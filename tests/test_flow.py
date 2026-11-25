# The whole flow and its failures (roadmap step 5, item 1): a server restart in the middle of a trip or a search,
# and agents mode through the API from the questionnaire to the PDF, with every source and the Anthropic client faked.
# Prices are fixed test examples.
import pytest
from fastapi.testclient import TestClient

from backend import agents, main, store

client = TestClient(main.app)

DEMO_BODY = {"destination": "Lisbon", "start_date": "2026-12-04", "end_date": "2026-12-06", "group_type": "friends",
             "group_size": 4, "age_range": "25-34", "interests": ["culture", "nature"],
             "budget": {"amount": 250, "currency": "EUR", "per": "person"}, "pace": "balanced", "notes": ""}


@pytest.fixture(autouse=True)
def _trips(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)


def saved(trip_id, status, search=None):
    trip = {"id": trip_id, "created": "2026-11-23T10:00:00+01:00", "mode": "demo", "status": status, "profile": {},
            "steps": [{"at": "2026-11-23T10:00:01+01:00", "who": "code", "text": "a step before the restart"}],
            "experiences": [], "totals": None, "brochure": None, "error": None}
    if search:
        trip["search"] = search
    store.save(trip)
    return trip


def searching():
    return {"kind": "quick", "for": None, "request": "wine", "day": 1, "status": "searching", "options": [],
            "error": None, "picked": None, "started": "2026-11-23T10:00:02+01:00"}


# --- a restart in the middle of a trip or a search -----------------------------------------------------------------

def test_a_restart_fails_a_trip_left_in_a_busy_step_and_keeps_what_was_done():
    for status in ("researching", "checking", "verifying"):
        saved(f"cut-{status}", status)
    saved("fine-ready", "ready")
    with TestClient(main.app):                           # startup: the check for work a restart cut off
        pass
    for status in ("researching", "checking", "verifying"):
        trip = store.load(f"cut-{status}")
        assert trip["status"] == "failed"
        assert trip["error"] == f"the server restarted while the trip was {status}, so it stopped there"
        assert trip["steps"][0]["text"] == "a step before the restart"
        assert trip["steps"][-1]["who"] == "code" and trip["steps"][-1]["text"] == trip["error"]
    assert store.load("fine-ready")["status"] == "ready"


