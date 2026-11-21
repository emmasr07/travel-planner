# Viator Partner API v2, Basic Access: bookable experiences with price, rating, start times and wheelchair info,
# each fact with a source block. Spec: https://docs.viator.com/partner-api/technical/
import os
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from backend.sources.common import SourceError, env, fetch, source_block

PROVIDER = "viator"
BASE_URLS = {
    "sandbox": "https://api.sandbox.viator.com/partner",
    "production": "https://api.viator.com/partner",
}

# Candidate English tag names per interest, matched exactly (ignoring case) against the live /products/tags list.
# Viator's docs give ids for Food & Drink (21911), Adventure Tours (22046) and Evening Entertainment (18953).
# The other names still have to be checked against the live list: names that don't match are returned by
# interest_tags() as unmatched and are simply not searched. A tag also matches its child tags in a search.
INTEREST_TAG_NAMES = {
    "culture": ["Art & Culture", "Cultural Tours", "Historical Tours", "Museum Tickets & Passes"],
    "food": ["Food & Drink"],
    "nature": ["Nature & Wildlife", "Nature and Wildlife Tours", "Parks"],
    "nightlife": ["Nightlife", "Evening Entertainment"],
    "relax": ["Spa & Wellness", "Spas", "Wellness"],
    "adventure": ["Adventure Tours"],
    "shopping": ["Shopping Tours", "Shopping"],
}
OUTDOOR_TAG_NAMES = {"outdoor activities"}                          # 21909 in Viator's docs
SUITABLE_TAG_NAMES = {"kid-friendly": "family", "romantic": "couple"}  # Kid-Friendly is 11919 in Viator's docs
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
# Viator's age bands, as viator.com names them. TRAVELER (one price for every age) has no name to show.
AGE_BANDS = {"ADULT": "Adult", "SENIOR": "Senior", "YOUTH": "Youth", "CHILD": "Child", "INFANT": "Infant",
             "STUDENT": "Student"}
MAX_LOCATION_REFS = 500

# /destinations and /products/tags are big and change weekly: fetched once per run.
_cache = {}


def clear_cache():
    _cache.clear()


def base_url():
    name = os.getenv("VIATOR_ENV", "")
    if name not in BASE_URLS:
        raise SourceError("VIATOR_ENV must be 'sandbox' or 'production' (see .env.example)")
    return BASE_URLS[name]


def _call(method, path, *, summary, client, body=None, items=None):
    headers = {"exp-api-key": env("VIATOR_API_KEY"), "Accept": "application/json;version=2.0",
               "Accept-Language": "en-US"}
    return fetch(PROVIDER, method, base_url() + path, summary=summary, client=client, headers=headers,
                 json_body=body, items=items)


def record_id(code):
    return "viator-" + re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-")


# ---------- destinations and tags ----------

def _destinations(client):
    key = ("destinations", base_url())
    if key not in _cache:
        _cache[key] = _call("GET", "/destinations", summary="GET /destinations", client=client)["destinations"]
    return _cache[key]


def find_destination(destination, *, client=None):
    """'Lisbon' or 'London, England' (city, then any ancestor's name). Never guesses between two cities."""
    city, _, region = (part.strip() for part in destination.partition(","))
    everything = _destinations(client)
    by_id = {d["destinationId"]: d for d in everything}

    def ancestors(d):
        ids = [int(x) for x in str(d.get("lookupId", "")).split(".") if x.isdigit()]
        return [by_id[i]["name"] for i in ids[:-1] if i in by_id]

    found = [d for d in everything if d.get("type") == "CITY" and d.get("name", "").lower() == city.lower()]
    if region:
        found = [d for d in found if region.lower() in (a.lower() for a in ancestors(d))]
    if len(found) == 1:
        return found[0]
    if not found:
        raise SourceError(f"viator: no city called {destination!r} in /destinations")
    listed = "; ".join(f"{d['name']} ({d['destinationId']}) in {' > '.join(ancestors(d))}" for d in found)
    raise SourceError(f"viator: {destination!r} matches several cities: {listed}. Add the region, e.g. '{city}, <region>'")


