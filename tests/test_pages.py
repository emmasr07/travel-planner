# Checks the four frontend pages (home, questionnaire, experience list, brochure) are served with 200.
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

PAGES = ["/index.html", "/plan.html", "/experiences.html", "/brochure.html"]


@pytest.mark.parametrize("path", PAGES)
def test_page_returns_200(path):
    r = client.get(path)
    assert r.status_code == 200
