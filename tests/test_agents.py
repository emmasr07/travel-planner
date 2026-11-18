# backend/agents.py in agents mode: one Claude Managed Agents session per job, with a cost cap, a time limit and the
# model from the settings; custom tools answered by our code over backend/sources/; deliveries checked by the code and
# sent back with their errors (3 tries); the session's cost recorded. The Anthropic client and every HTTP call are fakes.
import json

import pytest

from backend import agents
from tests import fake_apis
from tests.agent_helpers import PAGE_QUOTE, PAGE_URL, WEB, Steps, delivery, fake_http, install, set_up, verdicts
from tests.factories import checked, experience, profile
from tests.fake_anthropic import DROP, HANG, idle, session_error, tool_use, usage

BUILT_IN = {"bash", "read", "write", "edit", "glob", "grep", "web_fetch", "web_search"}


@pytest.fixture
def ready(monkeypatch):
    set_up(monkeypatch)
    return fake_http(monkeypatch)


def research(prof=None, **kwargs):
    steps, recorded, pages = Steps(), [], {}
    out = agents.research(prof or profile(), steps, record=recorded.append, pages=pages, **kwargs)
    return out, steps, recorded, pages


def results(fake):
    """(text, is_error) of every tool result we sent, in order."""
    return [(e["content"][0]["text"], e.get("is_error", False)) for e in fake.sent if e["type"] == "user.custom_tool_result"]


# --- one research session -------------------------------------------------------------------------------------

def test_research_runs_one_capped_session_with_the_model_from_the_settings(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("search_web", {"query": "Lisbon tram 28"})],
                                 [tool_use("read_page", {"url": PAGE_URL})],
                                 [tool_use("deliver_experiences", delivery())],
                                 []])
    prof = profile(timezone=None)
    out, steps, recorded, pages = research(prof)

    assert out == delivery()
    [create] = fake.created
    assert create["agent"] == {"type": "agent_with_overrides", "id": "agent_res", "version": 3,
                               "model": {"id": "claude-opus-5-5"}}
    assert create["environment_id"] == "env_test"
    assert create["budget"] == {"type": "limit", "max_list_cost": {"amount": "100", "currency": "USD"}}
    message = next(e for e in fake.sent if e["type"] == "user.message")
    assert json.loads(message["content"][0]["text"])["destination"] == "Lisbon"
    assert prof["timezone"] == "Europe/Lisbon"                       # found by code (Geoapify), not by the agent
    assert pages[PAGE_URL] == PAGE_QUOTE                             # kept for the code's source check
    assert ("researcher", "search_web 'Lisbon tram 28'") in steps
    assert any(who == "researcher" and text.startswith("session sesn_test1 started") for who, text in steps)
    assert "list cost $0.37" in steps.text()
    [info] = recorded
    assert info["role"] == "researcher" and info["session_id"] == "sesn_test1"
    assert info["model"] == "claude-opus-5-5" and info["cap"] == {"amount": "100", "currency": "USD"}
    assert info["list_cost"] == {"amount": "37", "currency": "USD"} and info["stop"] == "end_turn"
    assert info["deliveries"] == 1 and info["tool_calls"] == 3


def test_a_wrong_delivery_goes_back_with_its_errors(ready, monkeypatch):
    bad = delivery()
    bad["experiences"][0]["price"]["amount"] = "35"
    fake = install(monkeypatch, [[tool_use("deliver_experiences", bad)],
                                 [tool_use("deliver_experiences", delivery())], []])
    out, steps, recorded, _ = research()
    assert out == delivery()
    (first, first_error), (second, second_error) = results(fake)
    assert first_error and "experiences/0/price/amount" in first
    assert not second_error
    assert "delivery 1 refused by the code checks" in steps.text()
    assert recorded[0]["deliveries"] == 2


