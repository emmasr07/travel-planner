# The business layer: what each click means for a trip, which rules apply and when the trip moves on.
#   researching -> checking -> verifying -> ready -> done   (or failed, keeping what was done before)
# The file is saved after every step and one line is added to `steps`, so the page can show the loop.
# Swap and quick search run beside a ready trip: their 1-3 options wait in trip["search"] until the user picks one.
# Facts come from sources (via agents.py), money from budget.py, checks from checks.py, files from store.py.
import copy
import re
import secrets
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from backend import access, agents, brochure, budget, checks, store
from backend.schema import validate_verdicts
from backend.sources.common import now_iso

NotBuilt = agents.NotBuilt
NotReady = agents.NotReady
Interest = Literal["culture", "food", "nature", "nightlife", "relax", "adventure", "shopping"]
BUSY = ("researching", "checking", "verifying")
_EDIT = threading.Lock()   # one change at a time: load, change, save


class NotFound(Exception):
    pass


class WrongState(Exception):
    """409: the trip is not in a state that allows this."""


class BadInput(Exception):
    """400: names the field that is wrong."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


# --- what the pages may send ---------------------------------------------------------------------------------

class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, max_digits=9, decimal_places=2)
    currency: Literal["EUR"] = "EUR"
    per: Literal["person", "total"]


class Profile(BaseModel):
    """The questionnaire answers, and nothing else (extra fields are refused)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    destination: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date
    group_type: Literal["solo", "couple", "friends", "family", "business"]
    group_size: int = Field(ge=1, le=30)
    age_range: Literal["18-24", "25-34", "35-49", "50+"]
    youngest_age: int | None = Field(default=None, ge=0, le=120)
    interests: list[Interest] = Field(min_length=1)
    budget: Budget
    pace: Literal["chill", "balanced", "packed"] = "balanced"
    notes: str = Field(default="", max_length=500)

    @field_validator("end_date")
    @classmethod
    def _ends_after_start(cls, end, info: ValidationInfo):
        start = info.data.get("start_date")
        if start and end < start:
            raise ValueError("the end date must be on or after the start date")
        return end

    @field_validator("interests")
    @classmethod
    def _unique(cls, interests):
        return list(dict.fromkeys(interests))


class Ask(BaseModel):
    """A last-minute request for one day of the trip (quick search)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request: str = Field(min_length=3, max_length=300)
    day: int = Field(ge=1)


class Change(BaseModel):
    """Keep/remove and/or a new day and start time for one experience."""
    model_config = ConfigDict(extra="forbid")
    status: Literal["kept", "removed"] | None = None
    day: int | None = Field(default=None, ge=1)
    start: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

    @model_validator(mode="after")
    def _something(self):
        if self.status is None and self.day is None and self.start is None:
            raise ValueError("send a status (kept or removed) and/or a day and start time")
        return self


# --- creating a trip and running its steps -------------------------------------------------------------------

def _paid_run(code):
    """An agents run (a trip, a swap or a quick search) costs money: the access code (403), the setup (503), then
    today's count (429). Called last, once the request is otherwise accepted, so a refused request never counts."""
    access.require_code(code)
    agents.settings()                               # NotReady (503) until scripts/create_agents.py has run
    access.count_run()


def create_trip(profile: Profile, *, demo=False, code=None):
    """demo=True: a demo trip on the samples even when the server runs the agents (no code, never counted)."""
    mode = "demo" if demo else agents.mode()
    if mode == "agents":
        _paid_run(code)
        answers = profile.model_dump(mode="json")
        answers["timezone"] = None                  # found by code from the destination at the research step
        return _new_trip(mode, answers)
    found = agents.find_sample(profile.destination)
    if not found:
        cities = ", ".join(agents.demo_destinations())
        raise BadInput("destination", f"demo mode has sample data for {cities} only")
    slug, city, sample = found
    answers = profile.model_dump(mode="json")
    answers["destination"] = city
    answers["timezone"] = sample[0]["location"]["timezone"] if sample else None
    return _new_trip(mode, answers)


def _new_trip(mode, answers):
    trip = {"id": _new_id(answers["destination"]), "created": now_iso(), "mode": mode, "status": "researching",
            "profile": answers, "steps": [], "experiences": [], "totals": None, "brochure": None, "error": None}
    store.save(trip)
    return trip


