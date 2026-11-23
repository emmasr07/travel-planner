# The code checks of docs/backend-logic.md section 5, one function each, and the final status per experience.
# Every check returns {"name", "result": "ok" | "warn" | "fail" | "skip", "detail"}. Money comparisons are asked
# of budget.py; times are local to the destination ("HH:MM" on trip day N), compared in minutes after midnight.
import re
from datetime import date, timedelta

from backend import budget
from backend.schema import validate_delivery, validate_verdicts
from backend.sources.osm_hours import has_holiday_rules, open_ranges
from backend.sources.viator import open_ranges as viator_open_ranges

PACE_LIMIT = {"chill": 2, "balanced": 3, "packed": 4}
AGE_FLOOR = {"18-24": 18, "25-34": 25, "35-49": 35, "50+": 50}
WHEELCHAIR = re.compile(r"wheel\s*-?\s*chair", re.I)
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
STATIC = ("schema", "source")     # decided once, at the checking step; the rest are re-run after every change
ORDER = ("schema", "source", "season", "age", "price", "hours", "closure", "overlap", "pace", "accessibility")
# Closure: words for "closed" in English, Portuguese, Italian, German, French and Spanish, as whole words.
# "ferme" without the accent is a farm, so French needs the é.
CLOSED = re.compile(r"\b(closed|encerrad[oa]s?|chius[oaie]|geschlossene?[nrs]?|fermée?s?|cerrad[oa]s?)\b", re.I)
# Temporarily or permanently closed always counts ("temporrariamente": as OpenStreetMap spells it in Lisbon).
FOR_NOW_OR_GOOD = re.compile(r"\b(tempor\w*|vorübergehend\w*|permanent\w*|definitiv\w*|définitiv\w*|dauerhaft\w*)",
                             re.I)
# A sentence that names weekdays or holidays is about the opening days ("Closed on Mondays"): the hours check's job.
# Portuguese segunda..sexta need a plural or "-feira" ("a quinta" is a farm).
CLOSED_DAYS = re.compile(
    r"\b(mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|weekends?|(bank |public )?holidays?"
    r"|(segunda|terça|terca|quarta|quinta|sexta)(s|-feiras?)|sábados?|domingos?|feriados?"
    r"|luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabat[oi]|domenic(a|he)|festiv[oiaà]\w*"
    r"|montags?|dienstags?|mittwochs?|donnerstags?|freitags?|samstags?|sonntags?|sonnabends?|feiertag\w*|wochenende\w*"
    r"|lundis?|mardis?|mercredis?|jeudis?|vendredis?|samedis?|dimanches?|fériés?"
    r"|lunes|martes|miércoles|miercoles|jueves|viernes|festivos?)\b", re.I)
# Free slots for a quick search or a swap: gaps of at least MIN_SLOT_MIN between DAY_START and DAY_END, local time.
DAY_START, DAY_END, MIN_SLOT_MIN = "08:00", "23:00", 30


def result(name, res, detail):
    return {"name": name, "result": res, "detail": detail}


# --- trip calendar ----------------------------------------------------------------------------------------------

def trip_days(profile):
    return (date.fromisoformat(profile["end_date"]) - date.fromisoformat(profile["start_date"])).days + 1


def date_of(profile, day):
    return date.fromisoformat(profile["start_date"]) + timedelta(days=day - 1)


def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def clock(mins):
    mins %= 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


def visit(e):
    """(start, end) in minutes on the scheduled day; end past 1440 when the visit ends after midnight."""
    s = e["schedule"]
    start, end = minutes(s["start"]), minutes(s["end"])
    return start, end + 1440 if end <= start else end


def _ranges_text(ranges):
    return ", ".join(f"{clock(a)}-{clock(b)}" for a, b in ranges)


# --- the delivery -----------------------------------------------------------------------------------------------

