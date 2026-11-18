# backend/store.py: one JSON file per trip in data/trips/, written atomically; unknown or malformed ids are not found.
import pytest

from backend import store


@pytest.fixture(autouse=True)
def _trips_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")


def test_save_then_load():
    trip = {"id": "lisbon-20261118-101500-ab12", "status": "researching", "profile": {"destination": "Lisbon"}}
    store.save(trip)
    assert store.load(trip["id"]) == trip
    assert store.path(trip["id"]).name == "lisbon-20261118-101500-ab12.json"


def test_save_replaces_the_file_and_leaves_no_temp_file():
    trip = {"id": "t-1", "status": "researching"}
    store.save(trip)
    store.save({**trip, "status": "ready"})
    assert store.load("t-1")["status"] == "ready"
    assert [p.name for p in store.TRIPS_DIR.iterdir()] == ["t-1.json"]


def test_unicode_is_kept():
    store.save({"id": "t-2", "notes": "Praça do Comércio, €"})
    assert store.load("t-2")["notes"] == "Praça do Comércio, €"


@pytest.mark.parametrize("trip_id", ["missing-1", "../etc/passwd", "UPPER", "a b", ""])
def test_unknown_or_bad_ids_are_not_found(trip_id):
    with pytest.raises(store.TripNotFound):
        store.load(trip_id)
