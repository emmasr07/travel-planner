# Swap, quick search and picking an option (docs/backend-logic.md section 4). Both searches run in the background and
# leave 1-3 checked and verified options in trip["search"]; the user's pick is what changes the list.
# Demo mode: same-category places (swap) or a keyword match (quick) from a tmp sample with fixed example prices.
# Agents mode: the researcher with the quick-search instructions, then the verifier (fake Anthropic client).
import json

import pytest
from fastapi.testclient import TestClient

from backend import agents, main, store
from backend.schema import SUGGESTION_FIELDS
from tests.agent_helpers import delivery, fake_http, install, set_up, verdicts
from tests.factories import experience
from tests.fake_anthropic import tool_use

client = TestClient(main.app)

BODY = {"destination": "Swapville", "start_date": "2026-12-04", "end_date": "2026-12-04", "group_type": "couple",
        "group_size": 2, "age_range": "25-34", "interests": ["culture"],
        "budget": {"amount": 150, "currency": "EUR", "per": "person"}, "pace": "chill", "notes": ""}


def sample_item(id, category, amount=10.0, **over):
    e = experience(id, category=category, name=id.replace("-", " ").title(), location={"city": "Swapville"}, **over)
    for field in SUGGESTION_FIELDS:
        e.pop(field)
    e["price"].update(amount=amount)
    return e


@pytest.fixture(autouse=True)
def _demo(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)
    samples = tmp_path / "samples"
    samples.mkdir()
    items = [sample_item("museum-a", "culture"), sample_item("museum-b", "culture"),
             sample_item("museum-c", "culture"), sample_item("too-young", "culture", min_age=99),
             sample_item("museum-d", "culture"), sample_item("museum-e", "culture"),
             sample_item("wine-bar", "food", tags=["wine tasting"]), sample_item("park", "nature")]
    (samples / "swapville.json").write_text(json.dumps({"experiences": items}))
    monkeypatch.setattr(agents, "SAMPLES_DIR", samples)


def new_trip(**over):
    r = client.post("/api/trips", json={**BODY, **over})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get(trip_id):
    return client.get(f"/api/trips/{trip_id}").json()


def ids(exps):
    return [e["id"] for e in exps]


# --- swap -------------------------------------------------------------------------------------------------------

def test_demo_swap_offers_same_category_places_not_already_in_the_trip():
    trip_id = new_trip()
    assert ids(get(trip_id)["experiences"]) == ["museum-a", "museum-b"]   # chill, 1 day: 2
    r = client.post(f"/api/trips/{trip_id}/swap/museum-a")
    assert r.status_code == 202 and r.json()["search"]["status"] == "searching"

    search = get(trip_id)["search"]
    assert search["status"] == "ready" and search["kind"] == "swap" and search["for"] == "museum-a"
    assert ids(search["options"]) == ["museum-c", "too-young", "museum-d"]
    for o in search["options"]:
        assert o["schedule"] == {"day": 1, "start": "10:00", "end": "12:00"}     # where museum-a was
        assert o["verdict"]["verdict"] == "not_sure" and o["checks"] and o["cost_eur"] == "10.00"
    assert next(o for o in search["options"] if o["id"] == "too-young")["status"] == "rejected"
    museum_c = search["options"][0]
    assert next(c for c in museum_c["checks"] if c["name"] == "overlap")["result"] == "ok"  # museum-a left out
    assert get(trip_id)["status"] == "ready"


def test_picking_a_swap_option_replaces_the_card():
    trip_id = new_trip()
    client.post(f"/api/trips/{trip_id}/swap/museum-a")
    r = client.post(f"/api/trips/{trip_id}/options/museum-c")
    assert r.status_code == 200, r.text
    trip = r.json()
    status = {e["id"]: e["user"]["status"] for e in trip["experiences"]}
    assert status == {"museum-a": "removed", "museum-b": "kept", "museum-c": "kept"}
    assert trip["totals"]["kept"] == 2 and trip["search"]["picked"] == "museum-c"
    assert trip["steps"][-1] == {"at": trip["steps"][-1]["at"], "who": "user",
                                 "text": "picked Museum C instead of Museum A"}
    again = client.post(f"/api/trips/{trip_id}/options/museum-d")
    assert again.status_code == 409 and "already picked" in again.json()["detail"]


def test_a_rejected_option_cannot_be_picked():
    trip_id = new_trip()
    client.post(f"/api/trips/{trip_id}/swap/museum-a")
    r = client.post(f"/api/trips/{trip_id}/options/too-young")
    assert r.status_code == 409 and "rejected by the checks" in r.json()["detail"]


