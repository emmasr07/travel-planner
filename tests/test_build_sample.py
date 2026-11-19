# scripts/build_sample.py: Viator experiences + Geoapify location + EUR price, FACT fields only, never padded.
# All HTTP is mocked (tests/fake_apis.py); prices are fixed test examples.
import json

import pytest

from backend.schema import SUGGESTION_FIELDS, validate_sample
from scripts import build_sample
from tests import fake_apis as fa
from tests.factories import experience
from tests.fake_apis import FakeAPIs


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(build_sample, "GEOAPIFY_PAUSE", 0)


def product(code, *, tag_ids=(12000,), start_ref="LOC-aaa", url_host="www.viator.com", price=35.0,
            currency="EUR", schedule=None):
    return (fa.summary(code, f"Tour {code}", tag_ids=tag_ids, url_host=url_host, price=price, currency=currency),
            fa.details(code, start_ref=start_ref),
            schedule or fa.schedule(code))


def lisbon_apis(products, locs=None):
    apis = FakeAPIs()
    fa.viator_routes(apis, products, locs=locs)
    fa.geo_routes(apis)
    return apis


def test_build_keeps_located_items_and_drops_the_rest():
    far = fa.meeting_location(name="Far away", center={"latitude": 38.80, "longitude": -9.30})
    apis = lisbon_apis(
        [product("P1"), product("P2", start_ref=None), product("P3", tag_ids=(12001,), start_ref="LOC-bbb")],
        locs={"LOC-aaa": fa.meeting_location(), "LOC-bbb": far})
    with apis.client() as c:
        exps, report = build_sample.build("Lisbon", *fa.DATES, client=c)

    assert [e["id"] for e in exps] == ["viator-p1"]
    assert validate_sample({"experiences": exps}) == []
    e = exps[0]
    assert e["location"]["city"] == "Lisbon"
    assert e["location"]["address"] == "Praça do Comércio, 1100-148 Lisbon, Portugal"
    assert (e["location"]["lat"], e["location"]["lng"]) == (38.70775, -9.13618)
    assert e["location"]["timezone"] == "Europe/Lisbon"
    assert e["location"]["source"]["provider"] == "geoapify"
    assert e["opening_hours"]["source"]["provider"] == "viator"
    assert e["accessibility"]["source"]["provider"] == "viator"
    assert e["price"]["amount_eur"] == 35.0 and e["price"]["fx"] is None
    for field in ("best_time", "why_fits", "schedule", "meeting_point", "notes"):
        assert field not in e
    assert e["certainty"] == "high" and e["doubts"] is None
    assert report["dropped"] == {"no meeting point": 1, "Geoapify address over 1 km from Viator's meeting point": 1}
    assert report["candidates"] == 3
    # Located by reverse geocoding Viator's coordinates, never by searching the name.
    [rev, _far] = apis.sent("/v1/geocode/reverse")
    assert (rev.url.params["lat"], rev.url.params["lon"]) == ("38.7077", "-9.1365")
    assert apis.sent("/v1/geocode/search") == []


def test_missing_facts_become_doubts_and_low_certainty():
    no_times = fa.schedule("P1", days=["MONDAY"])
    apis = lisbon_apis([product("P1", schedule=no_times)])
    apis.add("GET", fa.VIATOR_PROD + "/partner/products/P1", fa.details("P1", additional=[]))
    with apis.client() as c:
        [e], _ = build_sample.build("Lisbon", *fa.DATES, client=c)
    assert e["opening_hours"] is None
    assert e["certainty"] == "low"
    assert "No start times or opening hours in Viator's schedule for 2026-12-04 to 2026-12-06" in e["doubts"]
    assert "Wheelchair access not stated by Viator" in e["doubts"]


def test_no_geoapify_address_is_dropped():
    apis = lisbon_apis([product("P1")])
    apis.add("GET", fa.GEO + "/v1/geocode/reverse", {"results": []})
    with apis.client() as c:
        exps, report = build_sample.build("Lisbon", *fa.DATES, client=c)
    assert exps == []
    assert report["dropped"] == {"no Geoapify address at Viator's meeting point": 1}