def run_pipeline(trip_id):
    """Runs in the background after POST /api/trips. A step that fails stops here and sets `failed`."""
    trip = store.load(trip_id)
    profile, mode = trip["profile"], trip["mode"]

    def step(who, text):
        trip["steps"].append({"at": now_iso(), "who": who, "text": text})
        store.save(trip)

    def record(session):                               # agents mode: each session's cost, kept even if it fails
        trip.setdefault("sessions", []).append(session)
        store.save(trip)

    pages = {}                                         # url -> text of the pages the researcher read
    try:
        delivery = agents.research(profile, step, record=record, pages=pages, trip_mode=mode)
        trip["status"] = "checking"
        exps = delivery["experiences"]
        step("code", f"{len(exps)} experiences received: checking the schema, prices, dates, hours and ages")
        errors = checks.delivery_errors(delivery, profile)
        if errors:
            raise ValueError(f"the delivery does not match the schema ({len(errors)} errors), first: {errors[0]}")
        step("code", _convert_prices(exps, agents.rates(profile, exps, trip_mode=mode)))
        for e in exps:
            e["user"] = {"status": "kept", "position": None}
            e["verdict"] = None
        checks.check_all(profile, exps, pages=agents.source_pages(exps, pages, trip_mode=mode))  # demo: None
        alternatives = _keep_best_fit(profile, exps)
        if alternatives:
            days, pace = checks.trip_days(profile), profile["pace"]
            kept = sum(budget.counts(e) for e in exps)
            step("code", f"{kept} kept for {days} {'day' if days == 1 else 'days'} at a {pace} "
                         f"pace (up to {checks.PACE_LIMIT[pace]} a day), best fit first; {alternatives} more start as "
                         "alternatives you can restore")
        trip["experiences"] = exps
        _refresh(trip)
        trip["status"] = "verifying"
        step("code", "checks done: now verifying the sources")

        verdicts = agents.verify(profile, exps, step, record=record, trip_mode=mode)
        errors = validate_verdicts(verdicts)
        if errors:
            raise ValueError(f"the verdicts do not match the schema, first: {errors[0]}")
        by_id = {v["id"]: v for v in verdicts["verdicts"]}
        for e in exps:
            e["verdict"] = by_id.get(e["id"])
        _keep_best_fit(profile, exps)      # again: one the verifier contradicted gives its place to an alternative
        _refresh(trip)
        trip["status"] = "ready"
        count = {s: sum(e["status"] == s for e in exps) for s in ("verified", "to_check", "rejected")}
        step("code", f"ready: {count['verified']} verified, {count['to_check']} to check, "
                     f"{count['rejected']} rejected (hidden)" if exps else "ready: nothing to show, nothing invented")
    except Exception as exc:   # the page shows the error; the file keeps everything done before it
        trip["status"] = "failed"
        trip["error"] = f"{type(exc).__name__}: {exc}"
        store.save(trip)


def recover_interrupted():
    """At startup. The pipeline and the searches run in this process, so none survives a restart: a trip still in a
    busy step, or a search still searching, was cut off and would wait forever. Each becomes failed with a plain
    reason; everything done before is kept. A file that cannot be read is left as it is. Returns the ids changed."""
    changed = []
    for trip_id in store.trip_ids():
        with _EDIT:
            try:
                trip = store.load(trip_id)
            except (store.TripNotFound, ValueError):
                continue
            reasons = []
            if trip.get("status") in BUSY:
                reasons.append(f"the server restarted while the trip was {trip['status']}, so it stopped there")
                trip["status"], trip["error"] = "failed", reasons[-1]
            search = trip.get("search")
            if isinstance(search, dict) and search.get("status") == "searching":
                reasons.append("the server restarted during the search: ask again")
                search.update(status="failed", error=reasons[-1])
            if reasons:
                trip.setdefault("steps", []).extend({"at": now_iso(), "who": "code", "text": r} for r in reasons)
                store.save(trip)
                changed.append(trip_id)
    return changed


def _keep_best_fit(profile, exps):
    """The researcher lists up to 15 candidates, best fit first, and the pace may allow fewer (chill 2, balanced 3,
    packed 4 a day). Going down the list, one is kept while its day has room; the others start removed, as
    alternatives the user can restore. Rejected ones take no place (they stay hidden, as before). Returns how many are alternatives."""
    for e in exps:
        e["user"] = {"status": "kept", "position": None}
    checks.recheck(profile, exps)                    # which are rejected, whatever is kept
    limit, used, alternatives = checks.PACE_LIMIT[profile["pace"]], {}, 0
    for e in exps:
        day = e["schedule"]["day"]
        if e["status"] == "rejected":
            continue
        if used.get(day, 0) < limit:
            used[day] = used.get(day, 0) + 1
        else:
            e["user"] = {"status": "removed", "position": None, "alternative": True}
            alternatives += 1
    checks.recheck(profile, exps)
    return alternatives