def test_swap_and_pick_refuse_the_wrong_state():
    store.save({"id": "busy-1", "status": "verifying", "profile": {}, "experiences": [], "steps": []})
    r = client.post("/api/trips/busy-1/swap/x")
    assert r.status_code == 409 and r.json()["detail"] == "the list is not ready yet: verifying"
    trip_id = new_trip()
    assert client.post(f"/api/trips/{trip_id}/swap/nope").status_code == 404
    r = client.post(f"/api/trips/{trip_id}/options/museum-c")
    assert r.status_code == 409 and "no options" in r.json()["detail"]
    trip = get(trip_id)
    trip["search"] = {"kind": "quick", "for": None, "request": "x", "day": 1, "status": "searching", "options": [],
                      "error": None, "picked": None}
    store.save(trip)
    r = client.post(f"/api/trips/{trip_id}/swap/museum-a")
    assert r.status_code == 409 and "already running" in r.json()["detail"]


# --- quick search -----------------------------------------------------------------------------------------------

def test_demo_quick_search_matches_the_words_of_the_request():
    trip_id = new_trip()
    r = client.post(f"/api/trips/{trip_id}/quick", json={"request": "We suddenly want a wine tasting", "day": 1})
    assert r.status_code == 202
    search = get(trip_id)["search"]
    assert search["status"] == "ready" and ids(search["options"]) == ["wine-bar"]
    [wine] = search["options"]
    assert wine["schedule"] == {"day": 1, "start": "08:00", "end": "10:00"}       # the first free slot that fits
    assert wine["verdict"]["note"].startswith("Demo mode")
    client.post(f"/api/trips/{trip_id}/options/wine-bar")
    status = {e["id"]: e["user"]["status"] for e in get(trip_id)["experiences"]}
    assert status == {"museum-a": "kept", "museum-b": "kept", "wine-bar": "kept"}


def test_demo_quick_search_finds_nothing_and_says_so():
    trip_id = new_trip()
    client.post(f"/api/trips/{trip_id}/quick", json={"request": "Skydiving over the river", "day": 1})
    trip = get(trip_id)
    assert trip["search"]["status"] == "ready" and trip["search"]["options"] == []
    assert "nothing invented" in trip["steps"][-1]["text"]


def test_quick_search_checks_the_day_and_works_after_the_brochure():
    trip_id = new_trip()
    r = client.post(f"/api/trips/{trip_id}/quick", json={"request": "wine", "day": 2})
    assert r.status_code == 400 and r.json()["field"] == "day"
    assert client.post(f"/api/trips/{trip_id}/brochure").status_code == 200
    assert client.post(f"/api/trips/{trip_id}/swap/museum-a").status_code == 409     # swap: ready only
    assert client.post(f"/api/trips/{trip_id}/quick", json={"request": "wine", "day": 1}).status_code == 202
    trip = client.post(f"/api/trips/{trip_id}/options/wine-bar").json()
    assert trip["status"] == "ready" and trip["brochure"] is None


# --- agents mode ------------------------------------------------------------------------------------------------

def test_agents_swap_runs_the_quick_researcher_then_the_verifier(monkeypatch):
    set_up(monkeypatch)
    fake_http(monkeypatch)
    exps = delivery()["experiences"]
    other = experience("other-walk", name="Other walk", schedule={"day": 1, "start": "09:00", "end": "11:00"})
    fake = install(monkeypatch,
                   [[tool_use("deliver_experiences", {"experiences": exps})], []],
                   [[tool_use("deliver_verdicts", verdicts(ids(exps)))], []],
                   [[tool_use("deliver_experiences", {"experiences": [other]})], []],
                   [[tool_use("deliver_verdicts", verdicts(["other-walk"]))], []])
    trip_id = new_trip(destination="Lisbon", end_date="2026-12-06", interests=["food", "culture"], pace="balanced")
    assert get(trip_id)["status"] == "ready", get(trip_id)["error"]

    assert client.post(f"/api/trips/{trip_id}/swap/item-0").status_code == 202
    trip = get(trip_id)
    assert trip["search"]["status"] == "ready", trip["search"]["error"]
    [option] = trip["search"]["options"]
    assert option["id"] == "other-walk" and option["verdict"]["verdict"] == "confirmed"
    quick = fake.created[2]["agent"]
    assert "# Quick search" in quick["system"]
    sent = [e for e in fake.sent if e["type"] == "user.message"][2]
    asked = json.loads(sent["content"][0]["text"])
    assert "Item 0" in asked["request"] and asked["day"] == 1
    assert {"start": "08:00", "end": "12:30"} in asked["free_slots"]             # item-0's time is free
    assert asked["budget_left"]["currency"] == "EUR"
    assert [s["purpose"] for s in trip["sessions"]] == ["research", "verify", "quick", "verify"]

    trip = client.post(f"/api/trips/{trip_id}/options/other-walk").json()
    status = {e["id"]: e["user"]["status"] for e in trip["experiences"]}
    assert status["item-0"] == "removed" and status["other-walk"] == "kept"
