# backend/checks.py `suggestion`: a price, clock time, date, "free" or opening/closing in a suggestion
# (best_time.reason, why_fits) that the record's sourced facts don't state gets a to_check note, never a rejection.
# The suggestion texts are the researcher's own words in trip rome-20261122-231553-9b61, and each record's price,
# hours and quotes are copied from that trip. Prices are fixed test examples (here: the ones that trip found).
import pytest

from backend import agents, checks
from tests.factories import GEO, VIATOR, profile
from tests.real_places import CAPITOLINE, NAVONA, PHOTO, PIZZA, TESTACCIO, TICKET, TOUR, TREVI, place

TRIP = profile(destination="rome", start_date="2026-12-05", end_date="2026-12-07", timezone="Europe/Rome",
               group_type="couple", group_size=2, budget={"amount": "300"})
NOTE = "suggestion mentions a fact not in the sources: "


def web(url, quote):
    return {"provider": "web", "url": url, "retrieved_at": "2026-11-22T23:18:00+01:00", "quote": quote}


def viator_hours(*slots):
    return {"text": f"Start times on 2026-12-05 to 2026-12-07: {', '.join(slots)}", "slots": list(slots),
            "source": VIATOR}


def best(start, reason):
    return {"slot": "morning", "start": start, "reason": reason, "kind": "suggestion"}


def why(text):
    return {"text": text, "kind": "suggestion"}


# The records' facts, as the trip holds them.
FACTS = {
    "capitoline-museums": {
        "price": {"amount": 16.5, "currency": "EUR", "per": "person", "label": "Full price for non-residents",
                  "source": web("https://www.museicapitolini.org/en/biglietti-e-prenotazioni/tickets-and-videoguides",
                                "Full price for non-residents € 16,50")},
        "opening_hours": {"text": "Mo-Su 09:30-19:30; Dec 24,31 09:30-14:00; Jan 01 off; May 01 off; Dec 25 off",
                          "slots": [], "source": GEO}},
    "colosseum-roman-forum-palatine-self-guided": {
        "price": {"amount": 18, "currency": "EUR", "per": "person", "label": "Full entry",
                  "source": web("https://colosseo.it/en/tickets/colosseum-roman-forum-palatine",
                                "Full entry: €18.00\nReduced fare: €2.00 for EU citizens aged 18-until the day of "
                                "the 25th birthday")},
        "opening_hours": None},
    "colosseum-forum-palatine-guided-tour": {
        "price": {"amount": 130, "currency": "EUR", "per": "person", "label": "Adult (13–99)", "source": VIATOR},
        "opening_hours": viator_hours("10:15", "11:15", "12:15", "13:15", "14:00")},
    "testaccio-market": {
        "price": {"amount": 0, "currency": "EUR", "per": "free", "label": None,
                  "source": web("https://www.viator.com/Rome-attractions/Testaccio-Market-Mercato-Di-Testaccio/"
                                "d511-a101875",
                                "You can browse the stands at the Testaccio Market for free on your own, but many "
                                "travelers visit as part of a food tour that includes tastings along with insights "
                                "into Rome’s gastronomic culture.")},
        "opening_hours": {"text": "Mo-Sa 07:00-15:30, Su closed", "slots": [], "source": GEO}},
    "trevi-fountain": {
        "price": {"amount": 2, "currency": "EUR", "per": "person", "label": None,
                  "source": web("https://www.turismoroma.it/en/places/trevi-fountain",
                                "From February the 2nd 2026, to enter the basin of the Trevi Fountain (the part "
                                "closest to the monument), tourists and non-residents must pay a ticket costing two "
                                "euros, valid every day from 9 a.m. to 10 p.m. (including the first Sunday of the "
                                "month).")},
        "opening_hours": {"text": "Ticket valid every day from 9 a.m. to 10 p.m.", "slots": [],
                          "source": web("https://www.turismoroma.it/en/places/trevi-fountain",
                                        "From February the 2nd 2026, to enter the basin of the Trevi Fountain (the "
                                        "part closest to the monument), tourists and non-residents must pay a ticket "
                                        "costing two euros, valid every day from 9 a.m. to 10 p.m. (including the "
                                        "first Sunday of the month).")}},
    "piazza-navona": {
        "price": {"amount": 0, "currency": "EUR", "per": "free", "label": None,
                  "source": web("https://www.walksinsiderome.com/blog/piazza-navona",
                                "Absolutely! Piazza Navona is open to everyone, free of charge, making it one of the "
                                "best spots in Rome to explore at your leisure.")},
        "opening_hours": None},
    "pizza-gelato-suppli-class-colosseum": {
        "price": {"amount": 99, "currency": "EUR", "per": "person", "label": "Adult (18–100)", "source": VIATOR},
        "opening_hours": viator_hours("10:00", "14:00", "18:00")},
    "private-colosseum-photoshoot-eidos": {
        "price": {"amount": 45, "currency": "EUR", "per": "person", "label": "Adult (13–99), when 2 book together",
                  "source": VIATOR},
        "opening_hours": viator_hours(*(checks.clock(m) for m in range(6 * 60 + 30, 19 * 60 + 31, 15)))},
}


