"""The whole flow in demo mode: profile -> research -> checks -> verifier -> five picks -> PDF and JSON on disk."""
import time

from fastapi.testclient import TestClient

from backend import llm, main

PROFILE = {"destination": "Seychelles", "start": "2027-04-10", "end": "2027-04-20", "budget": 1500, "currency": "EUR",
           "travellers": [{"name": "Parent 1", "age": 50}, {"name": "Parent 2", "age": 48}, {"name": "Teen", "age": 15}],
           "interests": ["nature"]}


def test_demo_flow(monkeypatch):
    monkeypatch.setenv("MODE", "demo")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = TestClient(main.app)
    trip_id = c.post("/api/trips", json=PROFILE).json()["id"]
    for _ in range(100):
        trip = c.get(f"/api/trips/{trip_id}").json()
        if trip["status"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert trip["status"] == "ready", trip["error"]
    states = {e["id"]: e["status"] for e in trip["experiences"]}
    assert states["vallee-de-mai"] == "verified"
    assert states["creole-cooking"] == "to_check" and states["discover-scuba"] == "rejected"
    assert c.post(f"/api/trips/{trip_id}/picks", json={"ids": ["discover-scuba"]}).status_code == 400
    five = ["vallee-de-mai", "anse-source-dargent", "sainte-anne-snorkel", "curieuse-tortoises", "botanical-garden"]
    done = c.post(f"/api/trips/{trip_id}/picks", json={"ids": five}).json()
    assert done["status"] == "done" and done["totals"]["left"] == 711
    pdf = c.get(f"/api/trips/{trip_id}/pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert (main.TRIPS / f"{trip_id}.json").exists()
    (main.TRIPS / f"{trip_id}.json").unlink()
    (main.TRIPS / f"{trip_id}.pdf").unlink()