def test_meeting_point_without_coordinates_is_dropped():
    no_center = fa.meeting_location(center={})
    apis = lisbon_apis([product("P1")], locs={"LOC-aaa": no_center})
    with apis.client() as c:
        exps, report = build_sample.build("Lisbon", *fa.DATES, client=c)
    assert exps == []
    assert report["dropped"] == {"no coordinates for the meeting point from Viator": 1}
    assert apis.sent("/v1/geocode/reverse") == []


def test_london_prices_are_converted_with_frankfurter():
    tower = fa.meeting_location(name="Tower of London", street="Tower Hill",
                                center={"latitude": 51.5081, "longitude": -0.0759})
    apis = FakeAPIs()
    fa.viator_routes(apis, [product("L1", price=20.0, currency="GBP")], locs={"LOC-aaa": tower})
    fa.geo_routes(apis, rev=fa.reverse(name="Tower of London", lat=51.50812, lon=-0.07595, timezone="Europe/London"))
    fa.fx_routes(apis)
    with apis.client() as c:
        [e], report = build_sample.build("London, England", *fa.DATES, client=c)
    assert report["destination"]["destinationId"] == 737
    assert e["location"]["city"] == "London"
    assert e["price"]["currency"] == "GBP" and e["price"]["amount"] == 20.0
    assert e["price"]["amount_eur"] == 24.0
    assert e["price"]["fx"]["from"] == "GBP" and e["price"]["fx"]["source"]["provider"] == "frankfurter"
    assert validate_sample({"experiences": [e]}) == []


def test_round_robin_mixes_categories():
    recs = [{"id": i, "category": c} for i, c in
            enumerate(["food", "food", "food", "adventure", "culture"])]
    assert [r["id"] for r in build_sample.interleave(recs)] == [4, 0, 3, 1, 2]


def test_never_more_than_15():
    apis = lisbon_apis([product(f"P{i}") for i in range(20)])
    with apis.client() as c:
        exps, _ = build_sample.build("Lisbon", *fa.DATES, client=c)
    assert len(exps) == 15


def test_main_writes_the_city_file(tmp_path, capsys):
    apis = lisbon_apis([product("P1")])
    with apis.client() as c:
        code = build_sample.main(["Lisbon"], client=c, load_env=False, out_dir=tmp_path)
    assert code == 0
    data = json.loads((tmp_path / "lisbon.json").read_text())
    assert validate_sample(data) == []
    out = capsys.readouterr().out
    assert "Tour P1" in out and fa.product_url("P1") in out


def test_main_slug_uses_the_city_part(tmp_path):
    tower = fa.meeting_location(name="Tower of London", center={"latitude": 51.5081, "longitude": -0.0759})
    apis = FakeAPIs()
    fa.viator_routes(apis, [product("L1", currency="GBP")], locs={"LOC-aaa": tower})
    fa.geo_routes(apis, rev=fa.reverse(lat=51.50812, lon=-0.07595, timezone="Europe/London"))
    fa.fx_routes(apis)
    with apis.client() as c:
        assert build_sample.main(["London, England"], client=c, load_env=False, out_dir=tmp_path) == 0
    assert (tmp_path / "london.json").exists()


def test_main_refuses_links_that_are_not_viator_com(tmp_path, capsys):
    apis = lisbon_apis([product("P1", url_host="shop.live.rc.viator.com")])
    out = tmp_path / "samples"
    with apis.client() as c:
        code = build_sample.main(["Lisbon"], client=c, load_env=False, out_dir=out)
    assert code == 1
    assert not out.exists()
    assert "www.viator.com" in capsys.readouterr().out


# --- Viator alongside the Geoapify places already in the sample -------------------------------------------------