def rome(rec, best_time=None, why_fits=None, **over):
    """A record of the Rome trip with its facts, its schedule, and the suggestion texts a test gives."""
    texts = {k: v for k, v in (("best_time", best_time), ("why_fits", why_fits)) if v}
    return place(rec, **{**FACTS[rec["id"]], **texts, **over})


def run(*exps):
    checks.check_all(TRIP, list(exps))
    return exps


def note(e):
    return next(c for c in e["checks"] if c["name"] == "suggestion")


# --- the slips in the Rome trip ----------------------------------------------------------------------------------

@pytest.mark.parametrize("texts, words", [
    ({"why_fits": why("Culture pick: ancient sculpture in the heart of Rome, free on Sunday 6 Dec.")},
     '"free", "6 Dec"'),
    ({"best_time": best("10:00", "Arrive soon after opening, as free first-Sunday entry makes it busy later.")},
     '"free"'),
], ids=["why_fits", "best_time"])
def test_capitoline_free_sunday_is_not_in_its_sources(texts, words):
    [e] = run(rome(CAPITOLINE, **texts))
    assert note(e) == {"name": "suggestion", "result": "warn", "detail": NOTE + words}


def test_capitoline_both_texts_name_each_word_once():
    [e] = run(rome(CAPITOLINE,
                   best_time=best("10:00", "Arrive soon after opening, as free first-Sunday entry makes it busy "
                                           "later."),
                   why_fits=why("Culture pick: ancient sculpture in the heart of Rome, free on Sunday 6 Dec.")))
    assert note(e)["detail"] == NOTE + '"free", "6 Dec"'


def test_colosseum_ticket_hours_from_a_search_snippet():
    [e] = run(rome(TICKET,
                   best_time=best("09:30", "The Forum and Palatine open at 9:00 per a search snippet, and winter "
                                           "closing is early, so start in the morning."),
                   why_fits=why("Culture pick on a lower budget than a guided tour, at your own pace.")))
    assert note(e)["result"] == "warn"
    assert note(e)["detail"] == NOTE + '"open", "9:00", "closing"'


def test_colosseum_tour_closing_time_of_another_record():
    """16:30 is Geoapify's closing time for the Colosseum, copied into the tour's doubts: not one of its facts."""
    [e] = run(rome(TOUR,
                   best_time=best("10:15", "First slot of the day, before the winter afternoon closing around "
                                           "16:30."),
                   why_fits=why("Culture is your top pick: Ancient Rome with a guide, as a couple, on your first "
                                "day.")))
    assert note(e)["detail"] == NOTE + '"16:30"'


# --- what the sources do state -----------------------------------------------------------------------------------

