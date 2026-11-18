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


def test_never_more_than_25():
    many = [fa.place(f"Museum {i}", ["entertainment.museum"], osm=("n", i), website=f"https://museum{i}.pt/")
            for i in range(30)]
    apis = fa.places_routes(FakeAPIs(), many)
    with apis.client() as c:
        exps, _ = bsp.build("Lisbon", client=c)
    assert len(exps) == 25
    assert validate_sample({"experiences": exps}) == []


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


# ---------- food, nightlife, relax and adventure ----------

@pytest.mark.parametrize("categories, expected", [
    (["catering", "catering.restaurant", "catering.restaurant.portuguese"], "food"),
    (["catering.cafe", "catering.cafe.coffee_shop"], "food"),
    (["catering.food_court"], "food"),
    (["catering.bar"], "nightlife"),
    (["catering.pub", "catering.restaurant"], "nightlife"),             # a pub that serves food is still a pub
    (["catering.biergarten"], "nightlife"),
    (["catering.taproom"], "nightlife"),
    (["adult", "adult.nightclub"], "nightlife"),
    (["leisure.spa", "leisure.spa.public_bath"], "relax"),
    (["leisure.spa.sauna"], "relax"),
    (["beach", "beach.beach_resort"], "relax"),
    (["natural.water.hot_spring"], "relax"),                            # not nature, although it is natural.*
    (["entertainment.activity_park.climbing"], "adventure"),
    (["entertainment.activity_park.trampoline"], "adventure"),
    (["entertainment.flying_fox"], "adventure"),
    (["entertainment.water_park"], "adventure"),
    (["entertainment.escape_game"], "adventure"),
    (["sport.dive_centre"], "adventure"),
    (["sport.horse_riding"], "adventure"),
    (["rental.bicycle"], "adventure"),
    (["rental.boat"], "adventure"),
    (["commercial.marketplace", "catering.food_court"], "shopping"),    # markets stay shopping
    (["catering.fast_food"], None),                                     # not an experience
    (["commercial.outdoor_and_sport.water_sports"], None),             # a shop
    (["service.beauty.massage"], None),
    (["service.beauty", "service.beauty.spa"], None),                   # in OSM: nail, lash and waxing studios
])
def test_new_interests_come_from_the_osm_category(categories, expected):
    assert bsp.interest(categories) == expected


def test_every_interest_is_searched_and_each_search_serves_one_interest():
    served = {g: {bsp.interest([c]) for c in cats} for g, cats in bsp.SEARCH_GROUPS.items()}
    assert all(len(interests) == 1 and None not in interests for interests in served.values()), served
    assert set().union(*served.values()) == {"culture", "food", "nature", "nightlife", "relax", "adventure",
                                             "shopping"}


def test_one_category_per_search():
    # Geoapify (18 Nov 2026, central London): escape games alone 8 places, climbing alone 6, both in one query 0.
    # And the 100 nearest bike-rental places were all bike-share docks, which would crowd out anything sharing a query.
    assert all(len(cats) == 1 for cats in bsp.SEARCH_GROUPS.values())
    searched = [c for cats in bsp.SEARCH_GROUPS.values() for c in cats]
    assert len(searched) == len(set(searched))
    # The parent activity_park missed its climbing child, so the children are named.
    assert {"entertainment.activity_park.climbing", "entertainment.activity_park.trampoline"} <= set(searched)


def test_one_place_per_website():
    docks = [fa.place(f"Bicicletas Gira Estação {n}", ["rental.bicycle"], osm=("n", 300 + n),
                      website="https://www.gira-bicicletasdelisboa.pt/" + ("" if n % 2 else "/")) for n in range(3)]
    climbing = fa.place("Vertigo Climbing Center", ["entertainment.activity_park.climbing"], osm=("n", 400),
                        website="https://vertigoclimbing.pt/")
    apis = fa.places_routes(FakeAPIs(), docks + [climbing])
    with apis.client() as c:
        exps, report = bsp.build("Lisbon", client=c)
    assert [e["name"] for e in exps] == ["Bicicletas Gira Estação 0", "Vertigo Climbing Center"]
    assert report["dropped"] == {"duplicate website": 2}


def place_of(interest, i, **kw):
    cats = {"culture": ["entertainment.museum"], "food": ["catering.restaurant"], "nature": ["leisure.park"],
            "nightlife": ["catering.bar"], "relax": ["leisure.spa"], "adventure": ["rental.bicycle"],
            "shopping": ["commercial.marketplace"]}[interest]
    kw.setdefault("website", f"https://www.{interest}{i}.pt/")
    return fa.place(f"{interest.title()} place {i}", cats, osm=("n", 1000 + i), **kw)


