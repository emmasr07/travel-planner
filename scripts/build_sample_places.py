# Builds data/samples/<city>.json from Geoapify Places (OpenStreetMap) while the Viator key isn't active:
# attractions, museums, viewpoints, parks and markets near the city, with their official website as booking_url.
# FACT fields only, all from OSM via Geoapify; no price source yet (amount null). Never padded, at most 15.
#   PY -m scripts.build_sample_places "Lisbon"
#   PY -m scripts.build_sample_places "London, England"
#   PY -m scripts.build_sample_places "Oslo" --currency NOK     (countries not in COUNTRY_CURRENCY)
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from backend.schema import validate_sample
from backend.sources import geoapify
from backend.sources.osm_hours import months_open
from backend.sources.common import SourceAuthError, SourceError
from backend.sources.viator import short_description
from scripts.build_sample import MAX_ITEMS, SAMPLES_DIR, interleave, slug

ROOT = Path(__file__).resolve().parent.parent
RADIUS_M = 5000
LIMIT = 100  # per search; 1 credit per 20 places
# One search per group, so the many museums and statues in a centre don't crowd out parks and markets.
SEARCH_GROUPS = {
    "culture": ["entertainment.museum", "entertainment.culture", "tourism.sights", "heritage", "tourism.attraction"],
    "nature": ["tourism.attraction.viewpoint", "leisure.park"],
    "shopping": ["commercial.marketplace"],
}
# Small objects, not visits.
SKIP_CATEGORIES = ("tourism.attraction.artwork", "tourism.attraction.clock", "tourism.attraction.fountain",
                   "tourism.sights.memorial")
# Interest from the OSM category, first rule that matches (a category matches its sub-categories too).
INTEREST_RULES = [
    ("shopping", ("commercial.marketplace",)),
    ("nature", ("tourism.attraction.viewpoint", "leisure.park", "natural")),
    ("culture", ("entertainment.museum", "entertainment.culture", "tourism.sights", "heritage",
                 "building.historic", "tourism.attraction")),
]
# Local currency per country, for the (still empty) price. Add a country here or pass --currency.
COUNTRY_CURRENCY = {"pt": "EUR", "it": "EUR", "gb": "GBP"}

SKIPPED = "artwork, memorial, clock or fountain"
NO_INTEREST = "category matches no interest"
NO_NAME = "no name"
NO_WEBSITE = "no website"
NOT_HTTP = "website is not an http(s) link"
DUPLICATE = "duplicate name"


def _in(category, prefix):
    return category == prefix or category.startswith(prefix + ".")


def interest(categories):
    for name, prefixes in INTEREST_RULES:
        if any(_in(c, p) for c in categories for p in prefixes):
            return name
    return None


def first_website(value):
    # OSM separates several values with ';'.
    return value.split(";")[0].strip() if value else None


def experience(place, category, city, currency):
    src = place["source"]
    hours = {"text": place["opening_hours"], "slots": [], "source": src} if place["opening_hours"] else None
    wheelchair = place["wheelchair"]
    months, months_read = months_open(place["opening_hours"])
    doubts = ["no price source yet"]
    if not hours:
        doubts.append("No opening hours in OpenStreetMap")
    if not months_read:
        doubts.append("Opening hours too complex to read the months reliably; months left as []")
    if wheelchair == "unknown":
        doubts.append("Wheelchair access not stated in OpenStreetMap")
    return {
        "id": place["id"],
        "name": place["name"],
        "description": short_description(place["description"] or ""),
        "category": category,
        "tags": place["categories"],
        "location": {"city": city["name"], "address": place["address"], "lat": place["lat"], "lng": place["lng"],
                     "timezone": city["timezone"], "source": src},
        "duration_min": None,
        "price": {"amount": None, "currency": currency, "per": "person", "amount_eur": None, "fx": None,
                  "source": None},
        "opening_hours": hours,
        "months": months,
        "min_age": None,
        "rating": None,
        "indoor_outdoor": "unknown",
        "accessibility": {"wheelchair": wheelchair, "notes": None, "source": src if wheelchair != "unknown" else None},
        "suitable_for": {"values": [], "kind": "fact"},
        "booking_url": first_website(place["website"]),
        "photo_url": None,
        "certainty": "medium" if months_read else "low",
        "doubts": "; ".join(doubts),
    }


def build(destination, *, currency=None, client=None):
    """Returns (experiences, report). Raises SourceError / SourceAuthError from the sources."""
    city = geoapify.find_city(destination, client=client)
    if not city:
        raise SourceError(f"geoapify: no city called {destination!r}")
    if not city["timezone"]:
        raise SourceError(f"geoapify: no timezone for {city['name']}")
    currency = currency or COUNTRY_CURRENCY.get(city["country_code"])
    if not currency:
        raise SourceError(f"no currency known for country {city['country_code']!r}: pass --currency")
    places, ids = [], set()
    for categories in SEARCH_GROUPS.values():
        for place in geoapify.search_places((city["lat"], city["lng"]), categories, radius_m=RADIUS_M, limit=LIMIT,
                                            client=client):
            if place["id"] is None or place["id"] not in ids:
                ids.add(place["id"])
                places.append(place)

    kept, dropped, seen = [], Counter(), set()
    for place in places:
        category = interest(place["categories"])
        website = first_website(place["website"])
        if not place["name"] or not place["id"]:
            reason = NO_NAME
        elif any(_in(c, p) for c in place["categories"] for p in SKIP_CATEGORIES):
            reason = SKIPPED
        elif not category:
            reason = NO_INTEREST
        elif not website:
            reason = NO_WEBSITE
        elif not website.startswith(("http://", "https://")):
            reason = NOT_HTTP
        elif place["name"].lower() in seen:
            reason = DUPLICATE
        else:
            seen.add(place["name"].lower())
            kept.append(experience(place, category, city, currency))
            continue
        dropped[reason] += 1

    exps = interleave(kept)[:MAX_ITEMS]
    report = {"city": city, "currency": currency, "candidates": len(places), "dropped": dict(dropped)}
    return exps, report


def main(argv=None, *, client=None, load_env=True, out_dir=None):
    parser = argparse.ArgumentParser(description="Build data/samples/<city>.json from Geoapify Places (OpenStreetMap).")
    parser.add_argument("destination", help='a city, e.g. "Lisbon" or "London, England"')
    parser.add_argument("--currency", help="ISO currency code when the country is not in COUNTRY_CURRENCY")
    args = parser.parse_args(argv)
    if load_env:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")

    try:
        exps, report = build(args.destination, currency=args.currency, client=client)
    except SourceAuthError as e:
        print(f"Stopped, nothing written: {e}")
        return 2
    except SourceError as e:
        print(f"Failed, nothing written: {e}")
        return 1

    city = report["city"]
    print(f"{city['name']} ({city['country_code']}, {city['timezone']}), within {RADIUS_M // 1000} km, "
          f"currency {report['currency']} (no prices yet)")
    print(f"{report['candidates']} places from Geoapify, {len(exps)} kept, dropped: {report['dropped'] or 'none'}")
    data = {"experiences": exps}
    errors = validate_sample(data)
    if errors:
        print("Refused, nothing written: the sample does not match the schema:")
        for err in errors[:20]:
            print("  " + err)
        return 1

    out_dir = Path(out_dir or SAMPLES_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug(args.destination)}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path} ({len(exps)} experiences)")
    for e in exps:
        hours = e["opening_hours"]["text"] if e["opening_hours"] else "no hours"
        print(f"- {e['name']} | {e['category']} | {hours} | wheelchair {e['accessibility']['wheelchair']} "
              f"| {e['booking_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
