# The pages get their trip from the API, not from example data: mock-data.js is gone, and the questionnaire,
# the experience list and the brochure load js/api.js. The home page shows a static example without prices.
import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PAGES = ["index.html", "plan.html", "experiences.html", "brochure.html"]


@pytest.mark.parametrize("page", PAGES)
def test_no_page_loads_mock_data(page):
    assert "mock-data.js" not in (FRONTEND / page).read_text()


def test_mock_data_is_gone():
    assert not (FRONTEND / "js" / "mock-data.js").exists()


@pytest.mark.parametrize("page", ["plan.html", "experiences.html", "brochure.html"])
def test_api_pages_load_the_api_helper(page):
    html = (FRONTEND / page).read_text()
    assert '<script src="js/api.js" defer></script>' in html
    assert html.index("js/api.js") < html.index(f"js/{page.replace('.html', '.js')}")


def test_the_home_example_shows_no_prices():
    js = (FRONTEND / "js" / "index.js").read_text()
    assert not re.search(r"\bprice\b|€|checkedAt|budget", js)
    assert "mini-budget" not in (FRONTEND / "index.html").read_text()


@pytest.mark.parametrize("script", ["plan.js", "experiences.js", "brochure.js"])
def test_pages_call_the_api(script):
    assert "TP.api" in (FRONTEND / "js" / script).read_text()
