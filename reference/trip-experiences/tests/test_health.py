"""The server starts and answers /health: the one check the course asks for on day one."""
from fastapi.testclient import TestClient

from backend.main import app


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}
