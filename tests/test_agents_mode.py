# The whole pipeline through the API in MODE=agents (docs/backend-logic.md sections 3 and 7): any destination, the
# researcher and verifier sessions, prices converted with Frankfurter, the source check on the pages the researcher
# read, each agent step and each session's cost in the trip file. The Anthropic client and every HTTP call are fakes.
import json

import pytest
from fastapi.testclient import TestClient

from backend import main, store
from backend.sources import geoapify
from tests import fake_apis
from tests.agent_helpers import PAGE_URL, WEB, delivery, fake_http, from_the_web, install, set_up, verdicts
from tests.factories import experience
from tests.fake_anthropic import idle, tool_use, usage
from tests.real_places import NAVONA_RAW

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
    exps = [from_the_web(e) for e in delivery()["experiences"]]
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


def test_a_trip_uses_search_viator_when_the_key_works(http, monkeypatch):
    from tests import fake_apis
    code, url = "111P1", fake_apis.product_url("111P1")
    fake_apis.viator_routes(http, [(fake_apis.summary(code, "Alfama food walk"), fake_apis.details(code),
                                    fake_apis.schedule(code))])
    exps = delivery()["experiences"]
    exps[0].update(name="Alfama food walk", booking_url=url)
    exps[0]["price"].update(label=None, source={**exps[0]["price"]["source"], "provider": "viator", "url": url})
    ask = {"destination": "Lisbon", "interests": ["food"], "start_date": "2026-12-04", "end_date": "2026-12-06"}
    install(monkeypatch, [[tool_use("search_viator", ask)], [tool_use("deliver_experiences", {"experiences": exps})],
                          []], verify_script([e["id"] for e in exps]))
    trip = new_trip()

    assert trip["status"] == "ready", trip["error"]
    texts = [s["text"] for s in trip["steps"]]
    assert "search_viator Lisbon: food, 2026-12-04 to 2026-12-06" in texts
    assert not any("Viator unavailable" in t for t in texts)
    assert len(http.sent("/products/search")) == 1
    assert len(http.sent(f"/products/{code}")) == 2              # the researcher's search_viator, then the code's re-check
    walk = next(e for e in trip["experiences"] if e["id"] == "item-0")
    assert walk["booking_url"] == url and walk["price"]["source"]["provider"] == "viator"
    assert "Checked by the code" in walk["verdict"]["note"]


def test_a_square_found_by_find_place_is_always_open_and_a_tour_meeting_there_is_not(http, monkeypatch):
    http.add("GET", fake_apis.GEO + "/v2/place-details",
             fake_apis.place_details(opening_hours=None, wheelchair=None, tags=NAVONA_RAW))
    near = "-9.1365919,38.7077507"                                   # the fake Lisbon centre
    url = geoapify.public_url(geoapify.GEOCODE_URL, {"text": "Piazza Navona, Lisbon", "format": "json", "limit": 1,
                                                     "filter": f"circle:{near},30000", "bias": f"proximity:{near}"})
    spot = {"lat": 38.70775, "lng": -9.13618, "source": {"provider": "geoapify", "url": url, "quote": None,
                                                         "retrieved_at": "2026-11-25T09:12:49+01:00"}}
    exps = delivery()["experiences"]
    exps[0].update(name="Piazza Navona", opening_hours=None, category="culture")
    exps[1].update(name="Walking tour from Piazza Navona", opening_hours=None)
    for e in exps[:2]:
        e["location"].update(spot)
    install(monkeypatch, [[tool_use("find_place", {"name": "Piazza Navona", "city": "Lisbon"})],
                          [tool_use("deliver_experiences", {"experiences": exps})], []],
            verify_script([e["id"] for e in exps]))
    trip = new_trip()
    assert trip["status"] == "ready", trip["error"]

    by_id = {e["id"]: e for e in trip["experiences"]}
    square, tour = by_id["item-0"], by_id["item-1"]
    assert square["public_space"]["osm_tag"] == "place=square"
    assert square["public_space"]["source"]["url"].startswith("https://api.geoapify.com/v2/place-details?id=")
    assert next(c for c in square["checks"] if c["name"] == "hours") == {
        "name": "hours", "result": "ok", "detail": "public space, always open"}
    assert "public_space" not in tour                                # same spot, another name: not the square
    assert next(c for c in tour["checks"] if c["name"] == "hours")["detail"] == "no opening hours known"


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


# --- more candidates than the pace allows (first real trip: 10 for 2 days at a balanced pace, 5 a day) -----------

DAYS = [2, 1, 1, 2, 2, 1, 1, 2, 1, 2]           # the order the first real trip came in
TIMES = [("09:00", "11:00"), ("11:30", "13:30"), ("14:00", "16:00"), ("16:30", "18:30"), ("19:00", "21:00")]
TWO_DAYS = {"end_date": "2026-12-05"}