def test_three_wrong_deliveries_stop_the_session(ready, monkeypatch):
    bad = delivery(n=9)                                             # fewer than 10
    fake = install(monkeypatch, [[tool_use("deliver_experiences", bad)]] * 3 + [[]])
    with pytest.raises(agents.AgentFailed, match="still had errors after 3 deliveries"):
        research()
    assert all(is_error for _, is_error in results(fake)) and len(results(fake)) == 3
    assert fake.interrupted


def test_viator_401_answers_viator_unavailable_and_the_agent_goes_on(ready, monkeypatch):
    ready.add("GET", fake_apis.VIATOR_PROD + "/partner/destinations", (401, {"message": "Invalid API Key"}))
    ask = {"destination": "Lisbon", "interests": ["food"], "start_date": "2026-12-04", "end_date": "2026-12-06"}
    fake = install(monkeypatch, [[tool_use("search_viator", ask)], [tool_use("deliver_experiences", delivery())], []])
    out, _, _, _ = research()
    assert out == delivery()
    text, is_error = results(fake)[0]
    assert is_error and text.startswith("Viator unavailable")
    assert fake_apis.VIATOR_KEY not in text


def test_find_place_stays_within_30_km_of_the_city(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("find_place", {"name": "Praça do Comércio", "city": "Lisbon"})],
                                 [tool_use("deliver_experiences", delivery())], []])
    research()
    place = [r for r in ready.sent("/v1/geocode/search") if r.url.params.get("type") != "city"][-1]
    assert place.url.params["filter"] == "circle:-9.1365919,38.7077507,30000"
    found = json.loads(results(fake)[0][0])
    assert found["lat"] == 38.70775 and found["source"]["provider"] == "geoapify"


def test_read_page_sends_the_agent_at_most_30000_characters(monkeypatch):
    set_up(monkeypatch)
    fake_http(monkeypatch, page_text="x" * 40_000)
    fake = install(monkeypatch, [[tool_use("read_page", {"url": PAGE_URL})],
                                 [tool_use("deliver_experiences", delivery())], []])
    _, _, _, pages = research()
    page = json.loads(results(fake)[0][0])
    assert len(page["text"]) == 30_000 and page["truncated"] is True
    assert page["source"]["provider"] == "web" and page["source"]["url"] == PAGE_URL
    assert len(pages[PAGE_URL]) == 40_000


def test_an_unknown_tool_is_an_error_result(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("web_search", {"query": "x"})], [tool_use("deliver_experiences", delivery())], []])
    research()
    text, is_error = results(fake)[0]
    assert is_error and "no tool called web_search" in text


# --- stopping ---------------------------------------------------------------------------------------------------

def test_the_cost_cap_stops_the_session_and_its_cost_is_recorded(ready, monkeypatch):
    install(monkeypatch, [[tool_use("search_web", {"query": "q"})], [usage("104"), idle("budget_reached")]], cost="104")
    steps, recorded = Steps(), []
    with pytest.raises(agents.AgentFailed, match=r"stopped at its cost cap \(\$1\.00\) before delivering"):
        agents.research(profile(), steps, record=recorded.append, pages={})
    assert recorded[0]["stop"] == "budget_reached"
    assert recorded[0]["list_cost"] == {"amount": "104", "currency": "USD"}
    assert "list cost $1.04" in steps.text()


def test_the_time_limit_interrupts_the_session(monkeypatch):
    set_up(monkeypatch, AGENT_DEADLINE_S="1")
    fake_http(monkeypatch)
    fake = install(monkeypatch, [HANG])
    recorded = []
    with pytest.raises(agents.AgentFailed, match="no delivery within 1 s"):
        agents.research(profile(), Steps(), record=recorded.append, pages={})
    assert fake.interrupted
    assert recorded[0]["stop"] == "time_limit"


def test_a_session_error_that_is_not_retried_fails_with_its_message(ready, monkeypatch):
    install(monkeypatch, [[session_error("The model is overloaded."), idle("retries_exhausted")]])
    with pytest.raises(agents.AgentFailed, match="The model is overloaded."):
        research()


