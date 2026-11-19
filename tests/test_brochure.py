# The brochure (docs/ux-flow.md section 5, docs/backend-logic.md section 4): the sublist built by code from the kept
# experiences and saved in the trip file, the Geoapify static map (pin plot when it can't be had), and the PDF drawn
# from the saved sublist on download. No AI, no network: Geoapify is a fake server. Prices are fixed test examples.
import io
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import agents, brochure, budget, checks, main, store
from backend.schema import SUGGESTION_FIELDS
from backend.sources import common, geoapify
from tests import fake_apis as fa
from tests.factories import checked, experience, profile
from tests.fake_apis import FakeAPIs

client = TestClient(main.app)
STATIC = "maps.geoapify.com/v1/staticmap"


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return buf.getvalue()


PNG = _png()


def image_route(request):
    return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})


def log_lines():
    if not common.LOG_PATH.exists():
        return []
    return [json.loads(line) for line in common.LOG_PATH.read_text().splitlines()]


# --- a ready trip built from factories ---------------------------------------------------------------------------

EARLY = {"provider": "viator", "url": "https://www.viator.com/tours/Lisbon/castle",
         "retrieved_at": "2026-11-16T09:05:00+01:00", "quote": None}


def verdict(e, said="confirmed", note="The page supports name, price and hours."):
    return {"id": e["id"], "verdict": said, "url_read": e["booking_url"], "passage": "A copied passage.",
            "contested_fields": [], "note": note}


def ready_trip(exps, verdicts=None):
    """Checked like the pipeline does (source check skipped), verdicts set, costs and totals from budget.py."""
    prof = profile()
    for e in exps:
        e["verdict"] = (verdicts or {}).get(e["id"]) or verdict(e)
    checks.check_all(prof, exps)
    for e in exps:
        e["cost_eur"] = budget.item_cost(e["price"], prof)
    return {"id": "lisbon-20261119-100000-abcd", "created": "2026-11-19T10:00:00+01:00", "mode": "agents",
            "status": "ready", "profile": prof, "steps": [], "experiences": exps,
            "totals": budget.totals(prof, exps), "brochure": None, "error": None}


def sample_exps():
    castle = checked("castle", name="Castle", schedule={"day": 2, "start": "09:00", "end": "11:00"},
                     best_time={"start": "09:00", "reason": "Fewer people early"},
                     price={"amount": 20.0, "label": None, "source": EARLY},
                     location={"lat": 38.7139, "lng": -9.1335, "address": "Castelo, Lisbon"})
    tram = checked("tram-28", name="Tram 28", schedule={"day": 1, "start": "14:00", "end": "16:00"},
                   price={"amount": None, "label": None, "amount_eur": None})
    walk = checked("alfama-food-walk")                                  # day 1 10:00-12:00, €35 "regular adult"
    gone = checked("removed-one", kept=False, schedule={"day": 1, "start": "17:00", "end": "18:00"})
    young = checked("too-young", min_age=99, schedule={"day": 2, "start": "15:00", "end": "17:00"})
    return [castle, tram, walk, gone, young]


@pytest.fixture
def trip():
    return ready_trip(sample_exps())


# --- the sublist --------------------------------------------------------------------------------------------------

def test_sublist_keeps_kept_items_by_day_then_time(trip):
    stops = brochure.sublist(trip)
    assert [s["id"] for s in stops] == ["alfama-food-walk", "tram-28", "castle"]   # removed and rejected left out
    assert [s["stop"] for s in stops] == [1, 2, 3]
    assert [(s["day"], s["date"], s["start"], s["end"]) for s in stops] == [
        (1, "2026-12-04", "10:00", "12:00"), (1, "2026-12-04", "14:00", "16:00"), (2, "2026-12-05", "09:00", "11:00")]


def test_each_stop_carries_its_facts_time_reason_status_and_booking_link(trip):
    walk, tram, castle = brochure.sublist(trip)
    assert set(walk) == {"id", "stop", "day", "date", "start", "end", "name", "time_why", "price", "cost_eur",
                         "status", "note", "booking_url", "location"}
    assert walk["name"] == "Alfama food walk"
    assert walk["time_why"] == {"text": "A test suggestion", "kind": "suggestion"}     # the suggested time
    assert tram["time_why"] == {"text": "You picked this time", "kind": "user"}        # moved away from it
    assert walk["price"]["label"] == "regular adult" and walk["price"]["amount"] == 35.0
    assert walk["price"]["source"] == fa_source()
    assert walk["cost_eur"] == "35.00" and tram["cost_eur"] is None
    assert walk["status"] == "verified" and walk["note"] is None
    assert tram["status"] == "to_check" and "no source states a price" in tram["note"]
    assert walk["booking_url"] == "https://www.viator.com/tours/Lisbon/x"
    assert castle["location"] == {"lat": 38.7139, "lng": -9.1335, "address": "Castelo, Lisbon"}


