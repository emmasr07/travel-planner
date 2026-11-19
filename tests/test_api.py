# The API in demo mode (docs/backend-logic.md sections 3, 4, 6, 7): questionnaire -> sample + fixed suggestions ->
# code checks -> demo verdicts -> ready; keep/remove/time changes; fit-budget; brochure. No AI, no network.
# The real samples have no prices, so the budget paths use "Testville", a tmp sample with fixed example prices.
import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend import agents, main, store, trips
from backend.schema import SUGGESTION_FIELDS
from tests.factories import experience

client = TestClient(main.app)

BODY = {"destination": "Lisbon", "start_date": "2026-12-04", "end_date": "2026-12-06", "group_type": "friends",
        "group_size": 4, "age_range": "25-34", "interests": ["culture", "nature"],
        "budget": {"amount": 250, "currency": "EUR", "per": "person"}, "pace": "balanced", "notes": ""}


@pytest.fixture(autouse=True)
def _demo(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)


def body(**over):
    b = copy.deepcopy(BODY)
    b.update(over)
    return b


def new_trip(**over):
    r = client.post("/api/trips", json=body(**over))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get(trip_id):
    r = client.get(f"/api/trips/{trip_id}")
    assert r.status_code == 200, r.text
    return r.json()


def change(trip_id, exp_id, **payload):
    return client.post(f"/api/trips/{trip_id}/experiences/{exp_id}", json=payload)


def by_id(trip):
    return {e["id"]: e for e in trip["experiences"]}


def check(e, name):
    return next(c for c in e["checks"] if c["name"] == name)


# --- Testville: a tmp sample with fixed example prices -------------------------------------------------------------

FX = {"rate": 1.2, "from": "GBP", "to": "EUR", "date": "2026-11-17",
      "source": {"provider": "frankfurter", "url": "https://api.frankfurter.dev/v2/rates?base=GBP&quotes=EUR",
                 "retrieved_at": "2026-11-17T14:42:00+01:00", "quote": None}}


def sample_item(id, category, amount, currency="EUR", **over):
    e = experience(id, category=category, name=id.replace("-", " ").title(),
                   location={"city": "Testville"}, **over)
    for field in SUGGESTION_FIELDS:
        e.pop(field)
    e["price"].update(amount=amount, currency=currency, amount_eur=amount if currency == "EUR" else None)
    if currency == "GBP":
        e["price"].update(amount_eur=24.0, fx=FX)
    return e


@pytest.fixture
def testville_sample(tmp_path, monkeypatch):
    """Food, culture and one nature place; no nightlife, relax, adventure or shopping."""
    samples = tmp_path / "samples"
    samples.mkdir()
    items = [sample_item("first", "food", 100.0), sample_item("second", "culture", 80.0),
             sample_item("no-price", "food", None), sample_item("third", "culture", 30.0),
             sample_item("gbp", "food", 20.0, currency="GBP"), sample_item("too-young", "culture", 10.0, min_age=99),
             sample_item("park", "nature", 5.0)]
    (samples / "testville.json").write_text(json.dumps({"experiences": items}))
    monkeypatch.setattr(agents, "SAMPLES_DIR", samples)


@pytest.fixture
def testville(testville_sample):
    return new_trip(destination="Testville", interests=["food", "culture"], group_type="couple", group_size=2,
                    budget={"amount": 150, "currency": "EUR", "per": "person"})


def lisbon_matching(*interests):
    """Ids of the real Lisbon sample's places in these interests, in sample order (best fit first)."""
    sample = json.loads((agents.SAMPLES_DIR / "lisbon.json").read_text())["experiences"]
    return [s["id"] for s in sample if s["category"] in interests]


# --- config and the demo flow ---------------------------------------------------------------------------------

def test_config():
    assert client.get("/api/config").json() == {"mode": "demo", "demo_destinations": ["Lisbon", "London", "Matera"]}


def test_lisbon_demo_flow():
    trip = get(new_trip())
    assert trip["status"] == "ready", trip["error"]
    assert trip["mode"] == "demo"
    assert trip["profile"]["destination"] == "Lisbon" and trip["profile"]["timezone"] == "Europe/Lisbon"
    exps = trip["experiences"]
    matching = lisbon_matching("culture", "nature")
    assert matching, "the Lisbon sample has no culture or nature places"
    assert [e["id"] for e in exps] == matching[:9]               # best fit first, at most 3 days x 3, never padded
    assert {e["category"] for e in exps} <= {"culture", "nature"}
    assert sorted(e["schedule"]["day"] for e in exps) == sorted(i % 3 + 1 for i in range(len(exps)))
    closed = "osm-n5090471903"                                   # Museu de Lisboa - Torreão Poente: "Encerrado ..."
    for e in exps:
        assert e["status"] == ("rejected" if e["id"] == closed else "to_check")   # demo data is never verified
        assert e["verdict"]["verdict"] == "not_sure" and "Demo mode" in e["verdict"]["note"]
        assert e["user"] == {"status": "kept", "position": None}
        assert check(e, "schema")["result"] == "ok" and check(e, "source")["result"] == "skip"
        assert e["best_time"]["kind"] == "suggestion" and "Demo suggestion" in e["best_time"]["reason"]
        assert e["why_fits"]["text"] == f"You picked {e['category']}"
        assert e["cost_eur"] is None                             # the samples have no prices yet
    assert trip["totals"]["used"] == "0.00" and trip["totals"]["over"] is False
    assert trip["totals"]["not_counted"] == [e["id"] for e in exps if e["id"] != closed]
    assert {s["who"] for s in trip["steps"]} >= {"researcher", "code", "verifier"}
    assert all(set(s) == {"at", "who", "text"} for s in trip["steps"])