def load_tags(*, client=None):
    """tagId -> {name (English), parents}."""
    key = ("tags", base_url())
    if key not in _cache:
        data = _call("GET", "/products/tags", summary="GET /products/tags", client=client)
        _cache[key] = {t["tagId"]: {"name": (t.get("allNamesByLocale") or {}).get("en"),
                                    "parents": t.get("parentTagIds") or []} for t in data["tags"]}
    return _cache[key]


def interest_tags(tags, interests):
    """Returns ({interest: [(tagId, name)]}, {interest: [candidate names not found in the live list]})."""
    by_name = {}
    for tag_id, tag in tags.items():
        if tag["name"]:
            by_name.setdefault(tag["name"].lower(), []).append(tag_id)
    mapping, unmatched = {}, {}
    for interest in interests:
        mapping[interest], unmatched[interest] = [], []
        for name in INTEREST_TAG_NAMES.get(interest, []):
            ids = sorted(by_name.get(name.lower(), []))
            if ids:
                mapping[interest] += [(i, tags[i]["name"]) for i in ids]
            else:
                unmatched[interest].append(name)
    return mapping, unmatched


def _names_with_ancestors(tag_ids, tags):
    seen, stack = set(), list(tag_ids)
    while stack:
        tag_id = stack.pop()
        if tag_id in seen or tag_id not in tags:
            continue
        seen.add(tag_id)
        stack += tags[tag_id]["parents"]
    return {tags[t]["name"].lower() for t in seen if tags[t]["name"]}


# ---------- search ----------

def search_viator(destination, interests, dates, *, per_interest=5, client=None):
    """Experiences for each interest on the trip dates, best rated first, in the destination's own currency.

    Each record has the experience fact fields (each fact block with its Viator source), plus `meeting_point`
    (name, street, lat, lng from /locations/bulk, or None) and `notes` (caveats for `doubts`).
    """
    start, end = (_as_date(d) for d in dates)
    dest = find_destination(destination, client=client)
    tags = load_tags(client=client)
    mapping, _ = interest_tags(tags, interests)
    currency = dest.get("defaultCurrencyCode")
    if not currency:
        raise SourceError(f"viator: no defaultCurrencyCode for {dest['name']}")

    found = {}
    for interest in interests:
        for tag_id, _name in mapping.get(interest, []):
            body = {
                "filtering": {"destination": str(dest["destinationId"]), "tags": [tag_id],
                              "startDate": start.isoformat(), "endDate": end.isoformat()},
                "sorting": {"sort": "TRAVELER_RATING", "order": "DESCENDING"},
                "pagination": {"start": 1, "count": per_interest},
                "currency": currency,
            }
            summary = (f"POST /products/search destination={dest['destinationId']} tags={tag_id} "
                       f"{start}..{end} currency={currency}")
            data = _call("POST", "/products/search", summary=summary, client=client, body=body,
                         items=lambda d: [record_id(p["productCode"]) for p in d.get("products") or []])
            for product in data.get("products") or []:
                found.setdefault(product["productCode"], (product, interest))

    enriched = []
    for code, (summary_, interest) in found.items():
        details = _call("GET", f"/products/{code}", summary=f"GET /products/{code}", client=client,
                        items=lambda d, c=code: [record_id(c)])
        schedule = _call("GET", f"/availability/schedules/{code}", summary=f"GET /availability/schedules/{code}",
                         client=client, items=lambda d, c=code: [record_id(c)])
        enriched.append((summary_, interest, details, schedule))

    refs = sorted({r for _, _, d, _ in enriched if (r := meeting_ref(d))})
    locations = _locations(refs, client)
    return [_record(s, interest, d, sch, locations.get(meeting_ref(d)), tags, (start, end))
            for s, interest, d, sch in enriched]


def _locations(refs, client):
    out = {}
    for i in range(0, len(refs), MAX_LOCATION_REFS):
        chunk = refs[i:i + MAX_LOCATION_REFS]
        data = _call("POST", "/locations/bulk", summary=f"POST /locations/bulk refs={len(chunk)}", client=client,
                     body={"locations": chunk},
                     items=lambda d: [loc.get("reference") for loc in d.get("locations") or []])
        out.update({loc["reference"]: loc for loc in data.get("locations") or []})
    return out


