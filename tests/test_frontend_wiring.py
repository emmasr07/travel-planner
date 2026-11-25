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


# --- roadmap step 5: the full flow and its failures ----------------------------------------------------------------

def test_the_list_page_keeps_polling_through_a_lost_connection():
    # A restart or a short outage: no answer (status 0) or a 5xx keeps the page and tries again; 404 is final.
    js = (FRONTEND / "js" / "experiences.js").read_text()
    assert "error.status === 0 || error.status >= 500" in js
    assert "Lost the connection to the server: trying again" in js
    load = js[js.index("async function load()"):js.index("function pollSearch()")]
    assert "lostConnection(error)" in load and "setTimeout(load, POLL_MS)" in load
    poll = js[js.index("function pollSearch()"):js.index("function searching()")]
    assert "lostConnection(error)" in poll and poll.count("pollSearch();") == 2     # re-armed after a lost poll too


def test_the_questionnaire_locks_back_while_it_sends_the_answers():
    # Back during the POST re-enabled Next, so a second trip (a second paid run in agents mode) could start.
    js = (FRONTEND / "js" / "plan.js").read_text()
    send = js[js.index("async function findExperiences("):]
    send = send[:send.index("\n  }\n")]
    assert "backBtn.disabled = true" in send and "backBtn.disabled = false" in send


def test_the_empty_list_says_when_everything_was_rejected():
    js = (FRONTEND / "js" / "experiences.js").read_text()
    empty = js[js.index("if (shown.length === 0)"):js.index("statusCard.hidden = true;")]
    assert "trip.experiences.length" in empty and "failed the checks" in empty


def test_the_access_code_is_asked_on_the_questionnaire_and_sent_in_a_header_only():
    html = (FRONTEND / "plan.html").read_text()
    field = re.search(r'<input[^>]*id="access-code"[^>]*>', html).group(0)
    assert 'type="password"' in field and "data-field" not in field      # never part of the saved answers
    assert 'id="try-demo"' in html
    api = (FRONTEND / "js" / "api.js").read_text()
    assert '"X-Access-Code"' in api and "tp.accessCode" in api
    plan = (FRONTEND / "js" / "plan.js").read_text()
    assert '"/api/trips?mode=demo"' in plan and "403" in plan and "429" in plan
    assert "accessCode" not in plan[plan.index("function toProfile("):plan.index("function showSubmitError(")]


def test_a_same_place_alternative_shows_why_it_was_left_out():
    # The note ("Same place as Colosseum Roman Forum and Palatine Hill Guided Tour: restore it ...") is the overlap
    # check's detail, worded by backend/checks.py: the card only shows it.
    js = (FRONTEND / "js" / "experiences.js").read_text()
    card = js[js.index("function removedCard("):js.index("function renderBudget(")]
    assert "e.user.same_as" in card and 'c.name === "overlap"' in card and "esc(" in card