def test_a_dropped_stream_reconnects_and_answers_the_missed_call_once(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("search_web", {"query": "q"})],
                                 [DROP, tool_use("read_page", {"url": PAGE_URL})],
                                 [tool_use("deliver_experiences", delivery())], []])
    out, steps, _, _ = research()
    assert out == delivery()
    assert len(results(fake)) == 3 and len(fake.results) == 3       # each call answered exactly once
    assert len(fake.streams) == 2 and "reconnecting" in steps.text()


# --- the verifier -----------------------------------------------------------------------------------------------

def to_verify():
    exps = [checked(f"item-{i}", opening_hours={"text": "Daily 10:00", "slots": ["10:00"], "source": WEB})
            for i in range(2)]
    for e in exps:
        e.update(status="to_check", cost_eur="35.00")
    return exps


def test_the_verifier_gets_the_facts_only_and_a_lower_cap(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("read_page", {"url": PAGE_URL})],
                                 [tool_use("deliver_verdicts", verdicts(["item-0", "item-1"]))], []])
    steps, recorded = Steps(), []
    out = agents.verify(profile(), to_verify(), steps, record=recorded.append)
    assert out == verdicts(["item-0", "item-1"])
    [create] = fake.created
    assert create["agent"]["id"] == "agent_ver" and create["agent"]["version"] == 2
    assert create["budget"]["max_list_cost"]["amount"] == "50"
    sent = json.loads(next(e for e in fake.sent if e["type"] == "user.message")["content"][0]["text"])
    assert sent["profile"]["destination"] == "Lisbon"
    for e in sent["experiences"]:
        assert not {"best_time", "why_fits", "schedule", "checks", "user", "verdict", "status", "cost_eur"} & set(e)
        assert "amount_eur" not in e["price"] and "fx" not in e["price"]
        assert e["opening_hours"]["source"]["quote"] == PAGE_QUOTE
    assert recorded[0]["role"] == "verifier"


def test_the_verifier_has_no_search_tool(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("search_web", {"query": "q"})],
                                 [tool_use("deliver_verdicts", verdicts(["item-0", "item-1"]))], []])
    agents.verify(profile(), to_verify(), Steps())
    text, is_error = results(fake)[0]
    assert is_error and "no tool called search_web" in text


def test_every_experience_needs_exactly_one_verdict(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("deliver_verdicts", verdicts(["item-0", "other"]))],
                                 [tool_use("deliver_verdicts", verdicts(["item-0", "item-1"]))], []])
    agents.verify(profile(), to_verify(), Steps())
    text, is_error = results(fake)[0]
    assert is_error and "item-1: no verdict" in text and "other: not an experience you received" in text


# --- quick search -----------------------------------------------------------------------------------------------

ASK = {"kind": "quick", "request": "We suddenly want a wine tasting", "day": 2,
       "free_slots": [{"start": "15:00", "end": "19:00"}], "budget_left": {"amount": "50.00", "currency": "EUR",
                                                                          "per": "person"},
       "taken": ["alfama-food-walk"], "for": None}


def option(id="wine-tasting", start="15:30", end="17:30"):
    return experience(id, name="Wine tasting", schedule={"day": 2, "start": start, "end": end})


def test_quick_search_uses_the_researcher_with_the_quick_instructions(ready, monkeypatch):
    late = option(start="18:00", end="20:00")
    fake = install(monkeypatch, [[tool_use("deliver_experiences", {"experiences": [late]})],
                                 [tool_use("deliver_experiences", {"experiences": [option()]})], []])
    steps, recorded = Steps(), []
    out = agents.quick(profile(), ASK, steps, record=recorded.append, pages={})
    assert out == {"experiences": [option()]}
    [create] = fake.created
    agent = create["agent"]
    assert agent["id"] == "agent_res" and agent["model"] == {"id": "claude-opus-5-5"}
    assert "# Researcher agent" in agent["system"] and "# Quick search" in agent["system"]
    deliver = next(t for t in agent["tools"] if t["name"] == "deliver_experiences")
    array = deliver["input_schema"]["properties"]["experiences"]
    assert array["maxItems"] == 3 and "minItems" not in array
    assert [t["name"] for t in agent["tools"]] == [t["name"] for t in agents.agent_tools("researcher")]
    sent = json.loads(next(e for e in fake.sent if e["type"] == "user.message")["content"][0]["text"])
    assert set(sent) == {"profile", "request", "day", "free_slots", "budget_left"}
    text, is_error = results(fake)[0]
    assert is_error and "not inside a free slot" in text
    assert recorded[0]["purpose"] == "quick"