@pytest.mark.parametrize("rec, best_time, why_fits", [
    (TESTACCIO, best("13:15", "Street food stands are at their liveliest at lunch, and the market closes at 15:30."),
     why("You picked food: Roman street food at a local market, and it costs nothing to enter.")),
    (TREVI, best("18:00", "The fountain is lit up after dark and the ticket is valid until 22:00."),
     why("A romantic classic for a couple, and a cheap one at €2.")),
    (NAVONA, best("13:00", "A good stop after the Capitoline Museums, with cafes for a coffee; the square is also lit "
                           "in the evening."),
     why("Free Baroque sights and a lunch or coffee stop: easy on a balanced day.")),
    (PIZZA, best("14:00", "Afternoon class leaves the evening free for dinner in the area."),
     why("You picked food: make your own pizza, supplì and gelato near the Colosseum.")),
    (PHOTO, best("07:30", "Soft morning light and far fewer people around the Colosseum."),
     why("A keepsake for a couple: professional photos at the Colosseum for €45 each.")),
], ids=["closes at 15:30", "22:00 is 10 p.m.", "free square", "evening free", "€45"])
def test_facts_the_sources_state_pass(rec, best_time, why_fits):
    [e] = run(rome(rec, best_time=best_time, why_fits=why_fits))
    assert note(e) == {"name": "suggestion", "result": "ok",
                       "detail": "the suggestions mention no fact beyond the sources"}


def test_plain_suggestions_pass():
    [e] = run(rome(TOUR))      # the factories' "A test suggestion" and "You picked food"
    assert note(e)["result"] == "ok"


@pytest.mark.parametrize("text", ["Gluten-free options on the menu", "An open-air market", "Close to the Colosseum",
                                  "Feel free to linger", "Golden hour light in December falls late afternoon",
                                  "A short 40-minute shoot fits easily", "Free time afterwards for a walk"])
def test_words_that_are_not_such_facts(text):
    [e] = run(rome(TICKET, why_fits=why(text)))     # no hours, not free: any real slip would show
    assert note(e)["result"] == "ok", note(e)["detail"]


@pytest.mark.parametrize("text, words", [
    ("€36 for the two of you", '"€36"'),                     # sums are the code's job, not a source's fact
    ("Doors open at 8.30 am", '"open", "8.30 am"'),
    ("Gratis on 2 February", '"Gratis", "2 February"'),
    ("Last entry 2026-12-06 at 4 p.m.", '"2026-12-06", "4 p.m."'),
])
def test_other_ways_to_write_them(text, words):
    [e] = run(rome(TICKET, why_fits=why(text)))
    assert note(e)["detail"] == NOTE + words


def test_a_price_in_another_currency_is_not_the_sourced_one():
    [e] = run(rome(TREVI, why_fits=why("A cheap one at $2.")))
    assert note(e)["detail"] == NOTE + '"$2"'


def test_free_needs_a_source():
    """The price check already warns about a "free" with no source; a suggestion can't lean on it either."""
    unsourced = {**FACTS[NAVONA["id"]]["price"], "source": None}
    [e] = run(rome(NAVONA, why_fits=why("Free Baroque sights and a lunch or coffee stop: easy on a balanced day."),
                   price=unsourced))
    assert note(e)["detail"] == NOTE + '"Free"'


# --- what the note does ------------------------------------------------------------------------------------------

def test_the_note_makes_a_verified_item_to_check_never_rejected():
    clean, slipped = rome(TOUR), rome(TOUR, best_time=best("10:15", "First slot of the day, before the winter "
                                                                    "afternoon closing around 16:30."))
    for e in (clean, slipped):
        e["verdict"] = {"verdict": "confirmed"}
        run(e)
    assert clean["status"] == "verified"
    assert slipped["status"] == "to_check"


def test_the_time_reason_is_not_checked_once_the_user_picks_another_time():
    """The card then shows "You picked this time" instead of the reason; why_fits is still shown and checked."""
    moved = {"day": 1, "start": "11:15", "end": "13:45"}
    reason = best("10:15", "First slot of the day, before the winter afternoon closing around 16:30.")
    [e] = run(rome(TOUR, best_time=reason, schedule=moved))
    assert note(e)["result"] == "ok"
    [e] = run(rome(TOUR, best_time=reason, schedule=moved, why_fits=why("Free on Sunday 6 Dec.")))
    assert note(e)["detail"] == NOTE + '"Free", "6 Dec"'


# --- the researcher's instructions -------------------------------------------------------------------------------

def test_the_researcher_is_told_suggestions_use_only_sourced_facts():
    prompt = agents.prompt("researcher")
    rule = prompt[prompt.index("## Suggestions"):prompt.index("## Output")]
    assert "already in the record's fact fields" in rule
    for words in ("prices", "free days", "opening", "ages", "dates", "search snippet", "`doubts`"):
        assert words in rule, words
    assert "before 10:00" not in prompt     # an example clock time that is not a fact