def fa_source():
    return experience()["price"]["source"]


def test_the_note_names_the_warnings_and_a_doubtful_verdict():
    exps = sample_exps()
    walk = exps[2]
    t = ready_trip(exps, {walk["id"]: verdict(walk, "not_sure", "Demo mode: not verified.")})
    stop = next(s for s in brochure.sublist(t) if s["id"] == walk["id"])
    assert stop["status"] == "to_check" and stop["note"] == "Demo mode: not verified."


def test_build_has_totals_from_budget_not_counted_names_and_the_prices_note(trip):
    b = brochure.build(trip)
    assert b["totals"] == budget.totals(trip["profile"], trip["experiences"])
    assert b["totals"]["used"] == "55.00" and b["totals"]["budget"] == "250.00"
    assert b["not_counted"] == [{"id": "tram-28", "name": "Tram 28"}]
    assert b["prices_checked_at"] == "2026-11-16T09:05:00+01:00"                      # the oldest price check
    assert b["prices_note"] == ("Prices checked on 16 Nov 2026, 08:05 (Lisbon time). "
                                "They may change before you book.")
    assert b["pdf"] is None and b["created_at"]


def test_prices_note_without_any_sourced_price():
    t = ready_trip([checked("tram-28", price={"amount": None, "amount_eur": None})])
    b = brochure.build(t)
    assert b["prices_checked_at"] is None
    assert b["prices_note"] == "No prices from a source yet: experiences without a price are not counted."


def test_local_time_keeps_the_recorded_offset_when_the_zone_is_unknown():
    assert brochure.local_time("2026-11-17T14:42:00+01:00", "Europe/Lisbon") == "17 Nov 2026, 13:42 (Lisbon time)"
    assert brochure.local_time("2026-11-17T14:42:00+01:00", "Nowhere/Atlantis") == "17 Nov 2026, 14:42 (UTC+01:00)"
    assert brochure.local_time("2026-11-17T14:42:00+01:00", None) == "17 Nov 2026, 14:42 (UTC+01:00)"


# --- the Geoapify static map ---------------------------------------------------------------------------------------

POINTS = [{"lat": 38.7115, "lng": -9.1295, "text": "1", "color": "#0a66e8"},
          {"lat": 38.7139, "lng": -9.1335, "text": "2", "color": "#c75a00"}]


def test_static_map_request_has_the_markers_in_order_and_hides_the_key():
    apis = FakeAPIs().add("GET", STATIC, image_route)
    with apis.client() as c:
        out = geoapify.static_map(POINTS, client=c)
    assert out["png"] == PNG
    [req] = apis.requests
    q = req.url.params
    assert q["apiKey"] == fa.GEO_KEY and q["format"] == "png" and "center" not in q and "zoom" not in q
    first, second = q["marker"].split("|")
    assert first.startswith("lonlat:-9.1295,38.7115;") and "color:#0a66e8" in first and "text:1" in first
    assert second.startswith("lonlat:-9.1335,38.7139;") and "color:#c75a00" in second and "text:2" in second
    src = out["source"]
    assert src["provider"] == "geoapify" and src["quote"] is None
    assert src["url"].startswith("https://maps.geoapify.com/v1/staticmap?") and fa.GEO_KEY not in src["url"]
    [line] = log_lines()
    assert line["provider"] == "geoapify" and line["status"] == 200 and fa.GEO_KEY not in json.dumps(line)


def test_static_map_refuses_a_url_that_is_too_long_without_calling():
    apis = FakeAPIs().add("GET", STATIC, image_route)
    many = [{**POINTS[0], "text": str(n)} for n in range(1, 60)]
    with apis.client() as c, pytest.raises(common.SourceError, match="too many stops"):
        geoapify.static_map(many, client=c)
    assert apis.requests == []


