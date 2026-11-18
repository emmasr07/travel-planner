# Fake Viator, Geoapify, Frankfurter and Tavily servers for tests: no network. Prices here are fixed test examples.
import json

import httpx

VIATOR_KEY = "test-viator-key-1234"
GEO_KEY = "test-geo-key-5678"
TAVILY_KEY = "tvly-test-key-9012"
ALL_KEYS = (VIATOR_KEY, GEO_KEY, TAVILY_KEY)

VIATOR_PROD = "api.viator.com"
VIATOR_SANDBOX = "api.sandbox.viator.com"
GEO = "api.geoapify.com"
FX = "api.frankfurter.dev"
TAVILY = "api.tavily.com"

DATES = ("2026-12-04", "2026-12-06")
ALL_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

# Lisbon meeting point used by most tests, and a Geoapify match 30 m away from it.
LISBON_CENTER = {"latitude": 38.7223, "longitude": -9.1393}
MEETING = {"latitude": 38.7077, "longitude": -9.1365}


class FakeAPIs:
    """Routes requests by (method, host + path) to canned JSON and records every request."""

    def __init__(self):
        self.routes = {}
        self.requests = []

    def add(self, method, host_path, response):
        self.routes[(method, host_path)] = response
        return self

    def handler(self, request):
        self.requests.append(request)
        route = self.routes.get((request.method, request.url.host + request.url.path))
        if route is None:
            return httpx.Response(404, json={"message": "no fake route"})
        if callable(route):
            route = route(request)
            if isinstance(route, httpx.Response):
                return route
        status, body = route if isinstance(route, tuple) else (200, route)
        return httpx.Response(status, json=body)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def sent(self, path_end):
        return [r for r in self.requests if r.url.path.endswith(path_end)]

    @staticmethod
    def body(request):
        return json.loads(request.content)


# ---------- Viator ----------

def destinations():
    return {"destinations": [
        {"destinationId": 6, "name": "Europe", "type": "REGION", "parentDestinationId": 1, "lookupId": "6"},
        {"destinationId": 62, "name": "Portugal", "type": "COUNTRY", "parentDestinationId": 6, "lookupId": "6.62",
         "defaultCurrencyCode": "EUR"},
        {"destinationId": 538, "name": "Lisbon", "type": "CITY", "parentDestinationId": 62, "lookupId": "6.62.538",
         "defaultCurrencyCode": "EUR", "timeZone": "Europe/Lisbon", "center": LISBON_CENTER},
        {"destinationId": 60, "name": "United Kingdom", "type": "COUNTRY", "parentDestinationId": 6, "lookupId": "6.60"},
        {"destinationId": 61, "name": "England", "type": "REGION", "parentDestinationId": 60, "lookupId": "6.60.61"},
        {"destinationId": 737, "name": "London", "type": "CITY", "parentDestinationId": 61, "lookupId": "6.60.61.737",
         "defaultCurrencyCode": "GBP", "timeZone": "Europe/London",
         "center": {"latitude": 51.5072, "longitude": -0.1276}},
        {"destinationId": 8, "name": "North America", "type": "REGION", "parentDestinationId": 1, "lookupId": "8"},
        {"destinationId": 75, "name": "Canada", "type": "COUNTRY", "parentDestinationId": 8, "lookupId": "8.75"},
        {"destinationId": 76, "name": "Ontario", "type": "REGION", "parentDestinationId": 75, "lookupId": "8.75.76"},
        {"destinationId": 5555, "name": "London", "type": "CITY", "parentDestinationId": 76, "lookupId": "8.75.76.5555",
         "defaultCurrencyCode": "CAD", "timeZone": "America/Toronto",
         "center": {"latitude": 42.9849, "longitude": -81.2453}},
    ]}


def tags():
    def tag(tag_id, name, parents=()):
        return {"tagId": tag_id, "parentTagIds": list(parents), "allNamesByLocale": {"en": name, "de": name + " (de)"}}
    return {"tags": [
        tag(21911, "Food & Drink"),
        tag(12000, "Food Tours", [21911]),
        tag(22046, "Adventure Tours"),
        tag(21909, "Outdoor Activities"),
        tag(12001, "Kayaking", [21909, 22046]),
        tag(11919, "Kid-Friendly"),
    ]}


def product_url(code, host="www.viator.com"):
    return f"https://{host}/tours/Lisbon/Test-Tour/d538-{code}?pid=P00000&mcid=42383&medium=api"


