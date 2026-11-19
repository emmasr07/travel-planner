# Builds data/samples/<city>.json: real experiences from Viator, located with Geoapify, prices in EUR via
# Frankfurter, alongside the Geoapify places already in the file (scripts/build_sample_places.py), which are kept
# unchanged. FACT fields only (best_time, why_fits and schedule are left to the agent); never padded.
#   PY -m scripts.build_sample "Lisbon" [--start 2026-12-04 --end 2026-12-06]
#   PY -m scripts.build_sample "London, England"     (add the region when a city name is ambiguous)
import argparse
import itertools
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from backend import budget
from backend.schema import SAMPLE_MAX_ITEMS, validate_sample
from backend.sources import fx, geoapify, viator
from backend.sources.common import SourceAuthError, SourceError

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"
INTERESTS = ["culture", "food", "nature", "nightlife", "relax", "adventure", "shopping"]
MAX_ITEMS = 15            # Viator experiences per sample; the places already in the file fill the rest up to 25
# Results per tag search. In production (19 Nov 2026) most products give only a Google place id or a hotel pickup, so
# about 1 in 10 has a meeting point with coordinates: at 30, Lisbon 12, London 30, Matera 1.
VIATOR_PER_TAG = 30
MAX_DISTANCE_M = 1000
GEOAPIFY_PAUSE = 0.25  # free plan: 5 requests/second
DEFAULT_DATES = ("2026-12-04", "2026-12-06")

NO_MEETING_POINT = "no meeting point"
NO_COORDINATES = "no coordinates for the meeting point from Viator"
NO_MATCH = "no Geoapify address at Viator's meeting point"
TOO_FAR = "Geoapify address over 1 km from Viator's meeting point"
NO_TIMEZONE = "no timezone from Geoapify"
NO_BOOKING_URL = "no productUrl from Viator"


def interleave(records):
    """Round-robin over INTERESTS so the first 15 mix categories instead of being all food."""
    queues = {i: [r for r in records if r["category"] == i] for i in INTERESTS}
    out = []
    while any(queues.values()):
        for interest in INTERESTS:
            if queues[interest]:
                out.append(queues[interest].pop(0))
    return out


