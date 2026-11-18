"""The Managed Agents event loop in backend/llm.py, against a fake client: no key, no cost.

It proves the loop answers the delivery tool, sends code errors back so the agent fixes its delivery, and stops at
idle. It does not prove the platform behaves like the fake: that takes one real run with MODE=agents.
"""
import json
from types import SimpleNamespace as NS

from backend import checks, llm

GOOD = json.loads(open("data/demo_research.json").read())["experiences"]


class FakeSessions:
    def __init__(self, deliveries):
        self.sent, self.deliveries = [], deliveries
        self.events = self

    def create(self, **kw):
        self.created = kw
        return NS(id="sesn_test")

    def stream(self, session_id):
        evs = [NS(type="agent.tool_use", name="web_search", input={"query": "x"}, id="sevt_1", evaluated_permission="allow")]
        for i, d in enumerate(self.deliveries):
            evs.append(NS(type="agent.custom_tool_use", name="deliver_experiences", input=d, id=f"sevt_d{i}"))
        evs.append(NS(type="session.status_idle", stop_reason=NS(type="end_turn")))
        return Stream(evs)

    def send(self, session_id, events):
        self.sent += events

    def retrieve(self, sid):
        return NS(usage=NS(list_cost="1.23"))


class Stream:  # what `with client.beta.sessions.events.stream(...) as stream` yields: an iterator of events
    def __init__(self, events): self.events = events
    def __enter__(self): return iter(self.events)
    def __exit__(self, *a): return False


def run(monkeypatch, tmp_path, deliveries):
    sessions = FakeSessions(deliveries)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: NS(beta=NS(sessions=sessions)))
    lock = tmp_path / "agents.lock.json"
    lock.write_text(json.dumps({"environment_id": "env_x", "researcher": {"id": "agent_r", "version": 1}}))
    monkeypatch.setattr(llm, "LOCK", lock)
    monkeypatch.setenv("MODE", "agents")
    steps = []
    out, sid = llm.research({"destination": "Seychelles"}, lambda w, t: steps.append(t), checks.delivery_errors)
    return out, sessions, steps


def test_bad_delivery_goes_back_then_good_one_is_kept(monkeypatch, tmp_path):
    out, sessions, steps = run(monkeypatch, tmp_path, [{"experiences": GOOD[:3]}, {"experiences": GOOD}])
    results = [e for e in sessions.sent if e["type"] == "user.custom_tool_result"]
    assert results[0].get("is_error") is True and "at least 10" in results[0]["content"][0]["text"]
    assert results[1].get("is_error") is None and out == GOOD
    assert sessions.created["budget"]["max_list_cost"] == {"amount": "400", "currency": "USD"}
    assert sessions.sent[0]["type"] == "user.message"
    assert any("web_search" in s for s in steps)
