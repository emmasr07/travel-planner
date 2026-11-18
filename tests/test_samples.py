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


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_sample_is_valid(path):
    data = json.loads(path.read_text())
    assert validate_sample(data) == []
    exps = data["experiences"]
    assert len(exps) <= 15
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
