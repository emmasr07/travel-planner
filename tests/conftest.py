# Shared test setup: the sources log goes to a temp file, caches start empty, and fake keys are set.
import pytest

from tests import fake_apis


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
