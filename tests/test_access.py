# Going online (roadmap step 5, item 4): in MODE=agents a new trip, a swap and a quick search start a paid run, so
# each needs the access code (X-Access-Code header; 403 without it, or when the server has none set) and counts toward
# DAILY_AGENT_LIMIT a day (429 over it). A demo trip on the same server needs neither. The code is never written down.
# The Anthropic client and every source are fakes; prices are fixed test examples.
import pytest
from fastapi.testclient import TestClient

from backend import access, agents, main, store
from backend.sources import common
from tests.agent_helpers import delivery, fake_http, from_the_web, install, set_up, verdicts
from tests.fake_anthropic import tool_use

client = TestClient(main.app)

CODE = "a-real-code-7788"
BODY = {"destination": "Lisbon", "start_date": "2026-12-04", "end_date": "2026-12-06", "group_type": "friends",
        "group_size": 4, "age_range": "25-34", "interests": ["food", "culture"],
        "budget": {"amount": 250, "currency": "EUR", "per": "person"}, "pace": "balanced", "notes": ""}
LOCKED = "the AI agents need the access code: ask us for it, or plan a demo trip instead"


@pytest.fixture(autouse=True)
def _real_check(tmp_path, monkeypatch):
    main.app.dependency_overrides.pop(main.access_code, None)    # this module sends (or leaves out) the real header
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)
    set_up(monkeypatch)                                           # MODE=agents with its settings
    fake_http(monkeypatch)
    monkeypatch.setenv("ACCESS_CODE", CODE)


def runs(n):
    """n trips' agent sessions: each researcher delivers 3 experiences (fresh copies), then the verifier."""
    scripts = []
    for _ in range(n):
        exps = [from_the_web(e) for e in delivery(n=3, price={"amount": 20.0})["experiences"]]
        scripts += [[[tool_use("deliver_experiences", {"experiences": exps})], []],
                    [[tool_use("deliver_verdicts", verdicts([e["id"] for e in exps]))], []]]
    return scripts


def nothing_found():
    """A swap or quick search session that finds nothing real (0 options is allowed: no verifier runs)."""
    return [[tool_use("deliver_experiences", {"experiences": []})], []]


def post_trip(code=None, query=""):
    return client.post(f"/api/trips{query}", json=BODY, headers={"X-Access-Code": code} if code is not None else {})


def used():
    return access.usage()["count"]


# --- the access code ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code", [None, "", "wrong-code", CODE + "x"])
def test_an_agents_trip_without_the_right_code_is_403_and_nothing_starts(monkeypatch, code):
    fake = install(monkeypatch)
    r = post_trip(code)
    assert r.status_code == 403 and r.json() == {"detail": LOCKED}
    assert fake.created == [] and store.trip_ids() == [] and used() == 0


def test_with_no_code_set_on_the_server_every_agents_run_is_403(monkeypatch):
    monkeypatch.delenv("ACCESS_CODE")
    fake = install(monkeypatch)
    r = post_trip("anything")
    assert r.status_code == 403
    assert r.json()["detail"] == ("the AI agents are locked on this server (no access code is set): "
                                  "plan a demo trip instead")
    assert fake.created == [] and used() == 0


def test_the_code_comes_before_the_setup_check(monkeypatch):
    agents.LOCK.unlink()                                          # not set up: 503, but only for someone with the code
    assert post_trip().status_code == 403
    assert post_trip(CODE).status_code == 503


def test_the_right_code_starts_the_trip_and_is_never_written_down(monkeypatch):
    install(monkeypatch, *runs(1))
    r = post_trip(f"  {CODE} ")                                   # spaces around a pasted code are fine
    assert r.status_code == 201, r.text
    trip_id = r.json()["id"]
    trip = client.get(f"/api/trips/{trip_id}")
    assert trip.json()["status"] == "ready", trip.json()["error"]
    assert used() == 1
    written = [store.path(trip_id).read_text(encoding="utf-8"), common.LOG_PATH.read_text(encoding="utf-8"),
               access.USAGE_PATH.read_text(encoding="utf-8"), trip.text, client.get(f"/api/trips/{trip_id}/json").text,
               client.get("/api/config").text, r.text]
    assert all(CODE not in text for text in written)