def test_every_interest_gets_a_few_and_the_rest_is_never_padded():
    # 10 restaurants, 3 of each other interest except adventure (1): food can't crowd the others out.
    places = [place_of("food", i) for i in range(10)]
    places += [place_of(name, 100 + 10 * n + i) for n, name in
               enumerate(["culture", "nature", "nightlife", "relax", "shopping"]) for i in range(3)]
    places += [place_of("adventure", 200)]
    apis = fa.places_routes(FakeAPIs(), places)
    with apis.client() as c:
        exps, _ = bsp.build("Lisbon", client=c)
    # 26 found. Round-robin takes the others first, food fills the rest, and the cut at 25 leaves 9 food.
    counts = {i: sum(e["category"] == i for e in exps) for i in bsp.INTERESTS}
    assert counts == {"culture": 3, "food": 9, "nature": 3, "nightlife": 3, "relax": 3, "adventure": 1,
                      "shopping": 3}
    assert len(exps) == 25
    assert [e["category"] for e in exps[:7]] == ["culture", "food", "nature", "nightlife", "relax", "adventure",
                                                 "shopping"]
    assert validate_sample({"experiences": exps}) == []


def test_new_interests_follow_the_same_rules():
    pub = place_of("nightlife", 1, hours="Mo-Su 18:00-02:00", wheelchair="no")
    beach_bar = place_of("relax", 2, website=None)                     # no website: dropped
    spa = place_of("relax", 3, website="www.spa.pt")                   # not an http(s) link: dropped
    apis = fa.places_routes(FakeAPIs(), [pub, beach_bar, spa])
    with apis.client() as c:
        [e], report = bsp.build("Lisbon", client=c)
    assert e["category"] == "nightlife" and e["booking_url"] == "https://www.nightlife1.pt/"
    assert e["price"] == {"amount": None, "currency": "EUR", "per": "person", "amount_eur": None, "fx": None,
                          "source": None}
    assert e["doubts"].startswith("no price source yet")
    assert e["opening_hours"]["text"] == "Mo-Su 18:00-02:00" and e["accessibility"]["wheelchair"] == "no"
    assert all(b["provider"] == "geoapify" for b in source_blocks(e))
    assert report["dropped"] == {"no website": 1, "website is not an http(s) link": 1}


def test_main_prints_how_many_places_per_interest(tmp_path, capsys):
    apis = fa.places_routes(FakeAPIs(), [place_of("food", 1), place_of("food", 2), place_of("relax", 3)])
    with apis.client() as c:
        assert bsp.main(["Lisbon"], client=c, load_env=False, out_dir=tmp_path) == 0
    assert "per interest: culture 0, food 2, nature 0, nightlife 0, relax 1, adventure 0, shopping 0" \
        in capsys.readouterr().out


# ---------- places only one sex may enter, and places dropped on request ----------

def with_tags(feature, **tags):
    """The same fake place with extra raw OpenStreetMap tags (keys with ':' passed as '__')."""
    feature["properties"]["datasource"]["raw"].update({k.replace("__", ":"): v for k, v in tags.items()})
    return feature


def test_search_places_carries_the_osm_tags_on_who_may_enter():
    pleasure = with_tags(place_of("relax", 1), lgbtq="primary", lgbtq__men="only")
    apis = fa.places_routes(FakeAPIs(), [pleasure, place_of("relax", 2)])
    with apis.client() as c:
        tagged, plain = geoapify.search_places((38.7, -9.1), ["leisure.spa"], client=c)
    assert tagged["entry_tags"] == {"lgbtq:men": "only"}            # only the tags that say who may enter
    assert plain["entry_tags"] == {}


@pytest.mark.parametrize("tags, name", [
    ({"lgbtq__men": "only"}, "Pleasuredrome"),                       # London, OSM: lgbtq:men=only
    ({}, "Trombeta Bath (men only)"),                                 # Lisbon: only the name says it
    ({"male": "only"}, "Bath house"),
    ({"female": "no"}, "Bath house"),
    ({"female": "only"}, "Hammam for women"),                        # the same rule both ways
    ({"lgbtq__women": "only"}, "Bath house"),
    ({}, "Ladies-only spa"),
])
def test_places_only_one_sex_may_enter_are_dropped(tags, name):
    spa = with_tags(fa.place(name, ["leisure.spa", "leisure.spa.sauna"], osm=("n", 500),
                             website="https://bath.example/"), **tags)
    apis = fa.places_routes(FakeAPIs(), [spa])
    with apis.client() as c:
        exps, report = bsp.build("Lisbon", client=c)
    assert exps == [] and report["dropped"] == {"open to one sex only (OSM tags or name)": 1}


@pytest.mark.parametrize("tags, name", [
    ({"lgbtq": "primary"}, "Rainbow Bar"),                            # an LGBTQ venue is not a restriction
    ({"lgbtq": "primary", "lgbtq__men": "primary"}, "The Locker Room"),
    ({"male": "yes", "female": "yes"}, "Family Baths"),
    ({}, "Menorca Spa"),                                              # "men" inside a word
])
def test_places_open_to_everyone_are_kept(tags, name):
    spa = with_tags(fa.place(name, ["leisure.spa"], osm=("n", 501), website="https://open.example/"), **tags)
    apis = fa.places_routes(FakeAPIs(), [spa])
    with apis.client() as c:
        [e], _ = bsp.build("Lisbon", client=c)
    assert e["name"] == name