def _set_status(e, status):
    """The user's own keep or remove: from now on it is their choice, not a code alternative."""
    e["user"]["status"] = status
    e["user"].pop("alternative", None)


def _convert_prices(exps, rates):
    """amount_eur and fx filled by code (budget.to_eur). A currency with no known rate stays unconverted."""
    eur = converted = missing = 0
    for e in exps:
        p = e["price"]
        if p["amount"] is None:
            missing += 1
        elif p["currency"] == "EUR":
            p["amount_eur"], eur = budget.to_eur(p["amount"], "EUR", None), eur + 1
        elif p["currency"] in rates:
            p["fx"] = rates[p["currency"]]
            p["amount_eur"], converted = budget.to_eur(p["amount"], p["currency"], p["fx"]), converted + 1
    unconverted = len(exps) - eur - converted - missing
    text = f"prices: {eur} in EUR, {converted} converted to EUR, {missing} without a price (not counted)"
    return text + (f", {unconverted} in a currency with no known rate (not counted)" if unconverted else "")


def _refresh(trip):
    for e in trip["experiences"]:
        e["cost_eur"] = budget.item_cost(e["price"], trip["profile"])
    trip["totals"] = budget.totals(trip["profile"], trip["experiences"])


def _new_id(city):
    slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")[:30] or "trip"
    return f"{slug}-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


# --- reading and changing a trip -----------------------------------------------------------------------------

def get_trip(trip_id):
    try:
        return store.load(trip_id)
    except store.TripNotFound:
        raise NotFound("no such trip") from None


def _require(trip, allowed):
    status = trip["status"]
    if status in allowed:
        return
    if status in BUSY:
        raise WrongState(f"the list is not ready yet: {status}")
    if status == "failed":
        raise WrongState(f"the trip failed: {trip.get('error')}")
    if status == "done":
        raise WrongState("the brochure is already built: change the list to build it again")
    raise WrongState(f"not allowed while the trip is {status}")


def _experience(trip, exp_id):
    for e in trip["experiences"]:
        if e["id"] == exp_id:
            return e
    raise NotFound(f"no experience {exp_id} in this trip")


def change_experience(trip_id, exp_id, change: Change):
    with _EDIT:
        trip = get_trip(trip_id)
        _require(trip, ("ready", "done"))
        e = _experience(trip, exp_id)
        profile, said = trip["profile"], []
        if change.status:
            if change.status == "kept" and e["status"] == "rejected":
                reason = next((c["detail"] for c in e["checks"] if c["result"] == "fail"), "the verifier contradicted it")
                raise WrongState(f"{e['name']} was rejected by the checks: {reason}")
            _set_status(e, change.status)
            said.append(change.status)
        if change.day is not None or change.start is not None:
            days, s = checks.trip_days(profile), e["schedule"]
            day = change.day if change.day is not None else s["day"]
            if day > days:
                raise BadInput("day", f"day {day} is outside your {days}-day trip")
            start = change.start or s["start"]
            start_min, end_min = checks.visit(e)
            length = e["duration_min"] or end_min - start_min     # keep the visit's length when no duration is known
            e["schedule"] = {"day": day, "start": start, "end": checks.clock(checks.minutes(start) + length)}
            said.append(f"moved to day {day} at {start}")
        checks.recheck(profile, trip["experiences"])
        _refresh(trip)
        if trip["status"] == "done":
            trip["status"], trip["brochure"] = "ready", None
            said.append("the brochure needs building again")
        trip["steps"].append({"at": now_iso(), "who": "user", "text": f"{e['name']}: {', '.join(said)}"})
        store.save(trip)
        return trip


def fit_budget(trip_id):
    """A proposal only: the user confirms each removal with change_experience."""
    trip = get_trip(trip_id)
    _require(trip, ("ready",))
    proposal = budget.fit_proposal(trip["profile"], trip["experiences"])
    names = {e["id"]: e for e in trip["experiences"]}
    proposal["remove"] = [{"id": i, "name": names[i]["name"], "cost_eur": names[i]["cost_eur"]}
                          for i in proposal["remove"]]
    return proposal


# --- swap, quick search and picking an option ---------------------------------------------------------------------