def test_quick_search_may_deliver_nothing(ready, monkeypatch):
    install(monkeypatch, [[tool_use("deliver_experiences", {"experiences": []})], []])
    assert agents.quick(profile(), ASK, Steps(), pages={}) == {"experiences": []}


def test_quick_search_refuses_an_id_already_in_the_trip(ready, monkeypatch):
    fake = install(monkeypatch, [[tool_use("deliver_experiences", {"experiences": [option("alfama-food-walk")]})],
                                 [tool_use("deliver_experiences", {"experiences": [option()]})], []])
    agents.quick(profile(), ASK, Steps(), pages={})
    assert "alfama-food-walk: this id is already in the trip" in results(fake)[0][0]


# --- settings, tools, pages and rates ---------------------------------------------------------------------------

def test_settings_name_what_is_missing(monkeypatch):
    with pytest.raises(agents.NotReady, match="AGENT_MODEL"):
        agents.settings()
    set_up(monkeypatch)
    assert agents.settings()["model"] == "claude-opus-5-5"
    for name, value in [("RESEARCHER_CAP_CENTS", "1.5"), ("VERIFIER_CAP_CENTS", "0"), ("AGENT_DEADLINE_S", "ten")]:
        set_up(monkeypatch, **{name: value})
        with pytest.raises(agents.NotReady, match=name):
            agents.settings()
    set_up(monkeypatch)
    agents.LOCK.unlink()
    with pytest.raises(agents.NotReady, match="scripts.create_agents"):
        agents.settings()


def test_the_tools_each_agent_gets():
    researcher, verifier = agents.agent_tools("researcher"), agents.agent_tools("verifier")
    assert [t["name"] for t in researcher] == ["search_viator", "find_place", "search_web", "read_page",
                                               "deliver_experiences"]
    assert [t["name"] for t in verifier] == ["read_page", "deliver_verdicts"]
    for tool in researcher + verifier:
        assert tool["type"] == "custom" and tool["name"] not in BUILT_IN
        assert set(tool["input_schema"]) <= {"type", "properties", "required"}
        assert tool["input_schema"]["type"] == "object" and len(tool["description"]) > 100
        assert "$ref" not in json.dumps(tool)
    deliver = researcher[-1]["input_schema"]["properties"]["experiences"]
    assert deliver["minItems"] == 10 and deliver["maxItems"] == 15
    assert deliver["items"]["properties"]["location"]["properties"]["source"]["required"] == [
        "provider", "url", "retrieved_at", "quote"]


def test_source_pages_reuse_what_the_researcher_read_and_fetch_the_rest(ready, monkeypatch):
    exps = [checked(opening_hours={"text": "Daily 10:00", "slots": ["10:00"], "source": WEB})]
    assert agents.source_pages(exps, {PAGE_URL: "already read"}) == {PAGE_URL: "already read"}
    assert ready.sent("/extract") == []
    assert agents.source_pages(exps, {}) == {PAGE_URL: PAGE_QUOTE}
    monkeypatch.setenv("MODE", "demo")
    assert agents.source_pages(exps, {}) is None


def test_rates_come_from_frankfurter_in_agents_mode(ready, monkeypatch):
    exps = [checked(price={"amount": 20.0, "currency": "GBP"}), checked("b"), checked("c", price={"amount": None})]
    rates = agents.rates(profile(), exps)
    assert set(rates) == {"GBP"} and rates["GBP"]["rate"] == 1.1998
    assert [r.url.params["base"] for r in ready.sent("/v2/rates")] == ["GBP"]