def summary(code, title, *, price=35.0, currency="EUR", tag_ids=(12000, 11919), reviews=(4.8, 120),
            description="Taste pastries and cheese in the old town. Finish with ginjinha. Then walk home.",
            url_host="www.viator.com", duration=None):
    item = {
        "productCode": code,
        "title": title,
        "description": description,
        "images": [
            {"isCover": False, "variants": [{"width": 100, "height": 100, "url": "https://img.example/other.jpg"}]},
            {"isCover": True, "variants": [
                {"width": 200, "height": 150, "url": "https://img.example/cover-200.jpg"},
                {"width": 720, "height": 480, "url": "https://img.example/cover-720.jpg"},
            ]},
        ],
        "duration": duration or {"fixedDurationInMinutes": 180},
        "pricing": {"summary": {"fromPrice": price}, "currency": currency},
        "productUrl": product_url(code, url_host),
        "destinations": [{"ref": "538", "primary": True}],
        "tags": list(tag_ids),
        "flags": [],
    }
    if reviews:
        item["reviews"] = {"totalReviews": reviews[1], "combinedAverageRating": reviews[0]}
    return item


def details(code, *, start_ref="LOC-aaa", pricing_type="PER_PERSON", additional=None):
    logistics = {"redemption": {"redemptionType": "NONE"}}
    if start_ref:
        logistics["start"] = [{"location": {"ref": start_ref}, "description": "Meet at the fountain."}]
    return {
        "status": "ACTIVE",
        "productCode": code,
        "timeZone": "Europe/Lisbon",
        "pricingInfo": {"type": pricing_type, "ageBands": [{"ageBand": "ADULT", "startAge": 18, "endAge": 99}]},
        "logistics": logistics,
        "additionalInfo": additional if additional is not None else [
            {"type": "WHEELCHAIR_ACCESSIBLE", "description": "Wheelchair accessible"},
            {"type": "PHYSICAL_EASY", "description": "Suitable for all physical fitness levels"},
        ],
    }


def schedule(code, *, start_times=("10:00", "14:00"), days=ALL_DAYS, season=("2026-01-01", None),
             unavailable=(), operating=None):
    record = {"daysOfWeek": list(days)}
    if start_times:
        record["timedEntries"] = [{"startTime": t} for t in start_times]
    if unavailable:
        record["unavailableDates"] = [{"date": d, "reason": "NOT_OPERATING"} for d in unavailable]
    s = {"startDate": season[0], "pricingRecords": [record]}
    if season[1]:
        s["endDate"] = season[1]
    if operating:
        s["operatingHours"] = operating
    return {"productCode": code, "bookableItems": [{"productOptionCode": "TG1", "seasons": [s]}],
            "currency": "EUR", "summary": {"fromPrice": 35.0}}


def locations(by_ref):
    return {"locations": [dict({"reference": ref, "provider": "TRIPADVISOR"}, **loc) for ref, loc in by_ref.items()]}


def meeting_location(name="Praça do Comércio", street="Praça do Comércio", center=MEETING):
    return {"name": name, "address": {"street": street, "administrativeArea": "Lisbon", "country": "Portugal",
                                      "countryCode": "PT"}, "center": center}


def viator_routes(apis, products, *, host=VIATOR_PROD, locs=None):
    """products: list of (summary, details, schedule). One search route answers every tag."""
    base = host + "/partner"
    apis.add("GET", base + "/destinations", destinations())
    apis.add("GET", base + "/products/tags", tags())
    wanted = {21911: [p[0] for p in products if 12000 in p[0]["tags"] or 21911 in p[0]["tags"]],
              22046: [p[0] for p in products if 22046 in p[0]["tags"] or 12001 in p[0]["tags"]]}

    def search(request):
        body = json.loads(request.content)
        found = []
        for t in body["filtering"].get("tags", []):
            found += wanted.get(t, [])
        return {"products": found, "totalCount": len(found)}

    apis.add("POST", base + "/products/search", search)
    for s, d, sch in products:
        apis.add("GET", base + "/products/" + s["productCode"], d)
        apis.add("GET", base + "/availability/schedules/" + s["productCode"], sch)
    locs = locs if locs is not None else {"LOC-aaa": meeting_location()}

    def bulk(request):
        refs = json.loads(request.content)["locations"]
        return locations({r: locs[r] for r in refs if r in locs})

    apis.add("POST", base + "/locations/bulk", bulk)
    return apis


# ---------- Geoapify ----------

