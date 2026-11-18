# Geoapify Places samples (used while Viator's key isn't active): OpenStreetMap facts only, website as booking_url,
# no price yet. All HTTP is mocked (tests/fake_apis.py).
import json

import pytest

from backend.schema import validate_sample
from backend.sources import common, geoapify
from scripts import build_sample_places as bsp
from tests import fake_apis as fa
from tests.fake_apis import FakeAPIs


def log_lines():
    return [json.loads(line) for line in common.LOG_PATH.read_text().splitlines()]


def source_blocks(node):
    if isinstance(node, dict):
        if {"provider", "url", "retrieved_at", "quote"} <= set(node):
            yield node
        for value in node.values():
            yield from source_blocks(value)
    elif isinstance(node, list):
        for value in node:
            yield from source_blocks(value)


LISBON_PLACES = [
    fa.place("Museu Nacional do Azulejo", ["entertainment", "entertainment.museum", "tourism"], osm=("w", 1),
             website="https://www.museudoazulejo.gov.pt/", hours="Tu-Su 10:00-18:00", wheelchair="yes",
             description="Museum of Portuguese tiles. Housed in a former convent. Founded in 1965."),
    fa.place("Miradouro da Graça", ["tourism", "tourism.attraction", "tourism.attraction.viewpoint"], osm=("n", 2),
             website="https://www.visitlisboa.com/graca", wheelchair="no"),
    fa.place("Mercado de Campo de Ourique", ["commercial", "commercial.marketplace"], osm=("w", 3),
             website="https://www.mercadodecampodeourique.pt/; https://other.example/", website_in="raw"),
    fa.place("Jardim da Estrela", ["leisure", "leisure.park", "leisure.park.garden", "heritage"], osm=("w", 4),
             website="http://www.cm-lisboa.pt/estrela"),
    fa.place("Dom José I", ["tourism", "tourism.attraction", "tourism.attraction.artwork.statue"], osm=("n", 5),
             website="http://www.cm-lisboa.pt/jose"),
    fa.place("Castelo de São Jorge", ["tourism", "tourism.sights", "tourism.sights.castle"], osm=("w", 6),
             website=None),
    fa.place("Panteão Nacional", ["tourism.sights", "building.historic"], osm=("w", 7), website="www.panteao.pt"),
    fa.place("Museu Nacional do Azulejo", ["entertainment.museum"], osm=("r", 8),
             website="https://www.museudoazulejo.gov.pt/"),
]


# ---------- geoapify.find_city / search_places ----------

def test_find_city_request_and_record():
    apis = fa.places_routes(FakeAPIs(), [])
    with apis.client() as c:
        city = geoapify.find_city("London, England", client=c)
    [req] = apis.requests
    assert req.url.params["text"] == "London, England"
    assert req.url.params["type"] == "city" and req.url.params["format"] == "json"
    assert city["name"] == "Lisbon" and city["country_code"] == "pt" and city["timezone"] == "Europe/Lisbon"
    assert (city["lat"], city["lng"]) == (38.7077507, -9.1365919)
    assert city["source"]["provider"] == "geoapify" and fa.GEO_KEY not in city["source"]["url"]


def test_find_city_none_when_no_city():
    apis = fa.places_routes(FakeAPIs(), [], city_json={"results": []})
    with apis.client() as c:
        assert geoapify.find_city("Nowhere", client=c) is None