def distance_m(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def experience(rec, place, rate, city, dates):
    """The record in schema order: Viator facts, Geoapify location, code-filled EUR price, certainty and doubts."""
    price = dict(rec["price"])
    price["amount_eur"] = budget.to_eur(price["amount"], price["currency"], rate)
    price["fx"] = rate
    doubts = list(rec["notes"])
    if price["amount"] is None:
        doubts.append("No price from Viator")
    if rec["opening_hours"] is None:
        doubts.append(f"No start times or opening hours in Viator's schedule for {dates[0]} to {dates[1]}")
    if rec["accessibility"]["wheelchair"] == "unknown":
        doubts.append("Wheelchair access not stated by Viator")
    if rec["duration_min"] is None:
        doubts.append("No duration from Viator")
    if rec["rating"] is None:
        doubts.append("No reviews on Viator yet")
    return {
        "id": rec["id"],
        "name": rec["name"],
        "description": rec["description"],
        "category": rec["category"],
        "tags": rec["tags"],
        "location": {"city": city, "address": place["address"], "lat": place["lat"], "lng": place["lng"],
                     "timezone": place["timezone"], "source": place["source"]},
        "duration_min": rec["duration_min"],
        "price": price,
        "opening_hours": rec["opening_hours"],
        "months": rec["months"],
        "min_age": rec["min_age"],
        "rating": rec["rating"],
        "indoor_outdoor": rec["indoor_outdoor"],
        "accessibility": rec["accessibility"],
        "suitable_for": rec["suitable_for"],
        "booking_url": rec["booking_url"],
        "photo_url": rec["photo_url"],
        "certainty": "low" if price["amount"] is None or rec["opening_hours"] is None else "high",
        "doubts": "; ".join(doubts) or None,
    }


def build(destination, start, end, *, client=None):
    """Returns (experiences, report). Raises SourceError / SourceAuthError from the sources."""
    dest = viator.find_destination(destination, client=client)
    mapping, unmatched = viator.interest_tags(viator.load_tags(client=client), INTERESTS)
    records = viator.search_viator(destination, INTERESTS, (start, end), per_interest=VIATOR_PER_TAG, client=client)

    out, dropped = [], Counter()
    for rec in interleave(records):
        if len(out) == MAX_ITEMS:
            break
        meeting = rec["meeting_point"]
        if not rec["booking_url"]:
            dropped[NO_BOOKING_URL] += 1
            continue
        if not meeting:
            dropped[NO_MEETING_POINT] += 1
            continue
        if meeting["lat"] is None or meeting["lng"] is None:
            dropped[NO_COORDINATES] += 1
            continue
        # Located from Viator's own coordinates: a name search can match the wrong place.
        time.sleep(GEOAPIFY_PAUSE)
        place = geoapify.reverse_place(meeting["lat"], meeting["lng"], client=client)
        if not place:
            dropped[NO_MATCH] += 1
            continue
        if distance_m(meeting["lat"], meeting["lng"], place["lat"], place["lng"]) > MAX_DISTANCE_M:
            dropped[TOO_FAR] += 1
            continue
        if not place["timezone"]:
            dropped[NO_TIMEZONE] += 1
            continue
        rate = fx.eur_rate(rec["price"]["currency"], client=client)
        out.append(experience(rec, place, rate, dest["name"], (start, end)))

    report = {"destination": dest, "tags": mapping, "unmatched_tag_names": unmatched,
              "candidates": len(records), "dropped": dict(dropped)}
    return out, report


def merge(viator_items, existing):
    """Up to MAX_ITEMS Viator experiences first, then the other places of the current sample in their order, up to
    SAMPLE_MAX_ITEMS in all. Old Viator items are replaced. Within an interest Viator and places alternate; then the
    interests take turns (interleave)."""
    viator_items = viator_items[:MAX_ITEMS]
    places = [e for e in existing if not e["id"].startswith("viator-")][:SAMPLE_MAX_ITEMS - len(viator_items)]
    ordered = []
    for interest in INTERESTS:
        pairs = itertools.zip_longest([e for e in viator_items if e["category"] == interest],
                                      [e for e in places if e["category"] == interest])
        ordered += [e for pair in pairs for e in pair if e is not None]
    return interleave(ordered)


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _line(e):
    """One Viator experience as the hand checks need it: price as Viator states it, label, rating, booking link."""
    price, rating = e["price"], e["rating"]
    if price["per"] == "free":
        cost = "free"
    elif price["amount"] is None:
        cost = "no price"
    else:
        eur = f" = €{price['amount_eur']}" if price["currency"] != "EUR" and price["amount_eur"] is not None else ""
        cost = f"{price['amount']} {price['currency']}{eur} per {price['per']}"
    stars = f"{round(rating['value'], 2):g}/5, {_plural(rating['review_count'], 'review')}" if rating else "no reviews"
    return f"- {e['name']} | {e['category']} | {cost} | label {price.get('label') or 'none'} | {stars} | {e['booking_url']}"


def slug(destination):
    return re.sub(r"[^a-z0-9]+", "-", destination.partition(",")[0].strip().lower()).strip("-")


def main(argv=None, *, client=None, load_env=True, out_dir=None):
    parser = argparse.ArgumentParser(description="Build data/samples/<city>.json from Viator, Geoapify and Frankfurter.")
    parser.add_argument("destination", help='a Viator city, e.g. "Lisbon" or "London, England"')
    parser.add_argument("--start", default=DEFAULT_DATES[0], help="trip start date, YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_DATES[1], help="trip end date, YYYY-MM-DD")
    args = parser.parse_args(argv)
    if load_env:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")

    try:
        exps, report = build(args.destination, args.start, args.end, client=client)
    except SourceAuthError as e:
        print(f"Stopped, nothing written: {e}")
        return 2
    except SourceError as e:
        print(f"Failed, nothing written: {e}")
        return 1

    dest = report["destination"]
    print(f"{dest['name']} (Viator {dest['destinationId']}), {args.start} to {args.end}, "
          f"prices in {dest.get('defaultCurrencyCode')}")
    for interest in INTERESTS:
        tags = ", ".join(f"{name} ({tag_id})" for tag_id, name in report["tags"][interest]) or "none"
        missing = report["unmatched_tag_names"][interest]
        print(f"  {interest}: tags {tags}" + (f"; not in Viator's tag list: {', '.join(missing)}" if missing else ""))
    print(f"{report['candidates']} candidates, {len(exps)} kept, dropped: {report['dropped'] or 'none'}")

    hosts = sorted({urlparse(e["booking_url"]).hostname for e in exps} - {"www.viator.com"})   # Viator items only
    if hosts:
        print(f"Refused, nothing written: booking links point to {', '.join(hosts)}, not www.viator.com "
              "(sandbox data?). Use VIATOR_ENV=production for real experiences.")
        return 1
    out_dir = Path(out_dir or SAMPLES_DIR)
    path = out_dir / f"{slug(args.destination)}.json"
    existing = json.loads(path.read_text(encoding="utf-8"))["experiences"] if path.exists() else []
    merged = merge(exps, existing)
    data = {"experiences": merged}
    errors = validate_sample(data)
    if errors:
        print("Refused, nothing written: the sample does not match the schema:")
        for err in errors[:20]:
            print("  " + err)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tours = [e for e in merged if e["id"].startswith("viator-")]
    places = len(merged) - len(tours)
    left_out = len([e for e in existing if not e["id"].startswith("viator-")]) - places
    print(f"Wrote {path}: {_plural(len(tours), 'Viator experience')} and {_plural(places, 'Geoapify place')}"
          + (f" (the last {_plural(left_out, 'place')} of the old file left out to stay within {SAMPLE_MAX_ITEMS})" if left_out else ""))
    for e in tours:
        print(_line(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
