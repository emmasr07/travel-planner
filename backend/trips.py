# The business layer: what each click means for a trip, which rules apply and when the trip moves on.
#   researching -> checking -> verifying -> ready -> done   (or failed, keeping what was done before)
# The file is saved after every step and one line is added to `steps`, so the page can show the loop.
# Facts come from sources (via agents.py), money from budget.py, checks from checks.py, files from store.py.
import re
import secrets
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from backend import agents, brochure, budget, checks, store
from backend.schema import validate_verdicts
from backend.sources.common import now_iso

NotBuilt = agents.NotBuilt
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

def create_trip(profile: Profile):
    mode = agents.mode()
    if mode != "demo":
        raise NotBuilt("agents mode is not built yet (session 2): set MODE=demo in .env")
    found = agents.find_sample(profile.destination)
    if not found:
        cities = ", ".join(agents.demo_destinations())
        raise BadInput("destination", f"demo mode has sample data for {cities} only")
    slug, city, sample = found
    answers = profile.model_dump(mode="json")
    answers["destination"] = city
    answers["timezone"] = sample[0]["location"]["timezone"] if sample else None
    trip = {"id": _new_id(city), "created": now_iso(), "mode": mode, "status": "researching", "profile": answers,
            "steps": [], "experiences": [], "totals": None, "brochure": None, "error": None}
    store.save(trip)
    return trip


def run_pipeline(trip_id):
    """Runs in the background after POST /api/trips. A step that fails stops here and sets `failed`."""
    trip = store.load(trip_id)
    profile = trip["profile"]

    def step(who, text):
        trip["steps"].append({"at": now_iso(), "who": who, "text": text})
        store.save(trip)

    try:
        delivery = agents.research(profile, step)
        trip["status"] = "checking"
        exps = delivery["experiences"]
        step("code", f"{len(exps)} experiences received: checking the schema, prices, dates, hours and ages")
        errors = checks.delivery_errors(delivery, profile, min_items=trip["mode"] != "demo")
        if errors:
            raise ValueError(f"the delivery does not match the schema ({len(errors)} errors), first: {errors[0]}")
        step("code", _convert_prices(exps, agents.sample_rates(profile["destination"])))
        for e in exps:
            e["user"] = {"status": "kept", "position": None}
            e["verdict"] = None
        checks.check_all(profile, exps, pages=None)     # source pages are read in agents mode (session 2)
        trip["experiences"] = exps
        _refresh(trip)
        trip["status"] = "verifying"
        step("code", "checks done: the verifier reopens every source")

        verdicts = agents.verify(profile, exps, step)
        errors = validate_verdicts(verdicts)
        if errors:
            raise ValueError(f"the verdicts do not match the schema, first: {errors[0]}")
        by_id = {v["id"]: v for v in verdicts["verdicts"]}
        for e in exps:
            e["verdict"] = by_id.get(e["id"])
        checks.recheck(profile, exps)
        _refresh(trip)
        trip["status"] = "ready"
        count = {s: sum(e["status"] == s for e in exps) for s in ("verified", "to_check", "rejected")}
        step("code", f"ready: {count['verified']} verified, {count['to_check']} to check, "
                     f"{count['rejected']} rejected (hidden)" if exps else "ready: nothing to show, nothing invented")
    except Exception as exc:   # the page shows the error; the file keeps everything done before it
        trip["status"] = "failed"
        trip["error"] = f"{type(exc).__name__}: {exc}"
        store.save(trip)


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
            e["user"]["status"] = change.status
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


def build_brochure(trip_id):
    with _EDIT:
        trip = get_trip(trip_id)
        _require(trip, ("ready",))
        totals = trip["totals"]
        if not totals["kept"]:
            raise WrongState("keep at least one experience first")
        if totals["over"]:
            raise WrongState(f"over budget by €{totals['over_by']}: remove something or use Fit it to my budget")
        stops = brochure.sublist(trip)
        trip["brochure"] = {"created_at": now_iso(), "stops": stops, "pdf": None}
        trip["status"] = "done"
        days = len({s["day"] for s in stops})
        trip["steps"].append({"at": now_iso(), "who": "code",
                              "text": f"brochure built: {len(stops)} stops over {days} {'day' if days == 1 else 'days'}"})
        store.save(trip)
        return trip


def brochure_pdf(trip_id):
    trip = get_trip(trip_id)
    if trip["status"] != "done":
        raise WrongState("the brochure is not built yet: use Build my trip first")
    raise NotBuilt("the PDF is not built yet (session 3)")