def meeting_ref(details):
    """The start point's location ref, else the redemption point's; special refs (MEET_AT_...) don't count."""
    logistics = details.get("logistics") or {}
    refs = [(s.get("location") or {}).get("ref") for s in logistics.get("start") or []]
    refs += [loc.get("ref") for loc in (logistics.get("redemption") or {}).get("locations") or []]
    return next((r for r in refs if r and r.startswith("LOC-")), None)


def _meeting_point(location):
    # GOOGLE locations only carry a Google Place id: no name or coordinates without Google's API.
    if not location or location.get("provider") != "TRIPADVISOR" or not location.get("name"):
        return None
    address = location.get("address") or {}
    center = location.get("center") or {}
    return {"name": location["name"], "street": address.get("street") or location.get("unstructuredAddress"),
            "lat": center.get("latitude"), "lng": center.get("longitude")}


# ---------- one record ----------

def _record(s, interest, details, schedule, location, tags, dates):
    url = s.get("productUrl")
    notes = []
    pricing = s.get("pricing") or {}
    amount = (pricing.get("summary") or {}).get("fromPrice")
    pricing_info = details.get("pricingInfo") or {}
    per, label = price_basis(amount, pricing.get("currency"), pricing_info, schedule)
    if per == "group":
        unit = (pricing_info.get("unitType") or "unit").lower()
        most = max((b.get("maxTravelersPerBooking") or 0 for b in pricing_info.get("ageBands") or []), default=0)
        notes.append(f"Viator prices this per group ({unit}), not per person"
                     + (f": up to {most} travellers per booking" if most else ""))
    duration, duration_note = _duration(s.get("duration") or {})
    if duration_note:
        notes.append(duration_note)
    names = _names_with_ancestors(s.get("tags") or [], tags)
    return {
        "id": record_id(s["productCode"]),
        "name": s.get("title"),
        "description": short_description(s.get("description") or ""),
        "category": interest,
        "tags": [tags[t]["name"] for t in s.get("tags") or [] if t in tags and tags[t]["name"]],
        "duration_min": duration,
        # fromPrice is Viator's "from" price; label says which of its prices that is, when the schedule shows it.
        "price": {"amount": amount, "currency": pricing.get("currency"), "per": per, "label": label,
                  "amount_eur": None, "fx": None, "source": source_block(PROVIDER, url) if amount is not None else None},
        "opening_hours": hours_from_schedule(schedule, dates, source_block(PROVIDER, url)),
        "months": months_from_schedule(schedule, dates[0]),
        "min_age": None,  # Viator gives age bands for pricing, not a minimum age
        "rating": _rating(s.get("reviews"), url),
        "indoor_outdoor": "outdoor" if names & OUTDOOR_TAG_NAMES else "unknown",
        "accessibility": accessibility(details, source_block(PROVIDER, url)),
        "suitable_for": {"values": [v for name, v in SUITABLE_TAG_NAMES.items() if name in names], "kind": "fact"},
        "booking_url": url,
        "photo_url": photo(s.get("images")),
        "meeting_point": _meeting_point(location),
        "notes": notes,
    }


def price_basis(amount, currency, pricing_info, schedule):
    """(per, label) of a from-price. A UNIT product's from-price is the price of one unit (vehicle, boat, group), as
    its schedule shows: per group, no label. Otherwise per person, labelled with its age band when Viator says."""
    if pricing_info.get("type") == "UNIT":
        return "group", None
    return "person", price_label(amount, currency, pricing_info, schedule) if amount is not None else None


def price_label(amount, currency, pricing_info, schedule):
    """Which of the product's prices the from-price is, from the schedule's per-person prices in the same currency:
    its age band ("Adult (18–65)") and, when that price needs a group, how many book together
    ("Adult (18–99), when 2 book together"). None when Viator doesn't say (no matching price, or two bands)."""
    if schedule.get("currency") != currency:
        return None
    tiers = [p for item in schedule.get("bookableItems") or [] for season in item.get("seasons") or []
             for record in season.get("pricingRecords") or [] for p in record.get("pricingDetails") or []
             if p.get("pricingPackageType") == "PER_PERSON" and _same_price(_retail(p), amount)]
    bands = {t.get("ageBand") for t in tiers}
    band = "ADULT" if "ADULT" in bands else next(iter(bands)) if len(bands) == 1 else None
    if band is None:
        return None
    fewest = min((t for t in tiers if t.get("ageBand") == band), key=lambda t: t.get("minTravelers") or 0)
    low, high = fewest.get("minTravelers") or 0, fewest.get("maxTravelers")
    name = AGE_BANDS.get(band)
    ages = next((b for b in pricing_info.get("ageBands") or [] if b.get("ageBand") == band), {})
    if name and ages.get("startAge") is not None and ages.get("endAge") is not None:
        name = f"{name} ({ages['startAge']}–{ages['endAge']})"
    if low <= 1:
        return name
    group = f"{low}" if high in (None, low) else f"{low}–{high}"
    return f"{name}, when {group} book together" if name else f"When {group} book together"


