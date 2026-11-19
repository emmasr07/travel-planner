# The sample datasets in data/samples/: real experiences, FACT fields only, valid against the experiences schema
# (minus best_time, why_fits and schedule, which the agent fills later). Fails until build_sample.py has run.
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

from backend.schema import SUGGESTION_FIELDS, validate_sample

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
TEST_DESTINATIONS = ["lisbon", "london", "matera"]
FILES = sorted(SAMPLES.glob("*.json"))


def source_blocks(node):
    if isinstance(node, dict):
        if {"provider", "url", "retrieved_at", "quote"} <= set(node):
            yield node
        for value in node.values():
            yield from source_blocks(value)
    elif isinstance(node, list):
        for value in node:
            yield from source_blocks(value)


def test_every_test_destination_has_a_sample():
    missing = [c for c in TEST_DESTINATIONS if not (SAMPLES / f"{c}.json").exists()]
    assert missing == [], f"run: PY -m scripts.build_sample <City> for {missing}"


@pytest.mark.parametrize("city", TEST_DESTINATIONS)
def test_sample_has_viator_experiences_alongside_the_geoapify_places(city):
    exps = json.loads((SAMPLES / f"{city}.json").read_text())["experiences"]
    tours = [e for e in exps if e["id"].startswith("viator-")]
    assert tours, f"run: PY -m scripts.build_sample <City> for {city}"
    assert any(e["id"].startswith("osm-") for e in exps)
    for e in tours:
        price = e["price"]
        assert price["amount"] is not None and price["source"]["provider"] == "viator"
        assert "label" in price
        if e["rating"] is not None:                                    # null when Viator has no reviews yet
            assert e["rating"]["review_count"] > 0 and e["rating"]["source"]["provider"] == "viator"
        assert e["location"]["source"]["provider"] == "geoapify"
    assert any(e["rating"] for e in tours)


def test_lisbon_keeps_the_closed_museum_for_the_closure_check():
    exps = json.loads((SAMPLES / "lisbon.json").read_text())["experiences"]
    museum = next(e for e in exps if e["id"] == "osm-n5090471903")
    assert museum["description"] == "Encerrado temporrariamente"


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_sample_is_valid(path):
    data = json.loads(path.read_text())
    assert validate_sample(data) == []
    exps = data["experiences"]
    assert len(exps) <= 25
    ids = [e["id"] for e in exps]
    assert len(ids) == len(set(ids))
    for e in exps:
        assert not set(SUGGESTION_FIELDS) & set(e)
        link = urlparse(e["booking_url"])
        assert link.scheme in ("http", "https") and link.hostname
        if e["id"].startswith("viator-"):
            assert link.hostname == "www.viator.com"
        for block in source_blocks(e):
            assert block["provider"] in ("viator", "geoapify", "web", "frankfurter")
            assert datetime.fromisoformat(block["retrieved_at"]).utcoffset() is not None