def test_a_place_the_source_says_is_closed_is_rejected():
    trip = get(new_trip())
    museum = by_id(trip)["osm-n5090471903"]
    assert museum["description"] == "Encerrado temporrariamente"
    assert museum["status"] == "rejected" and check(museum, "closure")["result"] == "fail"
    r = change(trip["id"], museum["id"], status="kept")
    assert r.status_code == 409 and "closed" in r.json()["detail"]


def test_the_profile_holds_only_the_answers():
    profile = get(new_trip(notes="one of us uses a wheelchair"))["profile"]
    assert set(profile) == {"destination", "start_date", "end_date", "timezone", "group_type", "group_size",
                            "age_range", "youngest_age", "interests", "budget", "pace", "notes"}
    assert client.post("/api/trips", json=body(email="a@b.c")).status_code == 400


def test_a_chill_one_day_trip_gets_two():
    trip = get(new_trip(end_date="2026-12-04", pace="chill"))
    assert [e["schedule"]["start"] for e in trip["experiences"]] == ["10:00", "15:00"]


def test_empty_result(testville_sample):
    trip = get(new_trip(destination="Testville", interests=["nightlife", "relax"]))
    assert trip["status"] == "ready" and trip["experiences"] == []
    assert any("nothing" in s["text"].lower() for s in trip["steps"])


def test_london_and_matera_work_too():
    for city in ("London", "matera"):
        trip = get(new_trip(destination=city, interests=["culture", "nature", "shopping"]))
        assert trip["status"] == "ready" and trip["experiences"], city


# --- invalid input, unknown trips, wrong state -------------------------------------------------------------------

def test_destination_without_a_sample_is_400():
    r = client.post("/api/trips", json=body(destination="Paris"))
    assert r.status_code == 400
    assert r.json()["field"] == "destination" and "Lisbon, London, Matera" in r.json()["detail"]


@pytest.mark.parametrize("over, field", [
    ({"end_date": "2026-12-01"}, "end_date"),
    ({"interests": []}, "interests"),
    ({"interests": ["skydiving"]}, "interests.0"),
    ({"group_size": 0}, "group_size"),
    ({"age_range": "18–24"}, "age_range"),                       # the form's en dash is mapped by the page
    ({"budget": {"amount": 0, "currency": "EUR", "per": "person"}}, "budget.amount"),
    ({"budget": {"amount": 100, "currency": "USD", "per": "person"}}, "budget.currency"),
    ({"pace": "fast"}, "pace"),
])
def test_invalid_input_is_400_with_the_field(over, field):
    r = client.post("/api/trips", json=body(**over))
    assert r.status_code == 400, r.text
    assert r.json()["field"] == field


def test_unknown_trip_is_404():
    assert client.get("/api/trips/no-such-trip").status_code == 404
    assert client.get("/api/trips/UPPER").status_code == 404
    trip_id = new_trip()
    assert change(trip_id, "no-such-item", status="removed").status_code == 404


def test_wrong_state_is_409():
    store.save({"id": "busy-1", "status": "verifying", "profile": {}, "experiences": [], "steps": []})
    for r in (client.post("/api/trips/busy-1/experiences/x", json={"status": "removed"}),
              client.post("/api/trips/busy-1/fit-budget"), client.post("/api/trips/busy-1/brochure")):
        assert r.status_code == 409
        assert r.json()["detail"] == "the list is not ready yet: verifying"


def test_agents_mode_without_setup_is_503(monkeypatch):
    monkeypatch.setenv("MODE", "agents")
    assert client.get("/api/config").json()["mode"] == "agents"
    r = client.post("/api/trips", json=body())
    assert r.status_code == 503 and "agents mode is not set up" in r.json()["detail"]