def test_places_dropped_on_request_are_listed_with_a_reason():
    assert "osm-w65489507" in bsp.EXCLUDED_PLACES                     # Sweatbox Sauna & Gym, London
    assert all(len(reason) > 20 for reason in bsp.EXCLUDED_PLACES.values())
    sweatbox = with_tags(fa.place("Sweatbox Sauna & Gym", ["leisure.spa.sauna"], osm=("w", 65489507),
                                  website="https://www.sweatboxsoho.com/"), lgbtq="primary")
    apis = fa.places_routes(FakeAPIs(), [sweatbox, place_of("relax", 3)])
    with apis.client() as c:
        exps, report = bsp.build("Lisbon", client=c)
    assert [e["name"] for e in exps] == ["Relax place 3"]
    assert report["dropped"] == {"dropped on request": 1}


def test_a_number_as_name_does_not_crash():
    # Real OSM data (Lisbon, 18 Nov 2026): some places have a number, not a string, as their name.
    numbered = fa.place("x", ["catering.restaurant"], osm=("n", 600), website="https://n25.example/")
    numbered["properties"]["name"] = 25
    apis = fa.places_routes(FakeAPIs(), [numbered])
    with apis.client() as c:
        [e], _ = bsp.build("Lisbon", client=c)
    assert e["name"] == "25"


# ---------- Geoapify's empty answers to slow queries ----------
# London, 18 Nov 2026: leisure.spa took 15-20 s and returned 13 places, but once took 22 s and returned none (HTTP 200).

class SlowGeoapify:
    """Stands in for geoapify.search_places: each query takes `seconds` on a fake clock; `empty` answers [] first."""

    def __init__(self, places, empty=None, seconds=20):
        self.places, self.empty, self.seconds, self.now, self.calls = places, dict(empty or {}), seconds, 0.0, []

    def clock(self):
        return self.now

    def search(self, center, categories, **kw):
        self.calls.append(categories[0])
        self.now += self.seconds
        if self.empty.get(categories[0], 0) > 0:
            self.empty[categories[0]] -= 1
            return []
        return [p for p in self.places if categories[0] in p["categories"]]


def record(name, category, i):
    return {"id": f"osm-n{i}", "name": name, "lat": 38.71, "lng": -9.13, "address": f"{name}, Lisbon",
            "categories": [category], "description": None, "website": f"https://{i}.example/", "opening_hours": None,
            "wheelchair": "unknown", "entry_tags": {}, "source": {"provider": "geoapify", "url": "https://x",
                                                                  "retrieved_at": "2026-11-18T18:00:00+01:00",
                                                                  "quote": None}}


@pytest.fixture
def slow(monkeypatch):
    def install(places, **kw):
        fake = SlowGeoapify(places, **kw)
        monkeypatch.setattr(bsp.geoapify, "search_places", fake.search)
        monkeypatch.setattr(bsp.geoapify, "find_city", lambda *a, **k: {
            "name": "Lisbon", "lat": 38.7, "lng": -9.1, "country_code": "pt", "timezone": "Europe/Lisbon"})
        monkeypatch.setattr(bsp, "CLOCK", fake.clock)
        return fake
    return install


def test_a_slow_empty_answer_is_asked_again(slow):
    fake = slow([record("Covent Garden Health Spa", "leisure.spa", 1)], empty={"leisure.spa": 1})
    exps, report = bsp.build("Lisbon")
    assert fake.calls.count("leisure.spa") == 2
    assert [e["name"] for e in exps] == ["Covent Garden Health Spa"] and "leisure.spa" not in report["no_answer"]


def test_a_fast_empty_answer_means_nothing_there(slow):
    fake = slow([], seconds=1)
    _, report = bsp.build("Lisbon")
    assert fake.calls.count("leisure.spa") == 1 and report["no_answer"] == []


def test_still_no_answer_is_reported_not_hidden(slow, tmp_path, capsys):
    fake = slow([record("Spa", "leisure.spa", 1)], empty={"leisure.spa": 9})
    _, report = bsp.build("Lisbon")
    assert fake.calls.count("leisure.spa") == 1 + bsp.RETRIES
    assert "leisure.spa" in report["no_answer"]
    slow([record("Spa", "leisure.spa", 1)], empty={"leisure.spa": 9})
    assert bsp.main(["Lisbon"], load_env=False, out_dir=tmp_path) == 0
    out = capsys.readouterr().out
    warning = next(line for line in out.splitlines() if line.startswith("Geoapify gave no answer in time for: "))
    assert "leisure.spa" in warning and "tried 3 times" in warning