def delivery_errors(delivery, profile, *, quick=False):
    """Schema errors first (they stop here); then duplicate ids and schedules that don't fit the trip.
    In agents mode these go back to the researcher to fix (up to 3 deliveries)."""
    errors = validate_delivery(delivery, quick=quick)
    if errors:
        return errors
    exps = delivery["experiences"]
    ids = [e["id"] for e in exps]
    errors += [f"id {i} appears twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    days = trip_days(profile)
    for e in exps:
        s = e["schedule"]
        if not 1 <= s["day"] <= days:
            errors.append(f"{e['id']}: schedule day {s['day']} is outside a {days}-day trip")
        if e["duration_min"] is not None:
            expected = clock(minutes(s["start"]) + e["duration_min"])
            if s["end"] != expected:
                errors.append(f"{e['id']}: schedule end {s['end']} should be {expected} "
                              f"(start {s['start']} + {e['duration_min']} min)")
    return errors


def min_age_errors(delivery):
    """A minimum age only a source can state. Viator gives age bands for its prices, not a minimum age, and Geoapify
    none: an experience whose facts all come from them has no source for one ("Adult (18–99)" is not "18+").
    For an agent's delivery that already matches the schema; the samples are built by code and always say null."""
    return [f"{e['id']}: min_age {e['min_age']} has no source. Only a web page you read can state a minimum age "
            "(Viator and Geoapify give none, and a price label's age band is not one): set it to null, or cite the "
            "page that states it."
            for e in delivery["experiences"] if e["min_age"] is not None and not web_blocks(e)]


def quick_errors(delivery, ask):
    """A quick search or swap delivery (prompts/quick-search.md): new ids only, on the asked day, inside a free slot."""
    slots = ask["free_slots"]
    free = ", ".join(f"{f['start']}-{f['end']}" for f in slots) or f"none: day {ask['day']} is full, deliver an empty list"
    errors = []
    for e in delivery["experiences"]:
        s = e["schedule"]
        if e["id"] in ask["taken"]:
            errors.append(f"{e['id']}: this id is already in the trip: use another id")
        if s["day"] != ask["day"]:
            errors.append(f"{e['id']}: schedule day {s['day']} should be day {ask['day']}")
        start, end = visit(e)
        if not any(minutes(f["start"]) <= start and end <= minutes(f["end"]) for f in slots):
            errors.append(f"{e['id']}: {s['start']}-{s['end']} is not inside a free slot (free slots: {free})")
    return errors


def verdict_errors(verdicts, ids):
    """Schema errors first; then exactly one verdict for each experience the verifier received."""
    errors = validate_verdicts(verdicts)
    if errors:
        return errors
    got = [v["id"] for v in verdicts["verdicts"]]
    errors += [f"{i}: no verdict" for i in ids if i not in got]
    errors += [f"{i}: not an experience you received" for i in dict.fromkeys(got) if i not in ids]
    errors += [f"{i}: more than one verdict" for i in sorted({i for i in got if got.count(i) > 1})]
    return errors


def free_slots(profile, experiences, day):
    """[{start, end}] gaps on `day` between the kept items nothing rejected, within DAY_START-DAY_END."""
    busy = sorted(visit(e) for e in experiences if e["schedule"]["day"] == day and e["user"]["status"] == "kept"
                  and e.get("status") != "rejected")
    slots, t, day_end = [], minutes(DAY_START), minutes(DAY_END)
    for start, end in busy:
        if min(start, day_end) - t >= MIN_SLOT_MIN:
            slots.append((t, min(start, day_end)))
        t = max(t, end)
    if day_end - t >= MIN_SLOT_MIN:
        slots.append((t, day_end))
    return [{"start": clock(a), "end": clock(b)} for a, b in slots]


# --- one check each ---------------------------------------------------------------------------------------------

def schema_ok():
    return result("schema", "ok", "matches schemas/experiences.schema.json")


def web_blocks(e):
    """The fact source blocks that are web pages with a quote: the pages the source check reads."""
    blocks = [e["location"].get("source"), (e["price"] or {}).get("source"), (e["opening_hours"] or {}).get("source"),
              (e["rating"] or {}).get("source"), e["accessibility"].get("source")]
    return [b for b in blocks if b and b.get("provider") == "web" and b.get("quote")]


def normalise(text):
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def source(e, pages):
    """pages: url -> page text ("" when it did not load), or None when no page was read (demo mode)."""
    if pages is None:
        return result("source", "skip", "source pages not read in demo mode")
    blocks = web_blocks(e)
    if not blocks:
        return result("source", "skip", "no web quote to check: API data, recorded in data/sources-log.jsonl")
    for b in blocks:
        page = pages.get(b["url"], "")
        if not page:
            return result("source", "warn", f"the source page did not load: {b['url']}")
        if normalise(b["quote"]) not in normalise(page):
            return result("source", "warn", f"the quote is not on the source page: {b['url']}")
    return result("source", "ok", "every quote is on its source page")


def season(e, profile):
    months = e["months"]
    if not months:
        return result("season", "ok", "all year")
    runs = ", ".join(MONTHS[m - 1] for m in months)
    when = date_of(profile, e["schedule"]["day"])
    if when.month in months:
        return result("season", "ok", f"runs in {runs}")
    return result("season", "warn", f"runs in {runs}; day {e['schedule']['day']} is in {MONTHS[when.month - 1]}")


def age(e, profile):
    min_age = e["min_age"]
    if min_age is None:
        return result("age", "ok", "no minimum age stated")
    youngest = profile.get("youngest_age")
    if youngest is None and profile["group_type"] == "family":
        return result("age", "warn", f"minimum age {min_age}; the youngest traveller's age is not known")
    if youngest is None:
        youngest = AGE_FLOOR[profile["age_range"]]
    if youngest < min_age:
        return result("age", "fail", f"minimum age {min_age}, the youngest traveller is {youngest}")
    return result("age", "ok", f"minimum age {min_age}")


def price(e, profile):
    p = e["price"]
    unit = "per person" if profile["budget"]["per"] == "person" else "for the group"
    if p["per"] == "free" or p["amount"] == 0:
        if not p.get("source"):                     # "free" is a fact like any price: without a source, unverified
            return result("price", "warn", "free, but no source says so: not verified")
        if p["per"] == "free":
            return result("price", "ok", "free")
    if p["amount"] is None:
        return result("price", "warn", "no source states a price: not counted in the budget")
    if p["amount_eur"] is None:
        return result("price", "warn", f"price in {p['currency']} could not be converted to EUR: not counted")
    cost = budget.item_cost(p, profile)
    if budget.alone_over_budget(p, profile):
        limit = budget.fmt(budget.limit(profile))
        return result("price", "fail", f"€{cost} {unit} alone is more than the whole budget (€{limit} {unit})")
    return result("price", "ok", f"€{cost} {unit}")


def hours(e, profile):
    oh, s = e["opening_hours"], e["schedule"]
    if not oh:
        return result("hours", "warn", "no opening hours known")
    if oh["slots"]:
        if s["start"] in oh["slots"]:
            return result("hours", "ok", f"starts at {s['start']}, one of the listed start times")
        return result("hours", "warn", f"starts at {s['start']}; listed start times: {', '.join(oh['slots'])}")
    when = date_of(profile, s["day"])
    day = f"{when:%a} {when.day} {when:%b}"
    if (oh.get("source") or {}).get("provider") == "viator":     # dated hours from Viator's schedule
        ranges = viator_open_ranges(oh["text"], when)
        if ranges is None:
            return result("hours", "warn", f"no opening hours from Viator for {day}")
    else:                                                         # OpenStreetMap syntax
        ranges = open_ranges(oh["text"], when)
    if ranges is None:
        text = oh["text"] if len(oh["text"]) <= 60 else oh["text"][:59] + "…"
        return result("hours", "warn", f"opening hours too complex to check: {text}")
    note = " (public-holiday hours not checked)" if has_holiday_rules(oh["text"]) else ""
    if not ranges:
        return result("hours", "warn", f"closed on {day}{note}")
    start, end = visit(e)
    if any(a <= start and end <= b for a, b in ranges):
        return result("hours", "ok", f"open {_ranges_text(ranges)} on {day}{note}")
    return result("hours", "warn",
                  f"{s['start']}-{s['end']} is outside the opening hours on {day} ({_ranges_text(ranges)}){note}")


def overlap(e, active):
    if e not in active:
        return result("overlap", "skip", _why_left_out(e))
    start, end = visit(e)
    day = e["schedule"]["day"]
    clashes = [o for o in active if o is not e and o["schedule"]["day"] == day
               and visit(o)[0] < end and start < visit(o)[1]]
    if not clashes:
        return result("overlap", "ok", f"no overlap on day {day}")
    names = "; ".join(f"{o['name']} ({o['schedule']['start']}-{o['schedule']['end']})" for o in clashes)
    return result("overlap", "warn", f"overlaps {names} on day {day}")


def pace(e, active, profile):
    if e not in active:
        return result("pace", "skip", _why_left_out(e))
    day, limit = e["schedule"]["day"], PACE_LIMIT[profile["pace"]]
    n = sum(1 for o in active if o["schedule"]["day"] == day)
    if n > limit:
        return result("pace", "warn", f"{n} experiences on day {day}; a {profile['pace']} pace allows {limit}")
    return result("pace", "ok", f"{n} of {limit} on day {day}")


def closure(e):
    """Fail when the source's description says the place is closed ("Encerrado temporariamente", "Chiuso per
    restauro"). A sentence that only names closed days ("Closed on Mondays") is left to the hours check."""
    text = e.get("description")
    if not text:
        return result("closure", "skip", "no description from the source")
    days_only = False
    for sentence in re.split(r"[.;!?\n]+", text):
        if not CLOSED.search(sentence):
            continue
        if CLOSED_DAYS.search(sentence) and not FOR_NOW_OR_GOOD.search(sentence):
            days_only = True
            continue
        quote = sentence.strip()
        quote = quote if len(quote) <= 100 else quote[:99] + "…"
        return result("closure", "fail", f'the source says it is closed: "{quote}"')
    if days_only:
        return result("closure", "ok", "closed on some days only: the hours check covers those")
    return result("closure", "ok", "the source does not say it is closed")


def accessibility(e, profile):
    if not WHEELCHAIR.search(profile.get("notes") or ""):
        return result("accessibility", "skip", "no wheelchair need in your notes")
    wheelchair = e["accessibility"]["wheelchair"]
    if wheelchair in ("no", "unknown"):
        return result("accessibility", "warn", f"you mentioned a wheelchair; wheelchair access: {wheelchair}")
    return result("accessibility", "ok", f"wheelchair access: {wheelchair}")


def _why_left_out(e):
    if e["user"]["status"] == "kept":
        return "rejected by the checks"
    return "an alternative: restore it to add it to your plan" if e["user"].get("alternative") else "removed by you"


# --- all of them ------------------------------------------------------------------------------------------------

def final_status(checks, verdict):
    results = {c["result"] for c in checks}
    v = (verdict or {}).get("verdict")
    if "fail" in results or v == "contradicted":
        return "rejected"
    if "warn" in results or v != "confirmed":
        return "to_check"
    return "verified"


def check_all(profile, experiences, pages=None):
    """The checking step: schema (the delivery already passed it) and source, then everything else."""
    for e in experiences:
        e["checks"] = [schema_ok(), source(e, pages)]
    recheck(profile, experiences)


def recheck(profile, experiences):
    """Re-runs every check except schema and source (after a keep/remove or a time change) and sets each status.
    Overlap and pace only look at kept items that nothing has rejected."""
    for e in experiences:
        kept = [c for c in e.get("checks", []) if c["name"] in STATIC]
        e["checks"] = kept + [season(e, profile), age(e, profile), price(e, profile), hours(e, profile), closure(e),
                              accessibility(e, profile)]
    active = [e for e in experiences
              if e["user"]["status"] == "kept" and final_status(e["checks"], e.get("verdict")) != "rejected"]
    for e in experiences:
        e["checks"] += [overlap(e, active), pace(e, active, profile)]
        e["checks"].sort(key=lambda c: ORDER.index(c["name"]))
        e["status"] = final_status(e["checks"], e.get("verdict"))