def test_a_restart_ends_a_search_left_searching_so_a_new_one_can_start(monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    r = client.post("/api/trips", json=DEMO_BODY)
    trip_id = r.json()["id"]
    trip = store.load(trip_id)
    assert trip["status"] == "ready", trip["error"]
    trip["search"] = searching()
    store.save(trip)
    assert client.post(f"/api/trips/{trip_id}/quick", json={"request": "a garden", "day": 1}).status_code == 409

    with TestClient(main.app):
        pass
    trip = store.load(trip_id)
    assert trip["status"] == "ready"
    assert trip["search"]["status"] == "failed"
    assert trip["search"]["error"] == "the server restarted during the search: ask again"
    assert client.post(f"/api/trips/{trip_id}/quick", json={"request": "a garden", "day": 1}).status_code == 202


def test_a_damaged_trip_file_does_not_stop_the_server_from_starting():
    store.TRIPS_DIR.mkdir(parents=True, exist_ok=True)
    (store.TRIPS_DIR / "broken-1.json").write_text("{ not json", encoding="utf-8")
    saved("cut-1", "researching")
    with TestClient(main.app) as started:
        assert started.get("/health").json() == {"ok": True}
    assert store.load("cut-1")["status"] == "failed"


# --- each trip keeps the mode it was planned in --------------------------------------------------------------------

def agents_trip(trip_id="porto-agents-1"):
    """A ready trip planned with the agents, as saved (one kept experience)."""
    from tests.factories import checked, profile
    e = checked("porto-walk")
    e.update(checks=[], verdict=None, status="to_check", cost_eur="140.00")
    trip = {"id": trip_id, "created": "2026-11-22T10:00:00+01:00", "mode": "agents", "status": "ready",
            "profile": profile(destination="Porto"), "steps": [], "experiences": [e], "totals": None,
            "brochure": None, "error": None}
    store.save(trip)
    return trip


def test_swap_and_quick_search_on_an_agents_trip_are_refused_by_a_demo_server(monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    agents_trip()
    for r in (client.post("/api/trips/porto-agents-1/swap/porto-walk"),
              client.post("/api/trips/porto-agents-1/quick", json={"request": "a wine bar", "day": 1})):
        assert r.status_code == 409
        assert r.json()["detail"] == ("this trip was planned with the AI agents and this server runs the demo: "
                                      "swap and quick search are off for it")
    assert "search" not in store.load("porto-agents-1")


def test_a_demo_trip_searches_its_sample_even_when_the_server_runs_the_agents(monkeypatch):
    from tests.agent_helpers import install, set_up
    monkeypatch.setenv("MODE", "demo")
    trip_id = client.post("/api/trips", json=DEMO_BODY).json()["id"]
    set_up(monkeypatch)                                          # the server now runs the agents
    fake = install(monkeypatch)                                  # no agent session may start
    r = client.post(f"/api/trips/{trip_id}/quick", json={"request": "a garden or a park", "day": 1})
    assert r.status_code == 202, r.text
    trip = store.load(trip_id)
    assert trip["search"]["status"] == "ready", trip["search"]["error"]
    assert all(o["verdict"]["note"].startswith("Demo mode") for o in trip["search"]["options"])
    assert fake.created == [] and "sessions" not in trip


# --- agents mode: fewer real results is fine, an empty list is allowed ---------------------------------------------

AGENTS_BODY = {**DEMO_BODY, "interests": ["food", "culture"]}


def research_and_verify(exps):
    from tests.agent_helpers import verdicts
    from tests.fake_anthropic import tool_use
    research = [[tool_use("deliver_experiences", {"experiences": exps})], []]
    verify = [[tool_use("deliver_verdicts", verdicts([e["id"] for e in exps]))], []]
    return research, verify


def test_the_researcher_may_deliver_fewer_than_ten(monkeypatch):
    from tests.agent_helpers import delivery, fake_http, from_the_web, install, set_up
    set_up(monkeypatch)
    fake_http(monkeypatch)
    exps = [from_the_web(e) for e in delivery(n=4)["experiences"]]
    install(monkeypatch, *research_and_verify(exps))
    trip = store.load(client.post("/api/trips", json=AGENTS_BODY).json()["id"])
    assert trip["status"] == "ready", trip["error"]
    assert [e["id"] for e in trip["experiences"]] == ["item-0", "item-1", "item-2", "item-3"]
    assert [s["role"] for s in trip["sessions"]] == ["researcher", "verifier"]


def test_the_researcher_may_deliver_nothing_and_no_verifier_runs(monkeypatch):
    from tests.agent_helpers import fake_http, install, set_up
    set_up(monkeypatch)
    fake_http(monkeypatch)
    install(monkeypatch, *research_and_verify([]))
    trip = store.load(client.post("/api/trips", json=AGENTS_BODY).json()["id"])
    assert trip["status"] == "ready", trip["error"]
    assert trip["experiences"] == [] and trip["totals"]["kept"] == 0
    assert trip["steps"][-1]["text"] == "ready: nothing to show, nothing invented"
    assert [s["role"] for s in trip["sessions"]] == ["researcher"]


def test_the_researcher_is_told_never_to_pad():
    tools = {t["name"]: t for t in agents.agent_tools("researcher")}
    deliver = tools["deliver_experiences"]
    assert "minItems" not in deliver["input_schema"]["properties"]["experiences"]
    assert "never invent one to fill the list" in deliver["description"]
    prompt = agents.prompt("researcher")
    assert "Choose up to 15" in prompt and "never pad" in prompt


def test_the_researcher_is_told_one_experience_per_place():
    prompt = agents.prompt("researcher")
    rule = prompt[prompt.index("One experience per place"):]
    rule = rule[:rule.index("\n5. ")]
    assert "includes entry" in rule and "photoshoot outside" in rule and "`why_fits`" in rule
    assert "15 m" in rule and "alternative" in rule


# --- agents mode through the API: questionnaire -> list -> brochure -> PDF, and what goes wrong on the way ----------

@pytest.fixture
def live(monkeypatch):
    """Agents mode with its settings, the fake sources (Geoapify, Tavily, Frankfurter) and the sources log in tmp."""
    from tests.agent_helpers import fake_http, set_up
    set_up(monkeypatch)
    return fake_http(monkeypatch)


def priced(n=10, amount=20.0):
    """n experiences whose facts come from a web page (so the verifier agent runs), at a fixed example price."""
    from tests.agent_helpers import delivery, from_the_web
    return [from_the_web(e) for e in delivery(n=n, price={"amount": amount})["experiences"]]


def plan_trip(monkeypatch, exps, *more_sessions, verify=True, body=None):
    from tests.agent_helpers import install
    research, verifier = research_and_verify(exps)
    fake = install(monkeypatch, research, *([verifier] if verify else []), *more_sessions)
    r = client.post("/api/trips", json=body or AGENTS_BODY)
    assert r.status_code == 201, r.text
    return r.json()["id"], fake


def test_an_agents_trip_goes_from_the_questionnaire_to_the_pdf_and_no_key_reaches_the_browser(live, monkeypatch):
    from backend.sources import common
    from tests import fake_apis
    trip_id, _ = plan_trip(monkeypatch, priced())
    answers = [client.get(f"/api/trips/{trip_id}")]
    trip = answers[0].json()
    assert trip["status"] == "ready", trip["error"]
    assert trip["totals"]["over"] is False and trip["totals"]["kept"] == 9             # 3 a day, balanced, 3 days

    answers.append(client.post(f"/api/trips/{trip_id}/brochure"))
    assert answers[-1].status_code == 200, answers[-1].text
    built = answers[-1].json()
    assert built["status"] == "done" and len(built["brochure"]["stops"]) == 9
    assert built["brochure"]["map"]["kind"] == "plot"                 # the map source did not answer: pins by coordinates
    pdf = client.get(f"/api/trips/{trip_id}/brochure.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert client.get(f"/api/trips/{trip_id}/brochure/map.png").status_code == 404
    answers += [client.get(f"/api/trips/{trip_id}/json"), client.get("/api/config")]

    seen = [a.text for a in answers] + [store.path(trip_id).read_text(encoding="utf-8"),
                                        common.LOG_PATH.read_text(encoding="utf-8")]
    for key in fake_apis.ALL_KEYS:
        assert all(key not in text for text in seen), key
        assert key.encode() not in pdf.content


def test_an_agents_trip_over_budget_refuses_the_brochure_until_the_user_removes_something(live, monkeypatch):
    trip_id, _ = plan_trip(monkeypatch, priced(amount=40.0))           # 9 kept x 40 = 360 a person, budget 250
    trip = client.get(f"/api/trips/{trip_id}").json()
    assert trip["status"] == "ready" and trip["totals"]["over"] is True
    r = client.post(f"/api/trips/{trip_id}/brochure")
    assert r.status_code == 409 and r.json()["detail"].startswith("over budget by €")
    proposal = client.post(f"/api/trips/{trip_id}/fit-budget").json()
    assert proposal["remove"] and client.get(f"/api/trips/{trip_id}").json()["totals"]["over"] is True  # nothing removed
    for item in proposal["remove"]:
        assert client.post(f"/api/trips/{trip_id}/experiences/{item['id']}", json={"status": "removed"}).status_code == 200
    assert client.post(f"/api/trips/{trip_id}/brochure").status_code == 200


def test_the_city_lookup_down_fails_the_trip_with_a_plain_error_and_no_key(live, monkeypatch):
    from tests import fake_apis
    live.add("GET", fake_apis.GEO + "/v1/geocode/search", (500, {"message": "Internal error"}))
    trip_id, fake = plan_trip(monkeypatch, priced(), verify=False)
    trip = store.load(trip_id)
    assert trip["status"] == "failed"
    assert trip["error"] == "SourceError: geoapify returned 500 for GET /v1/geocode/search text='Lisbon' type=city"
    assert fake_apis.GEO_KEY not in trip["error"] and fake.created == []         # no agent session was paid for


def test_frankfurter_down_leaves_a_foreign_price_unconverted_and_not_counted(live, monkeypatch):
    from tests import fake_apis
    live.add("GET", fake_apis.FX + "/v2/rates", (500, {"message": "down"}))
    exps = priced()
    exps[1]["price"].update(amount=20.0, currency="GBP")
    trip_id, _ = plan_trip(monkeypatch, exps)
    trip = store.load(trip_id)
    assert trip["status"] == "ready", trip["error"]
    gbp = next(e for e in trip["experiences"] if e["id"] == "item-1")
    assert gbp["price"]["amount_eur"] is None and gbp["cost_eur"] is None and gbp["status"] == "to_check"
    assert next(c for c in gbp["checks"] if c["name"] == "price")["result"] == "warn"
    assert "item-1" in trip["totals"]["not_counted"]
    assert any("in a currency with no known rate (not counted)" in s["text"] for s in trip["steps"])


def test_the_verifier_at_its_cost_cap_fails_the_trip_and_keeps_both_costs_and_the_list(live, monkeypatch):
    from tests.agent_helpers import install
    from tests.fake_anthropic import idle, usage
    research, _ = research_and_verify(priced())
    install(monkeypatch, research, [[usage("51"), idle("budget_reached")]], cost="51")
    trip = store.load(client.post("/api/trips", json=AGENTS_BODY).json()["id"])
    assert trip["status"] == "failed"
    assert trip["error"] == "AgentFailed: verifier stopped at its cost cap ($0.50) before delivering"
    assert [(s["role"], s["stop"]) for s in trip["sessions"]] == [("researcher", "end_turn"),
                                                                 ("verifier", "budget_reached")]
    assert len(trip["experiences"]) == 10                     # what was done before is kept in the file


def test_a_swap_at_its_cost_cap_fails_the_search_and_the_list_stays_usable(live, monkeypatch):
    from tests.fake_anthropic import idle, usage
    trip_id, _ = plan_trip(monkeypatch, priced(), [[usage("101"), idle("budget_reached")]])
    assert client.post(f"/api/trips/{trip_id}/swap/item-0").status_code == 202
    trip = store.load(trip_id)
    assert trip["status"] == "ready"
    assert trip["search"]["status"] == "failed"
    assert "stopped at its cost cap ($1.00)" in trip["search"]["error"]
    assert trip["sessions"][-1]["purpose"] == "quick" and trip["sessions"][-1]["stop"] == "budget_reached"
    assert client.post(f"/api/trips/{trip_id}/experiences/item-0", json={"status": "removed"}).status_code == 200
