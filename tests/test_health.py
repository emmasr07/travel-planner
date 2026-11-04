# Checks the server is up: /health returns {"ok": true} and / serves the page.
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Travel Itinerary Planner" in r.text