def test_static_map_needs_an_image_back():
    apis = FakeAPIs().add("GET", STATIC, {"message": "not a picture"})
    with apis.client() as c, pytest.raises(common.SourceError, match="did not return an image"):
        geoapify.static_map(POINTS, client=c)


def test_map_image_uses_day_colours_and_stop_numbers(trip, monkeypatch):
    apis = FakeAPIs().add("GET", STATIC, image_route)
    monkeypatch.setattr(brochure, "HTTP", apis.client())
    block, png = brochure.map_image(brochure.sublist(trip))
    assert png == PNG and block["kind"] == "static"
    assert block["attribution"] == "Powered by Geoapify · © OpenStreetMap contributors"
    assert block["source"]["provider"] == "geoapify"
    markers = apis.requests[0].url.params["marker"].split("|")
    assert ["text:1" in markers[0], "text:3" in markers[2]] == [True, True]
    assert "color:#0a66e8" in markers[0] and "color:#c75a00" in markers[2]            # day 1 blue, day 2 orange


@pytest.mark.parametrize("route, reason", [((500, {"message": "boom"}), "returned 500"),
                                           ({"message": "json"}, "did not return an image")])
def test_map_image_falls_back_to_the_pin_plot(trip, monkeypatch, route, reason):
    monkeypatch.setattr(brochure, "HTTP", FakeAPIs().add("GET", STATIC, route).client())
    block, png = brochure.map_image(brochure.sublist(trip))
    assert png is None and block["kind"] == "plot" and reason in block["reason"]


def test_map_image_without_a_key_falls_back(trip, monkeypatch):
    monkeypatch.delenv("GEOAPIFY_API_KEY")
    apis = FakeAPIs().add("GET", STATIC, image_route)
    monkeypatch.setattr(brochure, "HTTP", apis.client())
    block, png = brochure.map_image(brochure.sublist(trip))
    assert png is None and block == {"kind": "plot", "reason": block["reason"]}
    assert "GEOAPIFY_API_KEY is not set" in block["reason"] and apis.requests == []


# --- the PDF -----------------------------------------------------------------------------------------------------------

def built(t, map_block=None):
    t["brochure"] = brochure.build(t)
    t["brochure"]["map"] = map_block or {"kind": "plot", "reason": "no key in this test"}
    t["status"] = "done"
    return t


def drawn(t, png=None):
    return "\n".join(brochure.render(t, png).drawn)


def test_pdf_text_has_the_whole_plan(trip):
    text = drawn(built(trip))
    for piece in ("Your trip brochure", "Lisbon", "Day 1 · Fri 4 Dec", "Day 2 · Sat 5 Dec",
                  "10:00 – 12:00", "Alfama food walk", "A test suggestion", "You picked this time",
                  "€35", "regular adult", "per person", "Viator · checked 17 Nov, 13:42",
                  "Verified", "To check: no source states a price", "No price yet", "Book",
                  "€55", "of €250 per person", "Not counted: Tram 28",
                  "Prices checked on 16 Nov 2026, 08:05 (Lisbon time). They may change before you book.",
                  "no key in this test"):
        assert piece in text, piece
    assert "Removed One" not in text and "too-young" not in text


def test_pdf_bytes_embed_inter_and_link_the_booking_pages(trip):
    data = brochure.pdf(built(trip), None)
    assert data.startswith(b"%PDF-")
    assert b"+Inter" in data and b"+InterBold" in data                                  # the bundled font
    assert b"/URI (https://www.viator.com/tours/Lisbon/x)" in data


def test_pdf_embeds_the_static_map_and_its_attribution(trip):
    block = {"kind": "static", "source": EARLY, "attribution": "Powered by Geoapify · © OpenStreetMap contributors"}
    t = built(trip, block)
    assert b"/Subtype /Image" in brochure.pdf(t, PNG)
    assert "Powered by Geoapify · © OpenStreetMap contributors" in drawn(t, PNG)


def test_pdf_prints_polish_and_greek_names_exactly(caplog):
    t = ready_trip([checked("lazienki", name="Łazienki Królewskie"),
                    checked("acropolis", name="Ακρόπολη", schedule={"day": 1, "start": "14:00", "end": "16:00"})])
    with caplog.at_level(logging.WARNING):
        text = drawn(built(t))
    assert "Łazienki Królewskie" in text and "Ακρόπολη" in text
    assert not [r for r in caplog.records if "missing" in r.getMessage().lower()]


# --- the API in demo mode ----------------------------------------------------------------------------------------------

