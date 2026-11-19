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


# --- session 3: Swap, Quick search and the brochure from the saved sublist --------------------------------------

def test_the_list_page_calls_swap_quick_search_and_pick():
    js = (FRONTEND / "js" / "experiences.js").read_text()
    for path in ('"/swap/', '"/quick"', '"/options/'):
        assert path in js, path
    assert not re.search(r'title="Coming soon" aria-label="Swap', js)
    html = (FRONTEND / "experiences.html").read_text()
    assert 'id="quick-search"' in html and 'id="search-panel"' in html


def test_the_brochure_page_shows_the_saved_sublist_and_downloads_the_pdf():
    js = (FRONTEND / "js" / "brochure.js").read_text()
    for piece in ("brochure.stops", "prices_note", "/brochure.pdf", "/brochure/map.png", "not_counted"):
        assert piece in js, piece
    assert "retrieved_at).sort" not in js and ".sort((a, b) => new Date(a)" not in js   # no checking-time sums here
    html = (FRONTEND / "brochure.html").read_text()
    assert re.search(r'<a [^>]*id="download-pdf"', html)
    assert not re.search(r'aria-disabled="true"[^>]*>Download PDF', html)
