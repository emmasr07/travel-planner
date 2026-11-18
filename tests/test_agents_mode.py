# The whole pipeline through the API in MODE=agents (docs/backend-logic.md sections 3 and 7): any destination, the
# researcher and verifier sessions, prices converted with Frankfurter, the source check on the pages the researcher
# read, each agent step and each session's cost in the trip file. The Anthropic client and every HTTP call are fakes.
import pytest
from fastapi.testclient import TestClient

from backend import main, store
from tests.agent_helpers import PAGE_URL, WEB, delivery, fake_http, install, set_up, verdicts
from tests.fake_anthropic import idle, tool_use, usage

client = TestClient(main.app)

BODY = {"destination": "Lisbon", "start_date": "2026-12-04", "end_date": "2026-12-06", "group_type": "friends",
        "group_size": 4, "age_range": "25-34", "interests": ["food", "culture"],
        "budget": {"amount": 250, "currency": "EUR", "per": "person"}, "pace": "balanced", "notes": ""}


@pytest.fixture(autouse=True)
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    set_up(monkeypatch)
    return fake_http(monkeypatch)


def researched():
    exps = delivery()["experiences"]
    exps[0]["opening_hours"] = {"text": "Daily 09:00", "slots": ["09:00"], "source": WEB}
    exps[1]["price"].update(amount=20.0, currency="GBP")
    return exps


def research_script(exps):
    return [[tool_use("read_page", {"url": PAGE_URL})], [tool_use("deliver_experiences", {"experiences": exps})], []]


def verify_script(ids):
    return [[tool_use("deliver_verdicts", verdicts(ids))], []]


def new_trip(**over):
    r = client.post("/api/trips", json={**BODY, **over})
    assert r.status_code == 201, r.text
    return client.get(f"/api/trips/{r.json()['id']}").json()


def test_a_trip_runs_both_agents_and_reaches_ready(http, monkeypatch):
    exps = researched()
    install(monkeypatch, research_script(exps), verify_script([e["id"] for e in exps]))
    trip = new_trip()

    assert trip["status"] == "ready", trip["error"]
    assert trip["mode"] == "agents" and trip["profile"]["timezone"] == "Europe/Lisbon"
    assert {"researcher", "verifier", "code"} <= {s["who"] for s in trip["steps"]}
    assert any(s["who"] == "researcher" and s["text"] == f"read_page {PAGE_URL}" for s in trip["steps"])
    assert [s["role"] for s in trip["sessions"]] == ["researcher", "verifier"]
    assert all(s["list_cost"] == {"amount": "37", "currency": "USD"} for s in trip["sessions"])

    by_id = {e["id"]: e for e in trip["experiences"]}
    source = next(c for c in by_id["item-0"]["checks"] if c["name"] == "source")
    assert source["result"] == "ok"                                  # the quote is on the page the researcher read
    assert len(http.sent("/extract")) == 1                           # read once, by the researcher's tool
    gbp = by_id["item-1"]["price"]
    assert gbp["amount_eur"] == 24.0 and gbp["fx"]["source"]["provider"] == "frankfurter"
    assert all(e["verdict"]["verdict"] == "confirmed" for e in trip["experiences"])


def test_any_destination_works_without_a_sample(monkeypatch):
    exps = delivery()["experiences"]
    install(monkeypatch, research_script(exps), verify_script([e["id"] for e in exps]))
    trip = new_trip(destination="Porto")
    assert trip["status"] == "ready", trip["error"]
    assert trip["profile"]["destination"] == "Porto"


def test_a_session_at_its_cap_fails_the_trip_and_keeps_its_cost(monkeypatch):
    install(monkeypatch, [[tool_use("search_web", {"query": "q"})], [usage("101"), idle("budget_reached")]],
            cost="101")
    trip = new_trip()
    assert trip["status"] == "failed"
    assert "stopped at its cost cap ($1.00)" in trip["error"]
    assert trip["experiences"] == []
    [session] = trip["sessions"]
    assert session["stop"] == "budget_reached" and session["list_cost"]["amount"] == "101"


def test_agents_mode_without_the_lock_file_is_503(monkeypatch):
    from backend import agents
    agents.LOCK.unlink()
    r = client.post("/api/trips", json=BODY)
    assert r.status_code == 503
    assert "agents mode is not set up" in r.json()["detail"] and "scripts.create_agents" in r.json()["detail"]