def _retail(pricing_detail):
    return ((pricing_detail.get("price") or {}).get("original") or {}).get("recommendedRetailPrice")


def _same_price(a, b):
    return a is not None and b is not None and round(float(a), 2) == round(float(b), 2)


def short_description(text, limit=300):
    """Up to two whole leading sentences within `limit`; one over-long sentence is cut at a word with '…'."""
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", text) if text else []
    out = ""
    for sentence in sentences[:2]:
        candidate = f"{out} {sentence}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    if out or not sentences:
        return out
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip() + "…"


def _duration(d):
    if d.get("fixedDurationInMinutes"):
        return d["fixedDurationInMinutes"], None
    low, high = d.get("variableDurationFromMinutes"), d.get("variableDurationToMinutes")
    if low:
        return low, f"Duration varies: {low}–{high} min; duration_min is the shortest" if high else None
    if d.get("unstructuredDuration"):
        return None, f"Duration as Viator states it: {d['unstructuredDuration']}"
    return None, None


def _rating(reviews, url):
    if not reviews or not reviews.get("totalReviews") or reviews.get("combinedAverageRating") is None:
        return None
    return {"value": reviews["combinedAverageRating"], "scale": 5, "review_count": reviews["totalReviews"],
            "source": source_block(PROVIDER, url)}


def accessibility(details, source):
    infos = {i.get("type"): i for i in details.get("additionalInfo") or []}
    yes, no = "WHEELCHAIR_ACCESSIBLE" in infos, "NOT_WHEELCHAIR_ACCESSIBLE" in infos
    if yes != no:
        info = infos["WHEELCHAIR_ACCESSIBLE" if yes else "NOT_WHEELCHAIR_ACCESSIBLE"]
        return {"wheelchair": "yes" if yes else "no", "notes": info.get("description"), "source": source}
    return {"wheelchair": "unknown", "notes": None, "source": None}


def photo(images):
    images = images or []
    cover = next((i for i in images if i.get("isCover")), images[0] if images else None)
    variants = (cover or {}).get("variants") or []
    return max(variants, key=lambda v: v.get("width") or 0)["url"] if variants else None


# ---------- one product again (the code's re-check, backend/recheck.py) ----------

_PRODUCT_PATH = re.compile(r"/d\d+-([A-Za-z0-9]+)/?$")


def product_code(url):
    """The product code in a Viator product link ('…/tours/Rome/…/d511-5487240P3?…' -> '5487240P3'), or None."""
    link = urlparse(url or "")
    if not (link.hostname or "").endswith("viator.com"):
        return None
    found = _PRODUCT_PATH.search(link.path)
    return found.group(1) if found else None


def product_facts(code, dates, *, client=None):
    """The facts search_viator gives for one product, fetched again from /products/{code} (status, reviews, pricing
    type) and /availability/schedules/{code} (from-price, its currency, start times and opening hours on `dates`):
    {status, price: {amount, currency, per, label}, rating: {value, review_count} | None, opening_hours: {text, slots}
    | None}. The price is in the schedule's currency."""
    details = _call("GET", f"/products/{code}", summary=f"GET /products/{code}", client=client,
                    items=lambda d: [record_id(code)])
    schedule = _call("GET", f"/availability/schedules/{code}", summary=f"GET /availability/schedules/{code}",
                     client=client, items=lambda d: [record_id(code)])
    amount, currency = (schedule.get("summary") or {}).get("fromPrice"), schedule.get("currency")
    per, label = price_basis(amount, currency, details.get("pricingInfo") or {}, schedule)
    rating = _rating(details.get("reviews"), None)
    hours = hours_from_schedule(schedule, dates, None)
    return {"status": details.get("status"),
            "price": {"amount": amount, "currency": currency, "per": per, "label": label},
            "rating": {"value": rating["value"], "review_count": rating["review_count"]} if rating else None,
            "opening_hours": {"text": hours["text"], "slots": hours["slots"]} if hours else None}