def place(id, category):
    """A Geoapify place as scripts/build_sample_places.py writes it: no price, its website as booking_url."""
    e = experience(id, category=category, name=id.title(), booking_url=f"https://{id}.example/",
                   price={"amount": None, "label": None, "source": None})
    for field in SUGGESTION_FIELDS:
        e.pop(field)
    return e


def test_merge_puts_viator_first_and_alternates_with_the_places_within_each_interest():
    viator_items = [{"id": "viator-v1", "category": "food"}, {"id": "viator-v2", "category": "food"}]
    places = [{"id": "osm-c1", "category": "culture"}, {"id": "osm-f1", "category": "food"},
              {"id": "osm-f2", "category": "food"}, {"id": "osm-f3", "category": "food"}]
    merged = build_sample.merge(viator_items, places)
    assert [e["id"] for e in merged] == ["osm-c1", "viator-v1", "osm-f1", "viator-v2", "osm-f2", "osm-f3"]


def test_merge_drops_old_viator_items_and_the_last_places_to_stay_within_25():
    places = [{"id": f"osm-{i}", "category": "culture"} for i in range(24)] + [{"id": "viator-old", "category": "food"}]
    viator_items = [{"id": "viator-v1", "category": "food"}, {"id": "viator-v2", "category": "food"}]
    ids = [e["id"] for e in build_sample.merge(viator_items, places)]
    assert len(ids) == 25 and "viator-old" not in ids
    assert {"viator-v1", "viator-v2"} <= set(ids)
    assert [i for i in ids if i.startswith("osm-")] == [f"osm-{i}" for i in range(23)]   # file order, last ones out


def test_merge_never_keeps_more_than_15_viator_items():
    viator_items = [{"id": f"viator-{i}", "category": "culture"} for i in range(20)]
    merged = build_sample.merge(viator_items, [{"id": "osm-1", "category": "food"}])
    assert sum(e["id"].startswith("viator-") for e in merged) == 15 and len(merged) == 16


def test_viator_is_asked_for_30_per_tag():
    apis = lisbon_apis([product("P1")])
    with apis.client() as c:
        build_sample.build("Lisbon", *fa.DATES, client=c)
    assert {FakeAPIs.body(r)["pagination"]["count"] for r in apis.sent("/products/search")} == {30}


def test_main_keeps_the_geoapify_places_of_the_current_sample(tmp_path, capsys):
    old = [place("osm-n1", "culture"), place("osm-n2", "food"), place("osm-n3", "nature")]
    (tmp_path / "lisbon.json").write_text(json.dumps({"experiences": old}))
    apis = lisbon_apis([product("P1")])
    with apis.client() as c:
        code = build_sample.main(["Lisbon"], client=c, load_env=False, out_dir=tmp_path)
    assert code == 0                                   # the places' own websites are not refused as non-Viator links
    data = json.loads((tmp_path / "lisbon.json").read_text())
    assert validate_sample(data) == []
    assert [e["id"] for e in data["experiences"]] == ["osm-n1", "viator-p1", "osm-n3", "osm-n2"]   # round-robin
    assert data["experiences"][0] == old[0]            # copied unchanged, checked-at time included
    out = capsys.readouterr().out
    assert "1 Viator experience and 3 Geoapify places" in out
    assert f"Tour P1 | food | 35.0 EUR per person | label none | 4.8/5, 120 reviews | {fa.product_url('P1')}" in out


def test_main_stops_on_401_and_writes_nothing(tmp_path, capsys):
    apis = FakeAPIs().add("GET", fa.VIATOR_PROD + "/partner/destinations", (401, {"code": "UNAUTHORIZED"}))
    out_dir = tmp_path / "samples"
    with apis.client() as c:
        code = build_sample.main(["Lisbon"], client=c, load_env=False, out_dir=out_dir)
    assert code == 2
    assert not out_dir.exists()
    out = capsys.readouterr().out
    assert "viator" in out and "401" in out
    assert fa.VIATOR_KEY not in out
