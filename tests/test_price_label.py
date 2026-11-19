# price.label: which of a place's prices the record holds (regular, reduced, resident / non-resident, by age), copied
# word for word from the source; null when the source gives one price without a name. Prices are fixed test examples.
import json

import pytest
from fastapi.testclient import TestClient

from backend import agents, main, store
from backend.schema import SUGGESTION_FIELDS, validate_delivery, validate_sample
from tests.factories import experience
from tests.fake_apis import FakeAPIs
from tests.test_sources import search_one

client = TestClient(main.app)


def test_a_delivery_names_the_price_or_says_null():
    e = experience(price={"label": "Adult (non-resident)"})
    assert validate_delivery({"experiences": [e]}, min_items=False) == []
    e["price"]["label"] = None
    assert validate_delivery({"experiences": [e]}, min_items=False) == []
    del e["price"]["label"]
    assert validate_delivery({"experiences": [e]}, min_items=False) == [
        "experiences/0/price: 'label' is a required property"]
    e["price"]["label"] = 16
    assert validate_delivery({"experiences": [e]}, min_items=False)[0].startswith("experiences/0/price/label:")


def test_samples_may_have_no_label_yet():
    item = experience()
    for field in SUGGESTION_FIELDS:
        item.pop(field)
    assert validate_sample({"experiences": [item]}) == []
    del item["price"]["label"]
    assert validate_sample({"experiences": [item]}) == []


def test_viator_names_no_price_so_its_label_is_null():
    [rec] = search_one(FakeAPIs())
    assert rec["price"]["label"] is None


def test_demo_items_keep_the_sample_label(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)
    body = {"destination": "Lisbon", "start_date": "2026-12-04", "end_date": "2026-12-05", "group_type": "couple",
            "group_size": 2, "age_range": "25-34", "interests": ["culture"],
            "budget": {"amount": 150, "currency": "EUR", "per": "person"}, "pace": "balanced", "notes": ""}
    trip_id = client.post("/api/trips", json=body).json()["id"]
    trip = client.get(f"/api/trips/{trip_id}").json()
    assert trip["status"] == "ready", trip["error"]
    sample = {e["id"]: e for e in json.loads((agents.SAMPLES_DIR / "lisbon.json").read_text())["experiences"]}
    assert trip["experiences"]
    for e in trip["experiences"]:                     # Viator's age band, null for Geoapify places
        assert e["price"]["label"] == sample[e["id"]]["price"].get("label")
    assert any(e["price"]["label"] for e in trip["experiences"] if e["id"].startswith("viator-"))


@pytest.mark.parametrize("label", ["Adult (non-resident)", None])
def test_the_verifier_sees_the_label(label):
    assert agents._facts(experience(price={"label": label}))["price"]["label"] == label
