# Builds data/samples/<city>.json from Geoapify Places (OpenStreetMap) while the Viator key isn't active:
# places near the city for all seven interests (museums and sights, restaurants and cafes, parks and viewpoints,
# bars and nightclubs, spas and beaches, activity parks and bike/boat rental, markets), with their official website
# as booking_url. FACT fields only, all from OSM via Geoapify; no price source yet (amount null).
# Never padded, at most 25, mixed round-robin so every interest found gets a few.
#   PY -m scripts.build_sample_places "Lisbon"
#   PY -m scripts.build_sample_places "London, England"
#   PY -m scripts.build_sample_places "Oslo" --currency NOK     (countries not in COUNTRY_CURRENCY)
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from backend.schema import SAMPLE_MAX_ITEMS, validate_sample
from backend.sources import geoapify
from backend.sources.osm_hours import months_open
from backend.sources.common import SourceAuthError, SourceError
from backend.sources.viator import short_description
from scripts.build_sample import INTERESTS, SAMPLES_DIR, interleave, slug

ROOT = Path(__file__).resolve().parent.parent
RADIUS_M = 5000
LIMIT = 100  # per search; 1 credit per 20 places
MAX_PLACES = SAMPLE_MAX_ITEMS
# What each interest searches. Categories: https://apidocs.geoapify.com/docs/places/#categories (checked 18 Nov 2026).
# There is none for live music, surfing, kayaking or a food market (markets are commercial.marketplace: shopping).
# service.beauty.spa is left out: in OSM it is mostly nail, lash and waxing studios.
CATEGORIES = {
    "culture": ["entertainment.museum", "entertainment.culture", "tourism.sights", "heritage", "tourism.attraction"],
    "food": ["catering.restaurant", "catering.cafe", "catering.food_court"],
    "nature": ["tourism.attraction.viewpoint", "leisure.park"],
    "nightlife": ["catering.bar", "catering.pub", "catering.biergarten", "catering.taproom", "adult.nightclub"],
    "relax": ["leisure.spa", "leisure.spa.public_bath", "beach", "natural.water.hot_spring"],
    "adventure": ["entertainment.activity_park", "entertainment.activity_park.climbing",
                  "entertainment.activity_park.trampoline", "entertainment.flying_fox", "entertainment.water_park",
                  "entertainment.escape_game", "sport.dive_centre", "sport.horse_riding", "rental.bicycle",
                  "rental.boat"],
    "shopping": ["commercial.marketplace"],
}
# One search per category. Geoapify loses results when several categories share a query (18 Nov 2026, central
# London: escape games alone 8 places, climbing alone 6, both together 0; the parent activity_park missed its climbing
# child), and a category with many places (bike-share docks) would crowd out the others in the nearest 100.
SEARCH_GROUPS = {category: [category] for categories in CATEGORIES.values() for category in categories}
# Geoapify answers a query it couldn't finish in time (about 20 s) with HTTP 200 and no places. An empty answer that
# took this long is asked again; one still empty after the retries is reported, never taken as "nothing there".
SLOW_EMPTY_S = 10
RETRIES = 2
CLOCK = time.monotonic
# Small objects, not visits.
SKIP_CATEGORIES = ("tourism.attraction.artwork", "tourism.attraction.clock", "tourism.attraction.fountain",
                   "tourism.sights.memorial")
# Interest from the OSM category, first rule that matches (a category matches its sub-categories too).
# Nightlife before food: a pub that serves food is a pub. Relax before nature: hot springs are natural.* too.
INTEREST_RULES = [
    ("shopping", ("commercial.marketplace",)),
    ("nightlife", ("catering.bar", "catering.pub", "catering.biergarten", "catering.taproom", "adult.nightclub")),
    ("food", ("catering.restaurant", "catering.cafe", "catering.food_court")),
    ("relax", ("leisure.spa", "beach", "natural.water.hot_spring")),
    ("adventure", ("entertainment.activity_park", "entertainment.flying_fox", "entertainment.water_park",
                   "entertainment.escape_game", "sport.dive_centre", "sport.horse_riding", "rental.bicycle",
                   "rental.boat")),
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
DUPLICATE_WEBSITE = "duplicate website"   # one booking site once: e.g. the docks of one bike-share
ONE_SEX = "open to one sex only (OSM tags or name)"
ON_REQUEST = "dropped on request"

# Who may enter, as OpenStreetMap states it: a tag (male=only, female=no, lgbtq:men=only...) or the name itself
# ("Trombeta Bath (men only)"). lgbtq=primary alone says a venue is LGBTQ, not who may enter: never a reason to drop.
ONE_SEX_NAME = re.compile(r"\b(men|women|ladies|gents|male|female)[\s-]+only\b", re.I)
# Places removed by hand, by OSM id, each with the reason. Add here only what the team asks for.
EXCLUDED_PLACES = {
    "osm-w65489507": "Sweatbox Sauna & Gym, London: the team asked on 18 Nov 2026 to drop men-only and adult saunas; "
                     "OpenStreetMap tags it only lgbtq=primary, which says nothing about who may enter.",
}


def _in(category, prefix):
    return category == prefix or category.startswith(prefix + ".")


def interest(categories):
    for name, prefixes in INTEREST_RULES:
        if any(_in(c, p) for c in categories for p in prefixes):
            return name
    return None


def one_sex_only(place):
    tags = place.get("entry_tags") or {}
    if any(tags.get(k) == "only" for k in ("male", "female", "lgbtq:men", "lgbtq:women")):
        return True
    if "no" in (tags.get("male"), tags.get("female")):
        return True
    return bool(ONE_SEX_NAME.search(place["name"] or ""))


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
    places, ids, no_answer = [], set(), []
    for categories in SEARCH_GROUPS.values():
        found, answered = _search((city["lat"], city["lng"]), categories, client)
        if not answered:
            no_answer.extend(categories)
        for place in found:
            if place["id"] is None or place["id"] not in ids:
                ids.add(place["id"])
                places.append(place)

    kept, dropped, seen, sites = [], Counter(), set(), set()
    for place in places:
        category = interest(place["categories"])
        website = first_website(place["website"])
        if not place["name"] or not place["id"]:
            reason = NO_NAME
        elif place["id"] in EXCLUDED_PLACES:
            reason = ON_REQUEST
        elif one_sex_only(place):
            reason = ONE_SEX
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
        elif website.lower().rstrip("/") in sites:
            reason = DUPLICATE_WEBSITE
        else:
            seen.add(place["name"].lower())
            sites.add(website.lower().rstrip("/"))
            kept.append(experience(place, category, city, currency))
            continue
        dropped[reason] += 1

    exps = interleave(kept)[:MAX_PLACES]
    report = {"city": city, "currency": currency, "candidates": len(places), "dropped": dict(dropped),
              "no_answer": no_answer}
    return exps, report


def _search(center, categories, client):
    """(places, answered): answered is False when every try came back empty only after SLOW_EMPTY_S."""
    for _ in range(1 + RETRIES):
        started = CLOCK()
        found = geoapify.search_places(center, categories, radius_m=RADIUS_M, limit=LIMIT, client=client)
        if found or CLOCK() - started < SLOW_EMPTY_S:
            return found, True
    return [], False


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
    print("per interest: " + ", ".join(f"{i} {sum(e['category'] == i for e in exps)}" for i in INTERESTS))
    if report["no_answer"]:
        print(f"Geoapify gave no answer in time for: {', '.join(report['no_answer'])} (tried {1 + RETRIES} times; "
              "run again later to fill them)")
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