def start_swap(trip_id, exp_id, code=None):
    """Asks for 2-3 alternatives to one experience. The search runs in the background (run_search)."""
    with _EDIT:
        trip = get_trip(trip_id)
        _require(trip, ("ready",))
        e = _experience(trip, exp_id)
        if e["status"] == "rejected":
            raise WrongState(f"{e['name']} was rejected by the checks: it is not on your list")
        request = (f"Alternatives to {e['name']} ({e['category']}): 2 to 3 experiences of a similar type and price, "
                   f"for the same time if possible")
        return _start_search(trip, "swap", exp_id, request, e["schedule"]["day"], f"{e['name']}: swap asked", code)


def start_quick(trip_id, ask: Ask, code=None):
    """A last-minute request for one day. The search runs in the background (run_search)."""
    with _EDIT:
        trip = get_trip(trip_id)
        _require(trip, ("ready", "done"))
        days = checks.trip_days(trip["profile"])
        if ask.day > days:
            raise BadInput("day", f"day {ask.day} is outside your {days}-day trip")
        return _start_search(trip, "quick", None, ask.request, ask.day,
                             f"quick search for day {ask.day}: {ask.request}", code)


def _start_search(trip, kind, for_id, request, day, said, code):
    if (trip.get("search") or {}).get("status") == "searching":
        raise WrongState("a swap or quick search is already running: wait for its options")
    if trip.get("mode") == "agents":                 # a trip keeps the mode it was planned in
        if agents.mode() != "agents":
            raise WrongState("this trip was planned with the AI agents and this server runs the demo: "
                             "swap and quick search are off for it")
        _paid_run(code)
    trip["search"] = {"kind": kind, "for": for_id, "request": request, "day": day, "status": "searching",
                      "options": [], "error": None, "picked": None, "started": now_iso()}
    trip["steps"].append({"at": now_iso(), "who": "user", "text": said})
    store.save(trip)
    return trip


def run_search(trip_id):
    """Runs in the background after a swap or quick request: the options get the same conversion, checks and
    verification as the list. The trip itself stays ready; each step is saved without losing the user's changes."""
    trip = get_trip(trip_id)
    profile, search, mode = trip["profile"], trip["search"], trip.get("mode")

    def step(who, text):
        _update(trip_id, lambda t: t["steps"].append({"at": now_iso(), "who": who, "text": text}))

    def record(session):
        _update(trip_id, lambda t: t.setdefault("sessions", []).append(session))

    try:
        plan = [e for e in trip["experiences"] if e["id"] != search["for"]]
        left = budget.totals(profile, plan)
        ask = {"kind": search["kind"], "request": search["request"], "day": search["day"],
               "free_slots": checks.free_slots(profile, plan, search["day"]),
               "budget_left": {"amount": left["left"], "currency": "EUR", "per": profile["budget"]["per"]},
               "taken": [e["id"] for e in trip["experiences"]],
               "for": next((e for e in trip["experiences"] if e["id"] == search["for"]), None)}
        pages = {}
        delivery = agents.quick(profile, ask, step, record=record, pages=pages, trip_mode=mode)
        errors = checks.delivery_errors(delivery, profile, quick=True)
        if errors:
            raise ValueError(f"the options do not match the schema ({len(errors)} errors), first: {errors[0]}")
        options = delivery["experiences"]
        if not options:
            _update(trip_id, lambda t: _search_done(t, []))
            step("code", f"no options found for {search['request']!r}: nothing invented")
            return
        step("code", f"{len(options)} options received: " +
             _convert_prices(options, agents.rates(profile, options, trip_mode=mode)))
        for o in options:
            o["user"] = {"status": "kept", "position": None}
            o["verdict"] = None
        checks.check_all(profile, options, pages=agents.source_pages(options, pages, trip_mode=mode))
        verdicts = agents.verify(profile, options, step, record=record, trip_mode=mode)
        errors = validate_verdicts(verdicts)
        if errors:
            raise ValueError(f"the verdicts do not match the schema, first: {errors[0]}")
        by_id = {v["id"]: v for v in verdicts["verdicts"]}
        for o in options:
            o["verdict"] = by_id.get(o["id"])
        _update(trip_id, lambda t: _search_done(t, options))
        count = {s: sum(o["status"] == s for o in options) for s in ("verified", "to_check", "rejected")}
        step("code", f"options ready: {count['verified']} verified, {count['to_check']} to check, "
                     f"{count['rejected']} rejected")
    except Exception as exc:   # the page shows the error; the trip and its list are untouched
        _update(trip_id, lambda t: t["search"].update(status="failed", error=f"{type(exc).__name__}: {exc}"))


