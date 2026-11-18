# scripts/create_agents.py: creates (first run) or updates (later runs) the environment and the two agents on Claude
# Managed Agents from prompts/*.md and the tool definitions in backend/agents.py, and writes their ids to the lock file.
# The Anthropic client is a fake: no network, no key.
import json

import pytest

from backend import agents
from scripts import create_agents
from tests.fake_anthropic import FakeAnthropic

ROOT = agents.ROOT


def calls(fake, kind):
    return [c for c in fake.calls if c[0] == kind]


def test_the_first_run_creates_the_environment_and_both_agents(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-opus-5-5")
    fake = FakeAnthropic()
    create_agents.main(client=fake)

    [(_, env)] = calls(fake, "environments.create")
    assert env["config"] == {"type": "cloud", "networking": {"type": "limited"}}
    created = {c[1]["name"]: c[1] for c in calls(fake, "agents.create")}
    assert set(created) == {"Travel planner: researcher", "Travel planner: verifier"}
    researcher, verifier = created["Travel planner: researcher"], created["Travel planner: verifier"]
    assert researcher["system"] == (ROOT / "prompts" / "researcher.md").read_text(encoding="utf-8")
    assert verifier["system"] == (ROOT / "prompts" / "verifier.md").read_text(encoding="utf-8")
    assert researcher["model"] == verifier["model"] == "claude-opus-5-5"
    assert researcher["tools"] == agents.agent_tools("researcher")
    assert verifier["tools"] == agents.agent_tools("verifier")
    assert calls(fake, "agents.update") == [] and calls(fake, "sessions.create") == []

    lock = json.loads(agents.LOCK.read_text())
    assert lock == {"environment_id": "env_new1", "researcher": {"id": "agent_new1", "version": 1},
                    "verifier": {"id": "agent_new2", "version": 1}}


def test_a_later_run_updates_the_same_agents(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-sonnet-5-5")
    agents.LOCK.parent.mkdir(parents=True)
    agents.LOCK.write_text(json.dumps({"environment_id": "env_old", "researcher": {"id": "agent_r", "version": 4},
                                       "verifier": {"id": "agent_v", "version": 2}}))
    fake = FakeAnthropic(versions={"agent_r": 4, "agent_v": 2})
    create_agents.main(client=fake)

    assert calls(fake, "environments.create") == [] and calls(fake, "agents.create") == []
    updated = {c[1]: c[2] for c in calls(fake, "agents.update")}
    assert set(updated) == {"agent_r", "agent_v"}
    assert updated["agent_r"]["model"] == "claude-sonnet-5-5"
    assert "version" not in updated["agent_r"]                     # the script owns the agents: update unconditionally
    lock = json.loads(agents.LOCK.read_text())
    assert lock == {"environment_id": "env_old", "researcher": {"id": "agent_r", "version": 5},
                    "verifier": {"id": "agent_v", "version": 3}}


def test_it_needs_the_model_setting():
    with pytest.raises(SystemExit, match="AGENT_MODEL"):
        create_agents.main(client=FakeAnthropic())
    assert not agents.LOCK.exists()