def test_swap_and_quick_search_on_an_agents_trip_need_the_code(monkeypatch):
    install(monkeypatch, *runs(1), nothing_found(), nothing_found())
    trip_id = post_trip(CODE).json()["id"]
    swap, quick = f"/api/trips/{trip_id}/swap/item-0", f"/api/trips/{trip_id}/quick"
    ask = {"request": "a wine tasting", "day": 1}
    assert client.post(swap).status_code == 403
    assert client.post(quick, json=ask, headers={"X-Access-Code": "nope"}).status_code == 403
    assert used() == 1                                            # refused: not counted, no search started
    assert "search" not in store.load(trip_id)

    assert client.post(swap, headers={"X-Access-Code": CODE}).status_code == 202
    assert store.load(trip_id)["search"]["status"] == "ready"
    assert client.post(quick, json=ask, headers={"X-Access-Code": CODE}).status_code == 202
    assert used() == 3


# --- a demo trip on an agents server -------------------------------------------------------------------------------

def test_a_demo_trip_on_an_agents_server_needs_no_code_and_never_counts(monkeypatch):
    fake = install(monkeypatch)
    r = post_trip(query="?mode=demo")
    assert r.status_code == 201, r.text
    trip = client.get(f"/api/trips/{r.json()['id']}").json()
    assert trip["mode"] == "demo" and trip["status"] == "ready", trip["error"]
    assert trip["experiences"] and "sessions" not in trip
    r = client.post(f"/api/trips/{trip['id']}/quick", json={"request": "a garden or a park", "day": 1})
    assert r.status_code == 202
    assert fake.created == [] and used() == 0


def test_a_demo_trip_is_only_for_the_sample_cities_and_mode_takes_only_demo():
    r = client.post("/api/trips?mode=demo", json={**BODY, "destination": "Porto"})
    assert r.status_code == 400 and r.json()["field"] == "destination"
    assert r.json()["detail"].startswith("demo mode has sample data for ")
    assert client.post("/api/trips?mode=agents", json=BODY).status_code == 400


# --- the daily limit -----------------------------------------------------------------------------------------------

def test_over_the_daily_limit_an_agents_run_is_429_and_refused_requests_do_not_count(monkeypatch):
    monkeypatch.setenv("DAILY_AGENT_LIMIT", "2")
    fake = install(monkeypatch, *runs(2))
    assert post_trip("wrong").status_code == 403
    assert post_trip(CODE).status_code == 201
    assert post_trip(CODE).status_code == 201
    r = post_trip(CODE)
    assert r.status_code == 429
    assert r.json()["detail"] == ("today's 2 AI agent runs are used up: try again tomorrow (the count restarts at "
                                  "midnight UTC), or plan a demo trip instead")
    assert used() == 2 and len(fake.created) == 4               # the third never started a session
    assert post_trip(query="?mode=demo").status_code == 201      # the demo still works


def test_the_limit_defaults_to_ten_and_starts_again_each_utc_day(monkeypatch):
    monkeypatch.setattr(access, "_today", lambda: "2026-11-23")
    for _ in range(10):
        access.count_run()
    with pytest.raises(access.LimitReached):
        access.count_run()
    assert access.usage() == {"date": "2026-11-23", "count": 10}
    monkeypatch.setattr(access, "_today", lambda: "2026-11-24")
    access.count_run()
    assert access.usage() == {"date": "2026-11-24", "count": 1}


def test_a_limit_of_zero_switches_the_agents_off_and_a_wrong_limit_is_503(monkeypatch):
    install(monkeypatch)
    monkeypatch.setenv("DAILY_AGENT_LIMIT", "0")
    r = post_trip(CODE)
    assert r.status_code == 429
    assert r.json()["detail"] == "the AI agents are switched off on this server today: plan a demo trip instead"
    monkeypatch.setenv("DAILY_AGENT_LIMIT", "ten")
    r = post_trip(CODE)
    assert r.status_code == 503 and "DAILY_AGENT_LIMIT" in r.json()["detail"]


def test_a_damaged_usage_file_counts_from_zero():
    access.USAGE_PATH.write_text("{ not json", encoding="utf-8")
    access.count_run()
    assert used() == 1