def test_a_failing_step_sets_failed_and_keeps_what_was_done(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("verifier exploded")
    monkeypatch.setattr(agents, "verify", broken)
    trip = get(new_trip())
    assert trip["status"] == "failed" and "verifier exploded" in trip["error"]
    assert [e["id"] for e in trip["experiences"]] == lisbon_matching("culture", "nature")[:9]
    assert any(s["who"] == "researcher" for s in trip["steps"])


# --- user changes --------------------------------------------------------------------------------------------

def test_remove_and_restore_update_the_totals(testville):
    trip = get(testville)
    assert trip["totals"]["used"] == "234.00"                   # 100 + 80 + 30 + 24 (GBP 20 at 1.2)
    trip = change(testville, "first", status="removed").json()
    assert trip["totals"]["used"] == "134.00" and by_id(trip)["first"]["user"]["status"] == "removed"
    assert trip["steps"][-1]["who"] == "user"
    trip = change(testville, "first", status="kept").json()
    assert trip["totals"]["used"] == "234.00"


def test_only_items_matching_the_interests(testville):
    assert "park" not in by_id(get(testville))                                    # nature: not picked


def test_prices_are_converted_offline_from_the_sample_rate(testville):
    gbp = by_id(get(testville))["gbp"]
    assert gbp["price"]["amount_eur"] == 24.0 and gbp["price"]["fx"]["from"] == "GBP"
    assert gbp["cost_eur"] == "24.00"


def test_a_rejected_item_is_kept_in_the_file_but_cannot_be_kept(testville):
    trip = get(testville)
    assert by_id(trip)["too-young"]["status"] == "rejected"
    assert "too-young" not in trip["totals"]["counted"]
    r = change(testville, "too-young", status="kept")
    assert r.status_code == 409 and "rejected" in r.json()["detail"]


def test_a_time_change_reruns_the_time_checks(testville):
    # first: day 1 10:00-12:00, third: day 1 14:00-16:00 (2 h each, from duration_min)
    trip = change(testville, "third", day=1, start="11:00").json()
    first, third = by_id(trip)["first"], by_id(trip)["third"]
    assert third["schedule"] == {"day": 1, "start": "11:00", "end": "13:00"}
    assert check(first, "overlap")["result"] == "warn" and check(third, "overlap")["result"] == "warn"
    assert first["status"] == "to_check"
    trip = change(testville, "third", start="20:00").json()                       # after closing (18:00)
    assert check(by_id(trip)["third"], "hours")["result"] == "warn"
    assert check(by_id(trip)["first"], "overlap")["result"] == "ok"


@pytest.mark.parametrize("payload, field", [({"day": 4}, "day"), ({"start": "25:00"}, "start"),
                                            ({"status": "maybe"}, "status"), ({}, None)])
def test_bad_changes_are_400(testville, payload, field):
    r = change(testville, "first", **payload)
    assert r.status_code == 400, r.text
    assert r.json()["field"] == field


# --- budget, fit-budget and the brochure ---------------------------------------------------------------------

def test_over_budget_blocks_the_brochure_and_fit_budget_proposes(testville):
    trip = get(testville)
    assert trip["totals"]["over"] is True and trip["totals"]["over_by"] == "84.00"
    r = client.post(f"/api/trips/{testville}/brochure")
    assert r.status_code == 409 and "over budget by €84.00" in r.json()["detail"]
    proposal = client.post(f"/api/trips/{testville}/fit-budget").json()
    # Kept and counted, best fit first: first 100, second 80, no-price -, third 30, gbp 24 (too-young is rejected).
    # From the bottom: gbp -> 210, third -> 180, no-price skipped (saves nothing), second -> 100: within 150.
    assert [p["id"] for p in proposal["remove"]] == ["gbp", "third", "second"]
    assert proposal["used_after"] == "100.00" and proposal["within_budget"] is True
    assert proposal["remove"][0] == {"id": "gbp", "name": "Gbp", "cost_eur": "24.00"}
    assert get(testville)["totals"]["used"] == "234.00"                           # nothing applied


def test_brochure_then_edit_goes_back_to_ready(testville):
    for exp_id in ("second", "gbp"):                                               # 100 + 30 = 130 of 150
        change(testville, exp_id, status="removed")
    r = client.post(f"/api/trips/{testville}/brochure")
    assert r.status_code == 200, r.text
    trip = r.json()
    assert trip["status"] == "done"
    stops = trip["brochure"]["stops"]
    assert [s["id"] for s in stops] == ["first", "third", "no-price"]            # day 1 10:00, 14:00; day 3
    assert [s["stop"] for s in stops] == [1, 2, 3]
    assert trip["brochure"]["pdf"] is None and trip["brochure"]["created_at"]
    assert client.post(f"/api/trips/{testville}/brochure").status_code == 409     # already built
    trip = change(testville, "third", status="removed").json()
    assert trip["status"] == "ready" and trip["brochure"] is None


def test_brochure_needs_one_kept_item(testville):
    for e in get(testville)["experiences"]:
        change(testville, e["id"], status="removed")
    r = client.post(f"/api/trips/{testville}/brochure")
    assert r.status_code == 409 and "at least one" in r.json()["detail"]


def test_brochure_pdf_downloads_once_built(testville):
    assert client.get(f"/api/trips/{testville}/brochure.pdf").status_code == 409  # not built yet
    for exp_id in ("second", "gbp"):
        change(testville, exp_id, status="removed")
    client.post(f"/api/trips/{testville}/brochure")
    r = client.get(f"/api/trips/{testville}/brochure.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")


def test_trip_json_download():
    trip_id = new_trip()
    r = client.get(f"/api/trips/{trip_id}/json")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.json() == get(trip_id)


def test_pages_are_still_served():
    assert client.get("/").status_code == 200 and client.get("/health").json() == {"ok": True}


def test_trips_module_has_the_errors():
    assert issubclass(trips.BadInput, Exception) and issubclass(trips.WrongState, Exception)
