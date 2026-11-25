# One experience per place (docs/backend-logic.md sections 3 and 5): going down the researcher's list, an item that
# is the same place as one already kept, or the same visit with entry included, starts as an alternative with a note.
# The user can restore it. The Rome trip rome-20261122-231553-9b61 as a demo sample: real names, coordinates and
# descriptions (tests/real_places.py), fixed example prices. No AI, no network.
import json

import pytest
from fastapi.testclient import TestClient

from backend import agents, main, store, trips
from backend.schema import SUGGESTION_FIELDS
from tests.factories import experience, profile
from tests.real_places import PHOTO, PHOTO_2, PIZZA, ROME, TICKET, TOUR, fields, place

client = TestClient(main.app)

BODY = {"destination": "Rome", "start_date": "2026-12-05", "end_date": "2026-12-07", "group_type": "couple",
        "group_size": 2, "age_range": "25-34", "interests": ["culture", "food"],
        "budget": {"amount": 2000, "currency": "EUR", "per": "person"}, "pace": "packed", "notes": ""}
SAME_AS_TOUR = "Same place as Colosseum Roman Forum and Palatine Hill Guided Tour"


def sample_item(rec):
    over = fields(rec)
    over.pop("schedule")
    over["location"].update(city="Rome", timezone="Europe/Rome")
    e = experience(rec["id"], **over)
    for field in SUGGESTION_FIELDS:
        e.pop(field)
    return e


@pytest.fixture(autouse=True)
def _demo(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    monkeypatch.setattr(store, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(agents, "DEMO_PAUSE_S", 0)
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "rome.json").write_text(json.dumps({"experiences": [sample_item(r) for r in ROME]}))
    monkeypatch.setattr(agents, "SAMPLES_DIR", samples)


def new_trip():
    r = client.post("/api/trips", json=BODY)
    assert r.status_code == 201, r.text
    trip = client.get(f"/api/trips/{r.json()['id']}").json()
    assert trip["status"] == "ready", trip["error"]
    return trip


def by_id(trip):
    return {e["id"]: e for e in trip["experiences"]}


def check(e, name):
    return next(c for c in e["checks"] if c["name"] == name)


def test_the_same_place_starts_as_an_alternative_with_a_note():
    trip = new_trip()
    exps = by_id(trip)
    assert len(exps) == 10                               # packed, 3 days: all 10 proposed, nothing dropped
    for photo in (PHOTO, PHOTO_2):
        e = exps[photo["id"]]
        assert e["user"] == {"status": "removed", "position": None, "alternative": True, "same_as": TOUR["id"]}
        for name in ("overlap", "pace"):
            assert check(e, name) == {"name": name, "result": "skip",
                                      "detail": f"{SAME_AS_TOUR}: restore it to add it to your plan"}
    kept = [e["id"] for e in trip["experiences"] if e["user"]["status"] == "kept"]
    assert kept == [r["id"] for r in ROME if r not in (PHOTO, PHOTO_2)]
    assert trip["totals"]["kept"] == 8
    assert any(s["who"] == "code" and s["text"] == "8 kept for 3 days at a packed pace (up to 4 a day), best fit "
               "first; 2 more start as alternatives you can restore (2 of them at the same place as one you keep)"
               for s in trip["steps"])


def test_a_ticket_the_tour_may_include_stays_with_a_note_to_check():
    exps = by_id(new_trip())
    ticket = exps[TICKET["id"]]
    assert ticket["user"] == {"status": "kept", "position": None} and ticket["status"] == "to_check"
    assert check(ticket, "overlap") == {
        "name": "overlap", "result": "warn",
        "detail": "May be the same visit as Colosseum Roman Forum and Palatine Hill Guided Tour: check whether the "
                  "tour includes entry"}
    assert exps[PIZZA["id"]]["user"]["status"] == "kept"                  # food, pinned on the Colosseum: kept
    assert check(exps[TOUR["id"]], "overlap")["result"] == "ok"


def test_restoring_a_same_place_alternative_makes_it_the_users_choice():
    trip_id = new_trip()["id"]
    r = client.post(f"/api/trips/{trip_id}/experiences/{PHOTO['id']}", json={"status": "kept"})
    assert r.status_code == 200, r.text
    photo = by_id(r.json())[PHOTO["id"]]
    assert photo["user"] == {"status": "kept", "position": None}
    assert check(photo, "overlap") == {"name": "overlap", "result": "warn", "detail": SAME_AS_TOUR}
    assert photo["status"] == "to_check"
    photo = by_id(client.post(f"/api/trips/{trip_id}/experiences/{PHOTO['id']}",
                              json={"status": "removed"}).json())[PHOTO["id"]]
    assert photo["user"] == {"status": "removed", "position": None}
    assert check(photo, "overlap")["detail"] == "removed by you"


def test_an_alternative_moves_up_when_its_twin_is_contradicted():
    prof = profile(start_date="2026-12-05", end_date="2026-12-07", pace="packed")
    exps = [place(TOUR), place(PIZZA), place(PHOTO)]
    for e in exps:
        e["verdict"] = {"id": e["id"], "verdict": "confirmed"}
    assert trips._keep_best_fit(prof, exps) == (1, 1)
    assert exps[2]["user"]["same_as"] == TOUR["id"]
    exps[0]["verdict"]["verdict"] = "contradicted"                       # after the verifier
    assert trips._keep_best_fit(prof, exps) == (0, 0)
    assert exps[0]["status"] == "rejected" and exps[2]["user"] == {"status": "kept", "position": None}
