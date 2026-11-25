# The code checks of docs/backend-logic.md section 5, one function each, and the final status per experience.
# Every check returns {"name", "result": "ok" | "warn" | "fail" | "skip", "detail"}. Money comparisons are asked
# of budget.py; times are local to the destination ("HH:MM" on trip day N), compared in minutes after midnight.
import math
import re
import unicodedata
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
ORDER = ("schema", "source", "season", "age", "price", "hours", "closure", "suggestion", "overlap", "pace",
         "accessibility")
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
# Facts a suggestion (best_time.reason, why_fits) may only repeat from the record's sources, as a code can spot them:
# a price (a currency next to a number), a clock time, a date (day and month), "free", and opening or closing.
_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_NUMBER = r"\d+(?:[.,]\d{3})*(?:[.,]\d{1,2})?"
CURRENCY = {"€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP"}
MONEY = re.compile(rf"(€|\$|£|\b(?:eur|usd|gbp)\b)\s?({_NUMBER})|\b({_NUMBER})\s?(€|\$|£|(?:eur|euros?|usd|gbp)\b)",
                   re.I)
CLOCK = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)(?:\s*([ap])\.?\s?m\b\.?)?", re.I)     # 16:30, 9.30, 8.30 am
HOUR = re.compile(r"\b(1[0-2]|0?[1-9])\s*([ap])\.?\s?m\b\.?", re.I)                       # 9 a.m., 10pm
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b", re.I)    # 6 Dec, 6th of December
MONTH_DAY = re.compile(rf"\b{_MONTH}\.?\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)  # Dec 6, February the 2nd
ISO_DATE = re.compile(r"\b\d{4}-(\d{2})-(\d{2})\b")
# "free" as a price; not gluten-free, "free time", "leaves the evening free", "feel free".
FREE = re.compile(r"(?<![-\w])(free|gratis|grátis|gratuit\w*|kostenlos\w*)\b", re.I)
FREE_TIME = re.compile(r"\b(?:morning|afternoon|evening|night|day|time)\s+free\b"
                       r"|\bfree\s+(?:time|morning|afternoon|evening|night)\b|\bfeel\s+free\b", re.I)
# Opening and closing; not open-air or open-top, and "close" (near) is not one.
OPENING = re.compile(r"\b(open(?:s|ed|ing)?(?![-\s](?:air|top)\b)|closed|closes|closing|closures?)\b", re.I)
# Free slots for a quick search or a swap: gaps of at least MIN_SLOT_MIN between DAY_START and DAY_END, local time.
DAY_START, DAY_END, MIN_SLOT_MIN = "08:00", "23:00", 30
# The same place: the same name, or the same spot in the same category. In Matera Viator's meeting point and the
# OpenStreetMap node of one museum are 8 m apart, while two different restaurants in Lisbon are 19 m apart.
SAME_PLACE_M = 15
# The same visit: a guided tour and an entry ticket that name the same place, pinned at two spots of it
# (Rome: the Colosseum and the Roman Forum, 493 m apart).
SAME_VISIT_M = 1000
# Words read on the plain text (lowercase, no accents or punctuation).
TOUR = re.compile(r"\b(tours?|guided|visita guidata|visite guidee|visita guiada|fuhrung)\b")
ENTRY = re.compile(r"\b(tickets?|entry|entrance|admission|bigliett[oi]|ingress[oi]|entradas?|bilhetes?|eintritt"
                   r"|billets?)\b")
INCLUDED = re.compile(r"\b(inclu\w*|inklusive|inbegriffen)\b|\bwith (entry|entrance|admission)\b")
NOT_INCLUDED = re.compile(r"\b(not|non|no|nao|nicht|pas|sans)( \w+){0,2} (inclu\w*|inbegriffen)\b|\bexclud\w*"
                          r"|\bwithout( \w+)? (entry|entrance|admission|tickets?)\b")
# Words too common to say two names are about one place.
GENERIC = set("tour tours guided guide ticket tickets entry entrance admission official skip line private small group "
              "with from visit experience self semi hour hours host full museum museums museo musei museu national "
              "city town historic center centre".split())


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


# --- the same place, the same visit -----------------------------------------------------------------------------

def _plain(text):
    """Lowercase, accents and punctuation removed: "Jerónimos: Entry-Tickets!" -> "jeronimos entry tickets"."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^\w\s]|_", " ", text).split())


def distance_m(a, b):
    """Metres between two experiences' coordinates (haversine)."""
    la, lb = a["location"], b["location"]
    p1, p2 = math.radians(la["lat"]), math.radians(lb["lat"])
    dp, dl = p2 - p1, math.radians(lb["lng"] - la["lng"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def same_place(a, b):
    """The same name after normalising, or within SAME_PLACE_M in the same category (a cooking class pinned on the
    Colosseum is not the Colosseum)."""
    if _plain(a["name"]) == _plain(b["name"]):
        return True
    return a["category"] == b["category"] and distance_m(a, b) <= SAME_PLACE_M


def _is_tour(e):
    return bool(TOUR.search(_plain(e["name"])))


def _is_ticket(e):
    return not _is_tour(e) and bool(ENTRY.search(_plain(f"{e['name']} {(e['price'] or {}).get('label') or ''}")))


def _place_words(e):
    city = set(_plain(e["location"].get("city")).split())
    return {w for w in _plain(e["name"]).split() if len(w) >= 4 and w not in GENERIC and w not in city}


def _says_entry(tour):
    """What the tour's own text (name, description, tags) says about entry: "included", "not included" or None."""
    included = excluded = False
    for sentence in re.split(r"[.;!?\n]+", "\n".join([tour["name"], tour.get("description") or "", *tour["tags"]])):
        text = _plain(sentence)
        if not ENTRY.search(text):
            continue
        if NOT_INCLUDED.search(text):
            excluded = True
        elif INCLUDED.search(text):
            included = True
    if included != excluded:
        return "included" if included else "not included"
    return None


def same_visit(a, b):
    """A guided tour and an entry ticket to the same place: "included" when the tour's source says entry is included,
    "unsure" when it says nothing (or both), None when it says entry is not included or they are not such a pair."""
    if _is_tour(a) and _is_ticket(b):
        tour, ticket = a, b
    elif _is_tour(b) and _is_ticket(a):
        tour, ticket = b, a
    else:
        return None
    if tour["category"] != ticket["category"]:
        return None
    if not same_place(tour, ticket) and not (_place_words(tour) & _place_words(ticket)
                                             and distance_m(tour, ticket) <= SAME_VISIT_M):
        return None
    says = _says_entry(tour)
    return None if says == "not included" else says or "unsure"


def twin_of(e, others):
    """The first of `others` that is the same place as e, or the same visit with entry included; else None."""
    return next((o for o in others if same_place(o, e) or same_visit(o, e) == "included"), None)


def _twin_reason(e, other):
    if same_place(other, e):
        return f"Same place as {other['name']}"
    visit = same_visit(other, e)
    if visit == "included":
        return f"Same visit as {other['name']}: its source says entry is included"
    if visit == "unsure":
        return f"May be the same visit as {other['name']}: check whether the tour includes entry"
    return None


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


def overlap(e, active, everyone=()):
    """A time clash with another kept item that day; and, said on the later of the two only, the same place or the
    same visit as an earlier kept item anywhere in the trip."""
    if e not in active:
        return result("overlap", "skip", _why_left_out(e, everyone))
    start, end = visit(e)
    day = e["schedule"]["day"]
    clashes = [o for o in active if o is not e and o["schedule"]["day"] == day
               and visit(o)[0] < end and start < visit(o)[1]]
    reasons = []
    if clashes:
        names = "; ".join(f"{o['name']} ({o['schedule']['start']}-{o['schedule']['end']})" for o in clashes)
        reasons.append(f"overlaps {names} on day {day}")
    earlier = active[:next(i for i, o in enumerate(active) if o is e)]
    reasons += [r for r in (_twin_reason(e, o) for o in earlier) if r]
    if not reasons:
        return result("overlap", "ok", f"no overlap on day {day}")
    return result("overlap", "warn", "; ".join(reasons))


def pace(e, active, profile, everyone=()):
    if e not in active:
        return result("pace", "skip", _why_left_out(e, everyone))
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


def _blank(m):
    return " " * len(m[0])      # keeps the other matches' positions


def _money(text):
    """(match, (amount, currency)) for each price written with its currency: "€16,50", "2 euros", "$1,200"."""
    for m in MONEY.finditer(text):
        symbol, number = (m[1], m[2]) if m[1] else (m[4], m[3])
        number = re.sub(r"[.,](?=\d{3}\b)", "", number).replace(",", ".")
        yield m, (budget.money(number), CURRENCY[symbol.lower()])


def _hhmm(h, mins, half):
    if half and half.lower() == "p" and h < 12:
        h += 12
    elif half and half.lower() == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mins:02d}"


def _times(text):
    """(match, "HH:MM") for each clock time: "16:30", "8.30 am", "10 p.m."; a price's "16.50" is not one."""
    text = MONEY.sub(_blank, text)
    for m in CLOCK.finditer(text):
        yield m, _hhmm(int(m[1]), int(m[2]), m[3])
    for m in HOUR.finditer(CLOCK.sub(_blank, text)):
        yield m, _hhmm(int(m[1]), 0, m[2])


def _month(name):
    return [mo.lower() for mo in MONTHS].index(name[:3].lower()) + 1


def _dates(text):
    """(match, (month, day)) for each date with its day: "6 Dec", "February the 2nd", "2026-12-06"."""
    for m in DAY_MONTH.finditer(text):
        yield m, (_month(m[2]), int(m[1]))
    for m in MONTH_DAY.finditer(text):
        yield m, (_month(m[1]), int(m[2]))
    for m in ISO_DATE.finditer(text):
        yield m, (int(m[1]), int(m[2]))


def _frees(text):
    return list(FREE.finditer(FREE_TIME.sub(_blank, text)))


def _facts(e):
    """What the record's sourced facts state: the price, the opening hours, and every web quote."""
    p, oh = e["price"], e["opening_hours"]
    texts = [b["quote"] for b in web_blocks(e)]
    if p.get("source"):
        texts.append(p.get("label") or "")
    if oh and oh.get("source"):
        texts += [oh["text"], *oh["slots"]]
    text = "\n".join(texts)
    money = {v for _, v in _money(text)}
    if p.get("source") and p["amount"] is not None:
        money.add((budget.money(p["amount"]), p["currency"]))
    return {"money": money, "times": {v for _, v in _times(text)}, "dates": {v for _, v in _dates(text)},
            "free": bool(p.get("source") and (p["per"] == "free" or p["amount"] == 0) or _frees(text)),
            "opening": bool(oh and oh.get("source") or OPENING.search(text))}


def _unsourced(text, facts):
    """The words of `text` that name a price, time, date, "free" or opening the facts don't state, in text order."""
    found = [(m.start(), m[0]) for kind, finder in (("money", _money), ("times", _times), ("dates", _dates))
             for m, value in finder(text) if value not in facts[kind]]
    if not facts["free"]:
        found += [(m.start(), m[0]) for m in _frees(text)]
    if not facts["opening"]:
        found += [(m.start(), m[0]) for m in OPENING.finditer(text)]
    return [word.strip() for _, word in sorted(found)]


def suggestion(e):
    """Warn when a suggestion names a price, clock time, date, "free" or opening/closing that the record's sourced
    facts don't state. best_time's reason counts only while it is shown: while the user keeps the suggested time."""
    best, facts = e.get("best_time") or {}, _facts(e)
    texts = [best.get("reason") if best.get("start") == e["schedule"]["start"] else None,
             (e.get("why_fits") or {}).get("text")]
    words = list(dict.fromkeys(w for t in texts if t for w in _unsourced(t, facts)))
    if words:
        return result("suggestion", "warn",
                      "suggestion mentions a fact not in the sources: " + ", ".join(f'"{w}"' for w in words))
    return result("suggestion", "ok", "the suggestions mention no fact beyond the sources")


def accessibility(e, profile):
    if not WHEELCHAIR.search(profile.get("notes") or ""):
        return result("accessibility", "skip", "no wheelchair need in your notes")
    wheelchair = e["accessibility"]["wheelchair"]
    if wheelchair in ("no", "unknown"):
        return result("accessibility", "warn", f"you mentioned a wheelchair; wheelchair access: {wheelchair}")
    return result("accessibility", "ok", f"wheelchair access: {wheelchair}")


def _why_left_out(e, everyone=()):
    if e["user"]["status"] == "kept":
        return "rejected by the checks"
    if not e["user"].get("alternative"):
        return "removed by you"
    twin = next((o for o in everyone if o["id"] == e["user"].get("same_as")), None)
    if twin is None:
        return "an alternative: restore it to add it to your plan"
    if same_place(twin, e):
        return f"Same place as {twin['name']}: restore it to add it to your plan"
    return f"Same visit as {twin['name']}, whose source says entry is included: restore it to add it to your plan"


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
                              suggestion(e), accessibility(e, profile)]
    active = [e for e in experiences
              if e["user"]["status"] == "kept" and final_status(e["checks"], e.get("verdict")) != "rejected"]
    for e in experiences:
        e["checks"] += [overlap(e, active, experiences), pace(e, active, profile, experiences)]
        e["checks"].sort(key=lambda c: ORDER.index(c["name"]))
        e["status"] = final_status(e["checks"], e.get("verdict"))