def _search_done(trip, options):
    """Each option checked as if added to the current plan (for a swap, without the item it replaces)."""
    search, profile = trip["search"], trip["profile"]
    plan = [copy.deepcopy(e) for e in trip["experiences"] if e["id"] != search["for"]]
    for o in options:
        checks.recheck(profile, plan + [o])
        o["cost_eur"] = budget.item_cost(o["price"], profile)
    search.update(status="ready", options=options)


def pick_option(trip_id, option_id):
    """The user's pick adds the option as kept; for a swap the item it replaces becomes removed (restorable)."""
    with _EDIT:
        trip = get_trip(trip_id)
        _require(trip, ("ready", "done"))
        search = trip.get("search")
        if not search or search["status"] == "failed":
            raise WrongState("no options to pick from: ask for a swap or a quick search first")
        if search["status"] == "searching":
            raise WrongState("the search is still running: wait for its options")
        if search["picked"]:
            raise WrongState("an option was already picked from this search: ask again for new options")
        option = next((o for o in search["options"] if o["id"] == option_id), None)
        if option is None:
            raise NotFound(f"no option {option_id} in this search")
        if option["status"] == "rejected":
            reason = next((c["detail"] for c in option["checks"] if c["result"] == "fail"), "the verifier contradicted it")
            raise WrongState(f"{option['name']} was rejected by the checks: {reason}")
        if any(e["id"] == option_id for e in trip["experiences"]):
            raise WrongState(f"{option['name']} is already in the trip")
        new = copy.deepcopy(option)
        new["user"] = {"status": "kept", "position": None}
        trip["experiences"].append(new)
        said = f"picked {option['name']}"
        old = next((e for e in trip["experiences"] if e["id"] == search["for"]), None)
        if old is not None:
            _set_status(old, "removed")
            said += f" instead of {old['name']}"
        search["picked"] = option_id
        checks.recheck(trip["profile"], trip["experiences"])
        _refresh(trip)
        if trip["status"] == "done":
            trip["status"], trip["brochure"] = "ready", None
            said += ", the brochure needs building again"
        trip["steps"].append({"at": now_iso(), "who": "user", "text": said})
        store.save(trip)
        return trip


def _update(trip_id, change):
    """Load, change, save under the edit lock: a background search never overwrites the user's changes."""
    with _EDIT:
        trip = store.load(trip_id)
        change(trip)
        store.save(trip)


def build_brochure(trip_id):
    with _EDIT:
        trip = get_trip(trip_id)
        _require(trip, ("ready",))
        totals = trip["totals"]
        if not totals["kept"]:
            raise WrongState("keep at least one experience first")
        if totals["over"]:
            raise WrongState(f"over budget by €{totals['over_by']}: remove something or use Fit it to my budget")
        snapshot = brochure.build(trip)
        snapshot["map"], png = brochure.map_image(snapshot["stops"])
        if png:
            store.save_map(trip_id, png)
        trip["brochure"] = snapshot
        trip["status"] = "done"
        stops = snapshot["stops"]
        days = len({s["day"] for s in stops})
        where = "map from Geoapify" if png else f"map: {snapshot['map']['reason']}; pins placed by their coordinates"
        trip["steps"].append({"at": now_iso(), "who": "code", "text": f"brochure built: {len(stops)} stops over "
                                                                      f"{days} {'day' if days == 1 else 'days'}, {where}"})
        store.save(trip)
        return trip


def _built(trip):
    if trip["status"] != "done" or not trip.get("brochure"):
        raise WrongState("the brochure is not built yet: use Build my trip first")
    if "prices_note" not in trip["brochure"]:
        raise WrongState("this brochure was built by an older version: change the list, then Build my trip again")
    return trip["brochure"]


def brochure_pdf(trip_id):
    """The PDF, drawn on download from the sublist saved in the trip file (no PDF file is stored)."""
    trip = get_trip(trip_id)
    static = _built(trip)["map"]["kind"] == "static"
    return brochure.pdf(trip, store.load_map(trip_id) if static else None)


def brochure_map(trip_id):
    trip = get_trip(trip_id)
    png = store.load_map(trip_id) if _built(trip)["map"]["kind"] == "static" else None
    if png is None:
        raise NotFound("this brochure has no map image: its pins are placed by their coordinates")
    return png