def test_search_places_request_and_records():
    apis = fa.places_routes(FakeAPIs(), LISBON_PLACES[:3])
    with apis.client() as c:
        found = geoapify.search_places((38.7077507, -9.1365919), ["entertainment.museum", "leisure.park"],
                                       radius_m=5000, limit=100, client=c)
    [req] = apis.requests
    assert req.url.path == "/v2/places"
    assert req.url.params["categories"] == "entertainment.museum,leisure.park"
    assert req.url.params["filter"] == "circle:-9.1365919,38.7077507,5000"
    assert req.url.params["bias"] == "proximity:-9.1365919,38.7077507"
    assert req.url.params["limit"] == "100" and req.url.params["apiKey"] == fa.GEO_KEY
    museum, viewpoint, market = found
    assert museum["id"] == "osm-w1"
    assert museum["name"] == "Museu Nacional do Azulejo"
    assert (museum["lat"], museum["lng"]) == (38.71, -9.13)
    assert museum["address"].startswith("Museu Nacional do Azulejo, Rua Exemplo 1")
    assert museum["categories"] == ["entertainment", "entertainment.museum", "tourism"]
    assert museum["website"] == "https://www.museudoazulejo.gov.pt/"
    assert museum["opening_hours"] == "Tu-Su 10:00-18:00"
    assert museum["wheelchair"] == "yes"
    assert museum["description"].startswith("Museum of Portuguese tiles.")
    assert viewpoint["wheelchair"] == "no" and viewpoint["opening_hours"] is None
    assert market["website"] == "https://www.mercadodecampodeourique.pt/; https://other.example/"  # raw contact:website
    for p in found:
        assert p["source"]["provider"] == "geoapify" and p["source"]["quote"] is None
        assert p["source"]["url"].startswith("https://api.geoapify.com/v2/places?")
        assert "apiKey" not in p["source"]["url"]
    [line] = log_lines()
    assert line["provider"] == "geoapify" and line["items"] == ["osm-w1", "osm-n2", "osm-w3"]
    assert fa.GEO_KEY not in common.LOG_PATH.read_text()


# ---------- scripts/build_sample_places.py ----------

@pytest.mark.parametrize("categories, expected", [
    (["commercial.marketplace", "heritage"], "shopping"),
    (["leisure.park.garden", "heritage"], "nature"),
    (["tourism.attraction.viewpoint"], "nature"),
    (["natural.water.sea"], "nature"),
    (["entertainment.museum"], "culture"),
    (["entertainment.culture.theatre"], "culture"),
    (["tourism.sights.castle"], "culture"),
    (["tourism", "tourism.attraction"], "culture"),
    (["leisure.playground"], None),
])
def test_interest_comes_from_the_osm_category(categories, expected):
    assert bsp.interest(categories) == expected


def test_build_lisbon_keeps_facts_and_drops_the_rest():
    apis = fa.places_routes(FakeAPIs(), LISBON_PLACES)
    with apis.client() as c:
        exps, report = bsp.build("Lisbon", client=c)

    assert validate_sample({"experiences": exps}) == []
    by_id = {e["id"]: e for e in exps}
    assert set(by_id) == {"osm-w1", "osm-n2", "osm-w3", "osm-w4"}
    assert [e["category"] for e in exps] == ["culture", "nature", "shopping", "nature"]  # round-robin
    assert report["dropped"] == {"artwork, memorial, clock or fountain": 1, "no website": 1,
                                 "website is not an http(s) link": 1, "duplicate name": 1}

    museum = by_id["osm-w1"]
    assert museum["booking_url"] == "https://www.museudoazulejo.gov.pt/"
    assert museum["location"] == {"city": "Lisbon", "address": museum["location"]["address"], "lat": 38.71,
                                  "lng": -9.13, "timezone": "Europe/Lisbon", "source": museum["location"]["source"]}
    assert museum["opening_hours"]["text"] == "Tu-Su 10:00-18:00" and museum["opening_hours"]["slots"] == []
    assert museum["accessibility"]["wheelchair"] == "yes"
    assert museum["description"] == "Museum of Portuguese tiles. Housed in a former convent."
    assert museum["tags"] == ["entertainment", "entertainment.museum", "tourism"]
    assert by_id["osm-w3"]["booking_url"] == "https://www.mercadodecampodeourique.pt/"  # first of OSM's ;-list
    for e in exps:
        assert e["price"] == {"amount": None, "currency": "EUR", "per": "person", "amount_eur": None,
                              "fx": None, "source": None}
        assert e["certainty"] == "medium"
        assert e["doubts"].startswith("no price source yet")
        assert e["duration_min"] is None and e["rating"] is None and e["min_age"] is None
        blocks = list(source_blocks(e))
        assert blocks and all(b["provider"] == "geoapify" for b in blocks)
    assert "No opening hours in OpenStreetMap" in by_id["osm-n2"]["doubts"]
    assert "Wheelchair access not stated in OpenStreetMap" in by_id["osm-w4"]["doubts"]
    assert by_id["osm-w4"]["accessibility"] == {"wheelchair": "unknown", "notes": None, "source": None}