def five_a_day(**over_by_id):
    seen, exps = {1: 0, 2: 0}, []
    for i, day in enumerate(DAYS):
        start, end = TIMES[seen[day]]
        seen[day] += 1
        exps.append(from_the_web(experience(f"cand-{i}", name=f"Candidate {i}",
                                            schedule={"day": day, "start": start, "end": end},
                                            **over_by_id.get(f"cand-{i}", {}))))
    return exps


def kept_by_day(trip):
    out = {}
    for e in trip["experiences"]:
        if e["user"]["status"] == "kept" and e["status"] != "rejected":
            out.setdefault(e["schedule"]["day"], []).append(e["id"])
    return out


def check(e, name):
    return next(c for c in e["checks"] if c["name"] == name)


def test_the_code_keeps_the_best_fit_up_to_the_pace_and_the_rest_are_alternatives(monkeypatch):
    exps = five_a_day()
    fake = install(monkeypatch, research_script(exps), verify_script([e["id"] for e in exps]))
    trip = new_trip(**TWO_DAYS)
    assert trip["status"] == "ready", trip["error"]

    assert kept_by_day(trip) == {2: ["cand-0", "cand-3", "cand-4"], 1: ["cand-1", "cand-2", "cand-5"]}
    by_id = {e["id"]: e for e in trip["experiences"]}
    for i in ("cand-6", "cand-7", "cand-8", "cand-9"):
        assert by_id[i]["user"] == {"status": "removed", "position": None, "alternative": True}
        assert check(by_id[i], "pace") == {"name": "pace", "result": "skip",
                                           "detail": "an alternative: restore it to add it to your plan"}
    for day, ids in kept_by_day(trip).items():
        for i in ids:
            assert check(by_id[i], "pace") == {"name": "pace", "result": "ok", "detail": f"3 of 3 on day {day}"}
            assert "alternative" not in by_id[i]["user"]
    assert trip["totals"]["kept"] == 6
    assert any(s["who"] == "code" and s["text"] == "6 kept for 2 days at a balanced pace (up to 3 a day), best fit "
               "first; 4 more start as alternatives you can restore" for s in trip["steps"])
    sent = json.loads([e for e in fake.sent if e["type"] == "user.message"][1]["content"][0]["text"])
    assert len(sent["experiences"]) == 10                           # alternatives are verified too


def test_a_rejected_candidate_takes_no_place(monkeypatch):
    exps = five_a_day(**{"cand-1": {"min_age": 99}})
    install(monkeypatch, research_script(exps), verify_script([e["id"] for e in exps]))
    trip = new_trip(**TWO_DAYS)
    by_id = {e["id"]: e for e in trip["experiences"]}
    assert by_id["cand-1"]["status"] == "rejected" and by_id["cand-1"]["user"] == {"status": "kept", "position": None}
    assert kept_by_day(trip)[1] == ["cand-2", "cand-5", "cand-6"]
    assert any(s["text"].startswith("6 kept for 2 days") and "3 more start as alternatives" in s["text"]
               for s in trip["steps"])


def test_an_alternative_moves_up_when_the_verifier_contradicts_a_kept_one(monkeypatch):
    exps = five_a_day()
    answer = verdicts([e["id"] for e in exps])
    answer["verdicts"][1].update(verdict="contradicted", contested_fields=["price.amount"])   # cand-1, day 1
    install(monkeypatch, research_script(exps), [[tool_use("deliver_verdicts", answer)], []])
    trip = new_trip(**TWO_DAYS)
    assert kept_by_day(trip)[1] == ["cand-2", "cand-5", "cand-6"]
    assert {e["id"]: e["user"]["status"] for e in trip["experiences"]}["cand-8"] == "removed"


def test_restoring_an_alternative_makes_it_the_users_choice(monkeypatch):
    exps = five_a_day()
    install(monkeypatch, research_script(exps), verify_script([e["id"] for e in exps]))
    trip_id = new_trip(**TWO_DAYS)["id"]
    r = client.post(f"/api/trips/{trip_id}/experiences/cand-6", json={"status": "kept"})
    assert r.status_code == 200, r.text
    by_id = {e["id"]: e for e in r.json()["experiences"]}
    assert by_id["cand-6"]["user"] == {"status": "kept", "position": None}
    assert check(by_id["cand-6"], "pace")["detail"] == "4 experiences on day 1; a balanced pace allows 3"
    by_id = {e["id"]: e for e in client.post(f"/api/trips/{trip_id}/experiences/cand-6",
                                             json={"status": "removed"}).json()["experiences"]}
    assert check(by_id["cand-6"], "pace")["detail"] == "removed by you"
    assert check(by_id["cand-8"], "pace")["detail"] == "an alternative: restore it to add it to your plan"
