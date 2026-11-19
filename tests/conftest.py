# Shared test setup: the sources log goes to a temp file, caches start empty, and fake keys are set.
# Agents: no test can create a real Anthropic client or read the real agents/agents.lock.json, source calls made by
# agent tools go to a fake server with no routes unless a test adds some, and agent settings from the shell are cleared.
import pytest

from tests import fake_apis

AGENT_SETTINGS = ("AGENT_MODEL", "RESEARCHER_CAP_CENTS", "VERIFIER_CAP_CENTS", "AGENT_DEADLINE_S", "ANTHROPIC_API_KEY")


@pytest.fixture(autouse=True)
def _isolated_sources(tmp_path, monkeypatch):
    from backend.sources import common, fx, viator

    monkeypatch.setattr(common, "LOG_PATH", tmp_path / "sources-log.jsonl")
    viator.clear_cache()
    fx.clear_cache()
    monkeypatch.setenv("VIATOR_API_KEY", fake_apis.VIATOR_KEY)
    monkeypatch.setenv("VIATOR_ENV", "production")
    monkeypatch.setenv("GEOAPIFY_API_KEY", fake_apis.GEO_KEY)
    monkeypatch.setenv("TAVILY_API_KEY", fake_apis.TAVILY_KEY)
    yield


@pytest.fixture(autouse=True)
def _no_real_agents(tmp_path, monkeypatch):
    from backend import agents

    def refuse():
        raise AssertionError("tests must not create a real Anthropic client: use tests/fake_anthropic.py")

    monkeypatch.setattr(agents, "_client", refuse)
    monkeypatch.setattr(agents, "LOCK", tmp_path / "agents" / "agents.lock.json")
    monkeypatch.setattr(agents, "HTTP", fake_apis.FakeAPIs().client())
    for name in AGENT_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_real_maps(monkeypatch):
    """The brochure's Geoapify static map goes to a fake server with no routes unless a test adds one."""
    from backend import brochure

    monkeypatch.setattr(brochure, "HTTP", fake_apis.FakeAPIs().client())
    yield