def test_one_search_per_interest_group_so_parks_and_markets_are_not_crowded_out():
    apis = fa.places_routes(FakeAPIs(), LISBON_PLACES)
    with apis.client() as c:
        exps, report = bsp.build("Lisbon", client=c)
    searched = [r.url.params["categories"] for r in apis.sent("/v2/places")]
    assert searched == [",".join(cats) for cats in bsp.SEARCH_GROUPS.values()]
    assert len(exps) == 4 and report["candidates"] == len(LISBON_PLACES)  # same place twice is counted once


def test_months_come_from_the_osm_opening_hours():
    noha = fa.place("Casa Noha", ["tourism.sights"], osm=("n", 9), website="https://fondoambiente.it/luoghi/casa-noha",
                    hours="Feb-Mar: Th-Tu 10:00-17:00; Apr-Oct: Th-Tu 10:00-19:00")
    apis = fa.places_routes(FakeAPIs(), [noha])
    with apis.client() as c:
        [e], _ = bsp.build("Matera", client=c)
    assert e["months"] == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert e["certainty"] == "medium"
    assert "too complex" not in e["doubts"]


def test_hours_too_complex_leave_months_empty_with_a_doubt_and_low_certainty():
    church = fa.place("St Anne's Churchyard", ["leisure.park"], osm=("w", 10), website="https://www.example.org/",
                      hours="week 1-13 Mo-Su 10:00-16:00; week 14-43 10:00-18:00; week 44-52 10:00-16:00")
    apis = fa.places_routes(FakeAPIs(), [church])
    with apis.client() as c:
        [e], _ = bsp.build("Lisbon", client=c)
    assert e["months"] == []
    assert e["certainty"] == "low"
    assert "Opening hours too complex to read the months reliably; months left as []" in e["doubts"]
    assert e["doubts"].startswith("no price source yet")
    assert validate_sample({"experiences": [e]}) == []


def test_london_is_priced_in_gbp_with_no_conversion_call():
    london = fa.city(name="London", lat=51.5074, lon=-0.1278, country_code="gb", timezone="Europe/London")
    apis = fa.places_routes(FakeAPIs(), [fa.place("British Museum", ["entertainment.museum"], lat=51.5194,
                                                  lon=-0.127, website="https://www.britishmuseum.org/")],
                            city_json=london)
    with apis.client() as c:
        [e], _ = bsp.build("London, England", client=c)
    assert e["price"]["currency"] == "GBP" and e["price"]["amount"] is None and e["price"]["fx"] is None
    assert e["location"]["city"] == "London" and e["location"]["timezone"] == "Europe/London"
    assert apis.sent("/v2/rates") == []


def test_unknown_country_needs_a_currency():
    oslo = fa.city(name="Oslo", country_code="no", timezone="Europe/Oslo")
    apis = fa.places_routes(FakeAPIs(), [fa.place("Munch", ["entertainment.museum"])], city_json=oslo)
    with apis.client() as c:
        with pytest.raises(common.SourceError, match="--currency"):
            bsp.build("Oslo", client=c)
        [e], _ = bsp.build("Oslo", currency="NOK", client=c)
    assert e["price"]["currency"] == "NOK"


def test_never_more_than_15():
    many = [fa.place(f"Museum {i}", ["entertainment.museum"], osm=("n", i)) for i in range(30)]
    apis = fa.places_routes(FakeAPIs(), many)
    with apis.client() as c:
        exps, _ = bsp.build("Lisbon", client=c)
    assert len(exps) == 15


def test_main_writes_the_city_file(tmp_path, capsys):
    apis = fa.places_routes(FakeAPIs(), LISBON_PLACES)
    with apis.client() as c:
        assert bsp.main(["Lisbon"], client=c, load_env=False, out_dir=tmp_path) == 0
    assert validate_sample(json.loads((tmp_path / "lisbon.json").read_text())) == []
    out = capsys.readouterr().out
    assert "Museu Nacional do Azulejo" in out and "https://www.museudoazulejo.gov.pt/" in out


def test_main_stops_on_401_and_writes_nothing(tmp_path, capsys):
    apis = FakeAPIs().add("GET", fa.GEO + "/v1/geocode/search", (401, {"message": "Invalid apiKey"}))
    out_dir = tmp_path / "samples"
    with apis.client() as c:
        assert bsp.main(["Lisbon"], client=c, load_env=False, out_dir=out_dir) == 2
    assert not out_dir.exists()
    out = capsys.readouterr().out
    assert "geoapify" in out and "401" in out and fa.GEO_KEY not in out