# ---------- schedules ----------

def _as_date(d):
    return d if isinstance(d, date) else date.fromisoformat(str(d))


def _season_range(season):
    start = date.fromisoformat(season["startDate"])
    # No endDate: the season runs 384 days ahead (Viator spec).
    end = date.fromisoformat(season["endDate"]) if season.get("endDate") else date.max
    return start, end


def _unavailable(entries):
    return {u.get("date") for u in entries or []}


def hours_from_schedule(schedule, dates, source):
    """Start times (slots) and opening hours on the trip dates only, or None if the schedule has none."""
    start, end = (_as_date(d) for d in dates)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    slots, opening = set(), {}
    for item in schedule.get("bookableItems") or []:
        for season in item.get("seasons") or []:
            first, last = _season_range(season)
            for day in days:
                if not first <= day <= last:
                    continue
                weekday, iso = WEEKDAYS[day.weekday()], day.isoformat()
                records = [r for r in season.get("pricingRecords") or []
                           if weekday in (r.get("daysOfWeek") or []) and iso not in _unavailable(r.get("unavailableDates"))]
                if not records:
                    continue
                for record in records:
                    for entry in record.get("timedEntries") or []:
                        if iso not in _unavailable(entry.get("unavailableDates")):
                            slots.add(entry["startTime"])
                for hours in season.get("operatingHours") or []:
                    if hours.get("dayOfWeek") == weekday:
                        for h in hours.get("operatingHours") or []:
                            opening.setdefault(iso, set()).add(f"{h['opensAt']}–{h['closesAt']}")
    if not slots and not opening:
        return None
    span = f"{days[0]} to {days[-1]}" if len(days) > 1 else str(days[0])
    parts = []
    if slots:
        parts.append(f"Start times on {span}: {', '.join(sorted(slots))}")
    if opening:
        parts.append("Open " + "; ".join(f"{d} {', '.join(sorted(h))}" for d, h in sorted(opening.items())))
    return {"text": ". ".join(parts), "slots": sorted(slots), "source": source}


_OPEN_DATE = re.compile(r"(\d{4}-\d{2}-\d{2}) ([^;.]+)")
_OPEN_RANGE = re.compile(r"(\d{1,2}):(\d{2})(?::\d{2})?–(\d{1,2}):(\d{2})(?::\d{2})?")


def open_ranges(text, day):
    """[(start_min, end_min)] for one date, read back from the "Open <date> <from>–<to>, ...; <date> ..." part that
    hours_from_schedule writes (times as Viator gives them: "11:00" or "11:00:00"). None when the date isn't listed."""
    if "Open " not in text:
        return None
    for m in _OPEN_DATE.finditer(text.split("Open ", 1)[1]):
        if m.group(1) != day.isoformat():
            continue
        ranges = []
        for piece in m.group(2).split(","):
            found = _OPEN_RANGE.fullmatch(piece.strip())
            if not found:
                return None
            h1, m1, h2, m2 = map(int, found.groups())
            start, end = h1 * 60 + m1, h2 * 60 + m2
            ranges.append((start, end + 1440 if end <= start else end))   # "22:00–02:00" closes after midnight
        return sorted(ranges)
    return None


def months_from_schedule(schedule, start):
    """Months with a season in the year from `start`; [] when every month has one (all year)."""
    start = _as_date(start)
    window_end = start + timedelta(days=365)
    months = set()
    for item in schedule.get("bookableItems") or []:
        for season in item.get("seasons") or []:
            first, last = _season_range(season)
            first, last = max(first, start), min(last, window_end)
            year, month = first.year, first.month
            while first <= last and (year, month) <= (last.year, last.month):
                months.add(month)
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return [] if len(months) in (0, 12) else sorted(months)