def geocode(*, result_type="amenity", confidence=0.95, match_type="full_match", lat=38.70775, lon=-9.13618,
            name="Praça do Comércio", timezone="Europe/Lisbon", place_id="51abc"):
    return {"results": [{
        "name": name, "lat": lat, "lon": lon, "formatted": f"{name}, 1100-148 Lisbon, Portugal",
        "result_type": result_type, "place_id": place_id,
        "rank": {"confidence": confidence, "match_type": match_type},
        "timezone": {"name": timezone, "offset_STD": "+00:00"},
        "datasource": {"sourcename": "openstreetmap", "attribution": "© OpenStreetMap contributors"},
    }], "query": {"text": name}}


def reverse(*, lat=38.70775, lon=-9.13618, name="Praça do Comércio", timezone="Europe/Lisbon", distance=5.1):
    """Shape as returned live by /v1/geocode/reverse (checked 18 Nov 2026)."""
    return {"results": [{
        "name": name, "lat": lat, "lon": lon, "formatted": f"{name}, 1100-148 Lisbon, Portugal",
        "result_type": "amenity", "distance": distance, "place_id": "51rev",
        "timezone": {"name": timezone, "offset_STD": "+00:00"},
    }]}


def place_details(*, opening_hours="Tu-Su 10:00-18:00", wheelchair="yes"):
    raw = {"osm_id": 123, "osm_type": "n"}
    if opening_hours:
        raw["opening_hours"] = opening_hours
    if wheelchair:
        raw["wheelchair"] = wheelchair
    props = {"feature_type": "details", "name": "Praça do Comércio",
             "datasource": {"sourcename": "openstreetmap", "raw": raw}}
    if opening_hours:
        props["opening_hours"] = opening_hours
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": props}]}


def geo_routes(apis, *, geo=None, det=None, rev=None):
    apis.add("GET", GEO + "/v1/geocode/search", geo or geocode())
    apis.add("GET", GEO + "/v2/place-details", det or place_details())
    apis.add("GET", GEO + "/v1/geocode/reverse", rev or reverse())
    return apis


# ---------- Frankfurter ----------

def fx_routes(apis, rate=1.1998):
    apis.add("GET", FX + "/v2/rates", [{"date": "2026-11-18", "base": "GBP", "quote": "EUR", "rate": rate}])
    return apis


# ---------- Tavily ----------

def tavily_routes(apis):
    apis.add("POST", TAVILY + "/search", {"query": "q", "response_time": 0.5, "results": [
        {"title": "Tram 28", "url": "https://www.carris.pt/tram-28", "content": "Tram 28 runs daily.", "score": 0.9},
        {"title": "Blog", "url": "https://blog.example/tram", "content": "We rode it.", "score": 0.4},
    ]})
    apis.add("POST", TAVILY + "/extract", {"results": [
        {"url": "https://www.carris.pt/tram-28", "raw_content": "Tram 28 departs every 15 minutes from 07:00."},
    ], "failed_results": []})
    return apis


# ---------- Geoapify city lookup and Places (shapes as returned live, 18 Nov 2026) ----------

def city(*, name="Lisbon", lat=38.7077507, lon=-9.1365919, country_code="pt", timezone="Europe/Lisbon"):
    return {"results": [{"name": name, "city": name, "lat": lat, "lon": lon, "country_code": country_code,
                         "result_type": "city", "formatted": f"{name}, Country", "place_id": "51city",
                         "rank": {"confidence": 1, "match_type": "full_match"},
                         "timezone": {"name": timezone, "offset_STD": "+00:00"}}]}


def place(name, categories, *, osm=("w", 100), lat=38.71, lon=-9.13, website="https://www.example.pt/",
          hours=None, wheelchair=None, description=None, website_in="properties"):
    raw = {"osm_type": osm[0], "osm_id": osm[1], "name": name, "lat": lat, "lon": lon}
    props = {"name": name, "lat": lat, "lon": lon, "formatted": f"{name}, Rua Exemplo 1, 1100-001 Lisbon, Portugal",
             "categories": list(categories), "place_id": f"51{osm[0]}{osm[1]}", "distance": 100,
             "datasource": {"sourcename": "openstreetmap", "raw": raw}}
    if website and website_in == "properties":
        props["website"] = raw["website"] = website
    elif website:
        raw["contact:website"] = website
    if hours:
        props["opening_hours"] = raw["opening_hours"] = hours
    if wheelchair:
        raw["wheelchair"] = wheelchair
        props["facilities"] = {"wheelchair": wheelchair != "no"}
    if description:
        props["description"] = raw["description"] = description
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def places_routes(apis, features, *, city_json=None):
    apis.add("GET", GEO + "/v1/geocode/search", city_json or city())
    apis.add("GET", GEO + "/v2/places", {"type": "FeatureCollection", "features": list(features)})
    return apis
