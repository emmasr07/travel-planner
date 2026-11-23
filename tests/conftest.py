# Shared test setup: the sources log goes to a temp file, caches start empty, and fake keys are set.
# Access (backend/access.py): like the fake keys, every test has a test ACCESS_CODE set and sent with its requests, its
# own daily count in a temp file and the default limit; tests/test_access.py turns the sent code off to test the check.
# Agents: no test can create a real Anthropic client or read the real agents/agents.lock.json, source calls made by
# agent tools go to a fake server with no routes unless a test adds some, and agent settings from the shell are cleared.
import pytest

from tests import fake_apis

TEST_ACCESS_CODE = "test-access-code-3456"
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


@pytest.fixture(autouse=True)
def _access(tmp_path, monkeypatch):
    from backend import access, main

    monkeypatch.setattr(access, "USAGE_PATH", tmp_path / "agent-usage.json")
    monkeypatch.setenv("ACCESS_CODE", TEST_ACCESS_CODE)
    monkeypatch.delenv("DAILY_AGENT_LIMIT", raising=False)
    main.app.dependency_overrides[main.access_code] = lambda: TEST_ACCESS_CODE
    yield
    main.app.dependency_overrides.pop(main.access_code, None)