BODY = {"destination": "Bookville", "start_date": "2026-12-04", "end_date": "2026-12-05", "group_type": "couple",
        "group_size": 2, "age_range": "25-34", "interests": ["culture"],
        "budget": {"amount": 150, "currency": "EUR", "per": "person"}, "pace": "chill", "notes": ""}


def sample_item(id, amount, lat):
    e = experience(id, category="culture", name=id.title(), location={"city": "Bookville", "lat": lat})
    for field in SUGGESTION_FIELDS:
        e.pop(field)
    e["price"].update(amount=amount, amount_eur=amount)
    return e


@pytest.fixture(autouse=True)
def _demo(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)
    samples = tmp_path / "samples"
    samples.mkdir()
    items = [sample_item("tower", 30.0, 38.70), sample_item("museum", 20.0, 38.71),
             sample_item("garden", None, 38.72), sample_item("palace", 10.0, 38.73)]
    (samples / "bookville.json").write_text(json.dumps({"experiences": items}))
    (samples / "lisbon.json").write_text((agents.SAMPLES_DIR / "lisbon.json").read_text())
    monkeypatch.setattr(agents, "SAMPLES_DIR", samples)


def new_trip(**over):
    r = client.post("/api/trips", json={**BODY, **over})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_post_brochure_saves_the_sublist_in_the_trip_file():
    trip_id = new_trip()
    r = client.post(f"/api/trips/{trip_id}/brochure")
    assert r.status_code == 200, r.text
    saved = store.load(trip_id)["brochure"]
    assert saved == r.json()["brochure"]
    # demo: day 1 tower 10:00, garden 15:00; day 2 museum 10:00, palace 15:00
    assert [s["id"] for s in saved["stops"]] == ["tower", "garden", "museum", "palace"]
    assert saved["stops"][0]["price"]["label"] == "regular adult" and saved["stops"][0]["status"] == "to_check"
    assert saved["totals"]["used"] == "60.00" and saved["not_counted"] == [{"id": "garden", "name": "Garden"}]
    assert saved["map"]["kind"] == "plot"                     # the fake Geoapify has no static map route
    assert "map:" in store.load(trip_id)["steps"][-1]["text"]


def test_pdf_downloads_as_an_attachment():
    trip_id = new_trip()
    assert client.get(f"/api/trips/{trip_id}/brochure.pdf").status_code == 409          # not built yet
    client.post(f"/api/trips/{trip_id}/brochure")
    r = client.get(f"/api/trips/{trip_id}/brochure.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == f'attachment; filename="{trip_id}.pdf"'
    assert r.content.startswith(b"%PDF-")


def test_static_map_is_saved_and_served_without_the_key(monkeypatch):
    apis = FakeAPIs().add("GET", STATIC, image_route)
    monkeypatch.setattr(brochure, "HTTP", apis.client())
    trip_id = new_trip()
    assert client.get(f"/api/trips/{trip_id}/brochure/map.png").status_code == 409      # not built yet
    trip = client.post(f"/api/trips/{trip_id}/brochure").json()
    assert trip["brochure"]["map"]["kind"] == "static"
    r = client.get(f"/api/trips/{trip_id}/brochure/map.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == PNG
    assert fa.GEO_KEY not in store.path(trip_id).read_text()
    assert fa.GEO_KEY not in common.LOG_PATH.read_text()
    assert b"/Subtype /Image" in client.get(f"/api/trips/{trip_id}/brochure.pdf").content


def test_map_png_is_404_when_the_brochure_uses_the_pin_plot():
    trip_id = new_trip()
    client.post(f"/api/trips/{trip_id}/brochure")
    r = client.get(f"/api/trips/{trip_id}/brochure/map.png")
    assert r.status_code == 404 and "pins" in r.json()["detail"]


def test_demo_lisbon_brochure_and_pdf_show_viator_prices_and_no_price_yet():
    trip_id = new_trip(destination="Lisbon", end_date="2026-12-04")
    r = client.post(f"/api/trips/{trip_id}/brochure")
    assert r.status_code == 200, r.text
    trip = r.json()
    assert trip["brochure"]["prices_note"].startswith("Prices checked on")      # a Viator ticket
    assert client.get(f"/api/trips/{trip_id}/brochure.pdf").status_code == 200
    text = drawn(trip)
    assert "Viator · checked" in text and "No price yet" in text                 # and a Geoapify place
    assert "Demo data, not verified" in text
