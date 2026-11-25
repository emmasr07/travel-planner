# backend/checks.py: the code checks of docs/backend-logic.md section 5, the final status per experience, and the
# delivery check (schema, duplicate ids, schedule inside the trip). Prices are fixed test examples.
import pytest

from backend import checks
from tests.factories import checked, experience, profile
from tests.real_places import (CAPITOLINE, LISBON, MATERA, NAVONA, NAVONA_PUBLIC_SPACE, PHOTO, PIZZA, ROME_PROFILE,
                               TICKET, TOUR, TREVI, TREVI_HOURS, place)

P = profile()   # Lisbon, Fri 4 - Sun 6 Dec 2026, 4 friends aged 25-34, EUR 250 per person, balanced pace


def run(exps, prof=P, pages=None):
    checks.check_all(prof, exps, pages)
    return exps


def result(e, name):
    return next(c for c in e["checks"] if c["name"] == name)


def res(e, name):
    return result(e, name)["result"]


def test_every_check_is_there_in_order():
    [e] = run([checked()])
    assert [c["name"] for c in e["checks"]] == ["schema", "source", "season", "age", "price", "hours", "closure",
                                                "suggestion", "overlap", "pace", "accessibility"]
    assert all(set(c) == {"name", "result", "detail"} for c in e["checks"])


# --- source -------------------------------------------------------------------------------------------------

WEB = {"provider": "web", "url": "https://example.org/hours", "retrieved_at": "2026-11-17T14:43:10+01:00",
       "quote": "Tours depart daily at 10:00 and 14:00."}


def with_web_quote():
    return checked(opening_hours={"text": "Daily 10:00 and 14:00", "slots": ["10:00", "14:00"], "source": WEB})


def test_source_skipped_when_pages_were_not_read():
    [e] = run([with_web_quote()])
    assert res(e, "source") == "skip"


def test_source_quote_on_the_page():
    page = "Welcome! Tours depart daily at 10:00 and 14:00. Book now."
    [e] = run([with_web_quote()], pages={WEB["url"]: page})
    assert res(e, "source") == "ok"


def test_source_quote_missing_or_page_not_loaded():
    [e] = run([with_web_quote()], pages={WEB["url"]: "Tours depart daily at 11:00."})
    assert res(e, "source") == "warn"
    [e] = run([with_web_quote()], pages={WEB["url"]: ""})
    assert res(e, "source") == "warn" and "did not load" in result(e, "source")["detail"]


def test_source_api_data_only_has_nothing_to_check():
    [e] = run([checked()], pages={})
    assert res(e, "source") == "skip"


# --- season -------------------------------------------------------------------------------------------------

def test_season():
    [all_year] = run([checked(months=[])])
    [summer] = run([checked(months=[4, 5, 6, 7, 8, 9, 10])])
    [winter] = run([checked(months=[11, 12, 1])])
    assert (res(all_year, "season"), res(summer, "season"), res(winter, "season")) == ("ok", "warn", "ok")


def test_season_uses_the_scheduled_date():
    trip = profile(start_date="2026-11-30", end_date="2026-12-02")   # day 1 in Nov, day 2 in Dec
    [e] = run([checked(months=[12], schedule={"day": 1, "start": "10:00", "end": "12:00"})], trip)
    assert res(e, "season") == "warn"
    [e] = run([checked(months=[12], schedule={"day": 2, "start": "10:00", "end": "12:00"})], trip)
    assert res(e, "season") == "ok"


# --- age ----------------------------------------------------------------------------------------------------

def test_age():
    assert res(run([checked(min_age=None)])[0], "age") == "ok"
    assert res(run([checked(min_age=18)])[0], "age") == "ok"                       # youngest is 25
    assert res(run([checked(min_age=30)])[0], "age") == "fail"
    young = profile(age_range="18-24")
    assert res(run([checked(min_age=21)], young)[0], "age") == "fail"


def test_age_for_families():
    family = profile(group_type="family", age_range="35-49")
    assert res(run([checked(min_age=12)], family)[0], "age") == "warn"             # youngest not known
    with_kids = profile(group_type="family", age_range="35-49", youngest_age=8)
    assert res(run([checked(min_age=12)], with_kids)[0], "age") == "fail"
    assert res(run([checked(min_age=6)], with_kids)[0], "age") == "ok"


# --- price --------------------------------------------------------------------------------------------------

def test_price():
    assert res(run([checked()])[0], "price") == "ok"                                # 35 per person
    assert res(run([checked(price={"amount": 300.0})])[0], "price") == "fail"       # more than 250 alone
    assert res(run([checked(price={"amount": None})])[0], "price") == "warn"        # no price
    assert res(run([checked(price={"amount": None, "per": "free"})])[0], "price") == "ok"


@pytest.mark.parametrize("price", [
    {"amount": 0, "per": "free", "source": None},
    {"amount": None, "per": "free", "source": None},
    {"amount": 0, "per": "person", "source": None},
])
def test_a_free_price_without_a_source_cannot_be_verified(price):
    [e] = run([checked(price=price)])
    assert result(e, "price") == {"name": "price", "result": "warn",
                                  "detail": "free, but no source says so: not verified"}
    assert checks.final_status(e["checks"], {"verdict": "confirmed"}) == "to_check"


def test_a_free_price_with_a_source_is_ok():
    [e] = run([checked(price={"amount": 0, "per": "free"})])                      # the factory's Viator source
    assert result(e, "price") == {"name": "price", "result": "ok", "detail": "free"}


def test_price_in_a_currency_that_was_not_converted():
    e = checked(price={"amount": 20.0, "currency": "GBP"})
    e["price"]["amount_eur"] = None
    [e] = run([e])
    assert res(e, "price") == "warn" and "GBP" in result(e, "price")["detail"]


def test_price_against_a_total_budget():
    total = profile(budget={"amount": "250", "currency": "EUR", "per": "total"})
    assert res(run([checked(price={"amount": 70.0})], total)[0], "price") == "fail"   # 70 x 4 = 280
    assert res(run([checked(price={"amount": 60.0})], total)[0], "price") == "ok"


# --- hours --------------------------------------------------------------------------------------------------

def at(day, start, end, **over):
    return checked(schedule={"day": day, "start": start, "end": end}, **over)


def test_hours_inside_and_outside_osm_hours():
    hours = {"opening_hours": {"text": "Mo-Sa 07:00-14:00", "slots": [], "source": {}}}
    assert res(run([at(1, "10:00", "12:00", **hours)])[0], "hours") == "ok"         # Friday
    assert res(run([at(1, "13:00", "15:00", **hours)])[0], "hours") == "warn"       # ends after closing
    assert res(run([at(3, "10:00", "12:00", **hours)])[0], "hours") == "warn"       # Sunday: closed
    assert "closed" in result(run([at(3, "10:00", "12:00", **hours)])[0], "hours")["detail"]


def test_hours_after_midnight():
    hours = {"opening_hours": {"text": "Th-Sa 10:00-01:00", "slots": [], "source": {}}}
    assert res(run([at(2, "23:00", "00:30", **hours)])[0], "hours") == "ok"


def test_hours_unknown_or_too_complex():
    assert res(run([checked(opening_hours=None)])[0], "hours") == "warn"
    complex_hours = {"opening_hours": {"text": "07:30 - sunset", "slots": [], "source": {}}}
    e = run([checked(**complex_hours)])[0]
    assert res(e, "hours") == "warn" and "too complex" in result(e, "hours")["detail"]


def test_hours_with_start_times():
    slots = {"opening_hours": {"text": "Daily 10:00 and 14:00", "slots": ["10:00", "14:00"], "source": {}}}
    assert res(run([at(1, "14:00", "16:00", **slots)])[0], "hours") == "ok"
    assert res(run([at(1, "11:00", "13:00", **slots)])[0], "hours") == "warn"


def test_hours_mention_ignored_holiday_rules():
    hours = {"opening_hours": {"text": "08:00-18:30; PH 10:00-17:30", "slots": [], "source": {}}}
    e = run([checked(**hours)])[0]
    assert res(e, "hours") == "ok" and "public-holiday" in result(e, "hours")["detail"]


# Viator's schedule text, as backend/sources/viator.py writes it: dated, times as Viator gives them (with seconds in
# production, 19 Nov 2026: Lisbon Banksy Museum).
VIATOR_SRC = {"provider": "viator", "url": "https://www.viator.com/tours/Lisbon/x",
              "retrieved_at": "2026-11-19T12:25:00+00:00", "quote": None}
BANKSY = ("Open 2026-12-04 11:00:00–20:00:00; 2026-12-05 10:00:00–20:00:00, 21:00:00–23:00:00; "
          "2026-12-06 10:00:00–19:00:00")


def viator_hours(text=BANKSY):
    return {"opening_hours": {"text": text, "slots": [], "source": VIATOR_SRC}}


def test_hours_read_viators_dated_hours_with_seconds():
    e = run([at(1, "11:00", "13:00", **viator_hours())])[0]                         # Fri 4 Dec
    assert result(e, "hours") == {"name": "hours", "result": "ok", "detail": "open 11:00-20:00 on Fri 4 Dec"}
    e = run([at(1, "10:00", "12:00", **viator_hours())])[0]
    assert res(e, "hours") == "warn" and "outside the opening hours on Fri 4 Dec (11:00-20:00)" in \
        result(e, "hours")["detail"]
    e = run([at(2, "21:30", "22:30", **viator_hours())])[0]                         # Sat: two ranges
    assert result(e, "hours")["detail"] == "open 10:00-20:00, 21:00-23:00 on Sat 5 Dec"


def test_hours_read_viators_dated_hours_without_seconds_too():
    e = run([at(3, "10:00", "12:00", **viator_hours("Open 2026-12-06 09:00–18:00"))])[0]
    assert result(e, "hours")["detail"] == "open 09:00-18:00 on Sun 6 Dec"


def test_hours_on_a_day_viator_does_not_list_are_unknown_not_closed():
    e = run([at(3, "10:00", "12:00", **viator_hours("Open 2026-12-04 11:00:00–20:00:00"))])[0]
    assert result(e, "hours") == {"name": "hours", "result": "warn",
                                  "detail": "no opening hours from Viator for Sun 6 Dec"}


# Hours written as a sentence, and public spaces: the real Trevi Fountain and Piazza Navona of trip
# rome-20261122-231553-9b61 (day 2 is Sun 6 Dec 2026).
ROME = profile(**ROME_PROFILE)


def trevi(start="18:00", end="18:30", **over):
    return place(TREVI, **{"opening_hours": TREVI_HOURS, "schedule": {"day": 2, "start": start, "end": end}, **over})


def navona(**over):
    return place(NAVONA, **{"opening_hours": None, **over})


def test_hours_read_the_real_trevi_sentence():
    [e] = run([trevi()], ROME)
    assert result(e, "hours") == {"name": "hours", "result": "ok", "detail": "open 09:00-22:00 on Sun 6 Dec"}
    [e] = run([trevi("21:45", "22:15")], ROME)
    assert result(e, "hours") == {"name": "hours", "result": "warn",
                                  "detail": "21:45-22:15 is outside the opening hours on Sun 6 Dec (09:00-22:00)"}


def test_hours_read_an_italian_sentence():
    hours = {"text": "tutti i giorni dalle 9 alle 18", "slots": [], "source": WEB}
    [e] = run([trevi("10:00", "10:30", opening_hours=hours)], ROME)
    assert result(e, "hours")["detail"] == "open 09:00-18:00 on Sun 6 Dec"
    [e] = run([trevi(opening_hours=hours)], ROME)                               # 18:00-18:30: it closes at 18
    assert res(e, "hours") == "warn"


def test_an_unclear_sentence_stays_to_check():
    hours = {"text": "Every day from 9 to 18, last entry at 17", "slots": [], "source": WEB}
    [e] = run([trevi(opening_hours=hours)], ROME)
    assert res(e, "hours") == "warn" and "too complex" in result(e, "hours")["detail"]


def test_a_public_space_with_no_hours_is_always_open():
    [e] = run([navona(public_space=NAVONA_PUBLIC_SPACE)], ROME)
    assert result(e, "hours") == {"name": "hours", "result": "ok", "detail": "public space, always open"}
    [e] = run([navona()], ROME)                                                 # no OSM tag: unknown, as before
    assert result(e, "hours") == {"name": "hours", "result": "warn", "detail": "no opening hours known"}


def test_a_public_space_with_hours_given_follows_them():
    hours = {"text": "Mo-Fr 09:00-10:00", "slots": [], "source": WEB}
    [e] = run([navona(public_space=NAVONA_PUBLIC_SPACE, opening_hours=hours)], ROME)
    assert res(e, "hours") == "warn" and "closed on Sun 6 Dec" in result(e, "hours")["detail"]


# --- closure: the source says the place is closed --------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Encerrado temporrariamente",                       # as OpenStreetMap spells it (Lisbon sample)
    "Encerrado temporariamente.", "A quinta está encerrada.", "Temporarily closed for renovation.",
    "Permanently CLOSED", "Chiuso per restauro", "Museo chiuso temporaneamente", "Vorübergehend geschlossen",
    "Fermé pour travaux", "Définitivement fermée", "Cerrado por obras", "Closed until March 2027.",
    "A museum of the city. Closed until further notice; see the website.",
])
def test_closure_fails_when_the_source_says_it_is_closed(text):
    [e] = run([checked(description=text)])
    assert res(e, "closure") == "fail" and e["status"] == "rejected"
    assert result(e, "closure")["detail"].startswith("the source says it is closed: ")


@pytest.mark.parametrize("text", [
    "Closed on Mondays and public holidays.", "Chiuso il lunedì", "Montags geschlossen", "Fermé le lundi et les jours fériés",
    "Cerrado los lunes", "Encerrado às segundas-feiras", "Encerrado aos domingos e feriados", "Closed at weekends.",
])
def test_closure_leaves_closed_days_to_the_hours_check(text):
    [e] = run([checked(description=text)])
    assert res(e, "closure") == "ok" and "hours" in result(e, "closure")["detail"]
    assert e["status"] != "rejected"


def test_closure_temporarily_wins_over_a_weekday():
    [e] = run([checked(description="Temporarily closed, reopening on Monday 5 January.")])
    assert res(e, "closure") == "fail"


@pytest.mark.parametrize("text", ["An enclosed garden with a fountain.", "La Ferme du Bonheur, a city farm.",
                                  "Visit the quinta and its vineyards.", "Open daily from 10:00."])
def test_closure_ignores_lookalike_words(text):
    [e] = run([checked(description=text)])
    assert res(e, "closure") == "ok"


def test_closure_without_a_description_is_skipped():
    [e] = run([checked(description=None)])
    assert res(e, "closure") == "skip"


def test_a_closed_place_takes_no_place_in_its_day():
    closed = checked("closed-one", description="Chiuso per restauro")
    other = checked("other", schedule={"day": 1, "start": "11:00", "end": "13:00"})   # overlaps the closed one
    run([closed, other])
    assert closed["status"] == "rejected" and res(other, "overlap") == "ok"


# --- overlap and pace ---------------------------------------------------------------------------------------

def test_overlap_between_kept_items_on_the_same_day():
    a = at(1, "10:00", "12:00", id="a", name="Tram 28")
    b = at(1, "11:00", "13:00", id="b", name="Fado dinner")
    c = at(2, "11:00", "13:00", id="c", name="Surf lesson")
    run([a, b, c])
    assert (res(a, "overlap"), res(b, "overlap"), res(c, "overlap")) == ("warn", "warn", "ok")
    assert "Fado dinner" in result(a, "overlap")["detail"] and "Tram 28" in result(b, "overlap")["detail"]


def test_touching_items_do_not_overlap():
    a, b = at(1, "10:00", "12:00", id="a"), at(1, "12:00", "14:00", id="b")
    run([a, b])
    assert (res(a, "overlap"), res(b, "overlap")) == ("ok", "ok")


def test_removed_and_rejected_items_are_left_out():
    a, b = at(1, "10:00", "12:00", id="a"), at(1, "11:00", "13:00", id="b", kept=False)
    c = at(1, "11:00", "13:00", id="c", min_age=99)                                   # fails the age check
    run([a, b, c])
    assert res(a, "overlap") == "ok"
    assert (res(b, "overlap"), res(b, "pace")) == ("skip", "skip")
    assert c["status"] == "rejected" and res(c, "overlap") == "skip"


def test_pace():
    day1 = [at(1, f"{h:02d}:00", f"{h + 1:02d}:00", id=f"e{h}") for h in (9, 11, 13, 15)]
    run(day1)                                                                          # 4 on day 1, balanced allows 3
    assert {res(e, "pace") for e in day1} == {"warn"}
    run(day1, profile(pace="packed"))
    assert {res(e, "pace") for e in day1} == {"ok"}
    run(day1[:2], profile(pace="chill"))
    assert {res(e, "pace") for e in day1[:2]} == {"ok"}


# --- the same place, the same visit (part of the overlap check) -----------------------------------------------
# Real names, coordinates and descriptions (tests/real_places.py): the Rome trip, the Matera and Lisbon samples.

def test_the_same_spot_in_the_same_category_is_the_same_place():
    mattress, ipogeo = place(MATERA["underground-mattress"]), place(MATERA["ipogeo-materasum"])
    assert checks.distance_m(mattress, ipogeo) < 10                    # Viator's meeting point and the OSM node
    assert checks.same_place(mattress, ipogeo) and checks.same_place(ipogeo, mattress)


def test_the_same_name_after_normalising_is_the_same_place_wherever_it_is():
    tickets = place(LISBON["jeronimos-entry-tickets"])
    again = place(LISBON["jeronimos-entry-tickets"], id="again", name="JERÓNIMOS Monastery: entry-tickets!",
                  location={"lat": 38.75, "lng": -9.10})
    assert checks.distance_m(tickets, again) > 5000
    assert checks.same_place(tickets, again)


@pytest.mark.parametrize("a, b", [(MATERA["casa-noha"], MATERA["musma"]),                         # two museums
                                  (LISBON["ministerium-cantina"], LISBON["nosolo-italia"])])      # two restaurants
def test_neighbours_are_not_the_same_place(a, b):
    a, b = place(a), place(b)
    assert 15 < checks.distance_m(a, b) < 30
    assert not checks.same_place(a, b)


def test_another_category_at_the_same_pin_is_not_the_same_place():
    tour, pizza = place(TOUR), place(PIZZA)          # Geoapify pinned the class "by Colosseum" on the Colosseum
    assert checks.distance_m(tour, pizza) == 0
    assert not checks.same_place(tour, pizza)


def test_a_tour_and_a_ticket_to_that_place_may_be_the_same_visit():
    tour, ticket = place(TOUR), place(TICKET)
    assert 400 < checks.distance_m(tour, ticket) < 600 and not checks.same_place(tour, ticket)
    # The tour's source says "skip-the-line" and "beyond standard entry tickets", never that entry is included.
    assert checks.same_visit(tour, ticket) == "unsure"
    assert checks.same_visit(ticket, tour) == "unsure"


def test_skip_the_line_alone_does_not_say_entry_is_included():
    tour = place(TOUR, description="Skip-the-line tour of the Colosseum.", tags=["Skip the line Tickets"])
    assert checks.same_visit(tour, place(TICKET)) == "unsure"


@pytest.mark.parametrize("text", [
    "Entry tickets to the Colosseum, Roman Forum and Palatine Hill are included.",
    "Includes entrance to the Colosseum and the Roman Forum.",
    "A small-group tour with entry tickets.",
    "Biglietto d'ingresso incluso.",
])
def test_a_tour_whose_source_says_entry_is_included_is_the_same_visit(text):
    assert checks.same_visit(place(TOUR, description=text), place(TICKET)) == "included"


@pytest.mark.parametrize("text", [
    "Admission not included.",
    "Entrance fees are not included: buy your ticket separately.",
    "Ingresso non incluso.",
])
def test_a_tour_whose_source_says_entry_is_not_included_needs_the_ticket(text):
    assert checks.same_visit(place(TOUR, description=text), place(TICKET)) is None


def test_only_a_tour_and_a_ticket_to_the_same_place_can_be_the_same_visit():
    tour, ticket = place(TOUR), place(TICKET)
    assert checks.same_visit(place(PHOTO), ticket) is None                    # a photoshoot is no tour
    assert checks.same_visit(place(PIZZA), ticket) is None                    # nor a cooking class
    assert checks.same_visit(tour, place(CAPITOLINE)) is None                 # no ticket, another place
    assert checks.same_visit(place(TICKET, id="ticket-2"), ticket) is None    # two tickets: same place, if anything


def test_twin_of_finds_the_first_same_place_or_included_visit():
    tour, pizza, photo = place(TOUR), place(PIZZA), place(PHOTO)
    assert checks.twin_of(photo, [pizza, tour]) is tour
    assert checks.twin_of(place(TICKET), [pizza, tour]) is None               # unsure: both stay
    included = place(TOUR, description="Entry tickets are included.")
    assert checks.twin_of(place(TICKET), [included]) is included


def test_overlap_says_same_place_on_the_later_item_only():
    tour, photo = place(TOUR), place(PHOTO)
    run([tour, photo])
    assert result(tour, "overlap") == {"name": "overlap", "result": "ok", "detail": "no overlap on day 1"}
    assert result(photo, "overlap") == {"name": "overlap", "result": "warn",
                                        "detail": "Same place as Colosseum Roman Forum and Palatine Hill Guided Tour"}
    assert photo["status"] == "to_check"


def test_overlap_says_the_ticket_may_be_the_same_visit():
    tour, ticket = place(TOUR), place(TICKET)
    run([tour, ticket])
    assert res(tour, "overlap") == "ok"
    assert result(ticket, "overlap")["detail"] == ("May be the same visit as Colosseum Roman Forum and Palatine Hill "
                                                   "Guided Tour: check whether the tour includes entry")


def test_overlap_says_the_same_visit_when_the_tour_includes_entry():
    ticket, tour = place(TICKET), place(TOUR, description="Entry tickets are included.")
    run([ticket, tour])                                                       # the ticket came first this time
    assert res(ticket, "overlap") == "ok"
    assert result(tour, "overlap")["detail"] == ("Same visit as Colosseum, Roman Forum and Palatine (official ticket): "
                                                 "its source says entry is included")


def test_overlap_says_both_a_time_clash_and_the_same_place():
    tour = place(TOUR)
    photo = place(PHOTO, schedule={"day": 1, "start": "12:00", "end": "13:30"})
    run([tour, photo])
    assert result(photo, "overlap")["detail"] == ("overlaps Colosseum Roman Forum and Palatine Hill Guided Tour "
                                                  "(10:15-12:45) on day 1; Same place as Colosseum Roman Forum and "
                                                  "Palatine Hill Guided Tour")


def test_a_removed_or_rejected_twin_says_nothing():
    tour, photo = place(TOUR, kept=False), place(PHOTO)
    run([tour, photo])
    assert res(photo, "overlap") == "ok"
    tour, photo = place(TOUR, min_age=99), place(PHOTO)                      # the tour fails the age check
    run([tour, photo])
    assert res(photo, "overlap") == "ok"


# --- accessibility ------------------------------------------------------------------------------------------

def test_accessibility():
    needs = profile(notes="one of us uses a wheelchair")
    assert res(run([checked()], needs)[0], "accessibility") == "warn"                 # unknown
    assert res(run([checked(accessibility={"wheelchair": "no"})], needs)[0], "accessibility") == "warn"
    assert res(run([checked(accessibility={"wheelchair": "yes"})], needs)[0], "accessibility") == "ok"
    assert res(run([checked()])[0], "accessibility") == "skip"                        # no need in the notes


# --- final status -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("results, verdict, status", [
    (["ok"], "confirmed", "verified"),
    (["ok", "skip"], "confirmed", "verified"),
    (["ok"], "not_sure", "to_check"),
    (["ok"], None, "to_check"),
    (["ok", "warn"], "confirmed", "to_check"),
    (["ok"], "contradicted", "rejected"),
    (["fail"], "confirmed", "rejected"),
])
def test_final_status(results, verdict, status):
    cs = [{"name": "x", "result": r, "detail": ""} for r in results]
    assert checks.final_status(cs, {"verdict": verdict} if verdict else None) == status


def test_recheck_keeps_schema_and_source_and_sets_status():
    e = with_web_quote()
    run([e], pages={WEB["url"]: "Tours depart daily at 10:00 and 14:00."})
    e["verdict"] = {"verdict": "confirmed"}
    e["schedule"] = {"day": 1, "start": "10:00", "end": "12:00"}
    checks.recheck(P, [e])
    assert res(e, "source") == "ok" and res(e, "schema") == "ok"
    assert e["status"] == "verified"       # every check ok or skip, and the verifier confirmed
    e["verdict"] = None
    checks.recheck(P, [e])
    assert e["status"] == "to_check"       # not verified yet


# --- the delivery -------------------------------------------------------------------------------------------

def delivery(*exps):
    return {"experiences": list(exps)}


def ten():
    return [experience(f"item-{i}") for i in range(10)]


def test_a_good_delivery_has_no_errors():
    assert checks.delivery_errors(delivery(*ten()), P) == []


def test_delivery_schema_errors_are_listed():
    bad = ten()
    bad[0]["price"]["amount_eur"] = 35.0                       # only the code fills amount_eur
    del bad[1]["booking_url"]
    errors = checks.delivery_errors(delivery(*bad), P)
    assert any("experiences/0/price/amount_eur" in e for e in errors)
    assert any("booking_url" in e for e in errors)


def test_a_delivery_holds_up_to_fifteen_never_padded():
    # Roadmap step 5: no minimum. Fewer real results is fine and an empty list is allowed; more than 15 is too long.
    assert checks.delivery_errors(delivery(experience()), P) == []
    assert checks.delivery_errors({"experiences": []}, P) == []
    too_many = {"experiences": [experience(f"e-{i}") for i in range(16)]}
    assert any("too long" in e for e in checks.delivery_errors(too_many, P))


WEB_PAGE = {"provider": "web", "url": "https://www.example.it/cooking-class", "retrieved_at": "2026-11-21T10:00:00+01:00",
            "quote": "Participants must be at least 18 years old."}


def test_a_min_age_no_source_can_state_goes_back_to_the_researcher():
    # Viator gives age bands for prices, not a minimum age, and Geoapify none: "Adult (18–99)" is not "18+".
    e = experience("pasta-class", min_age=18, price={"label": "Adult (18–99)"})        # Viator price, Geoapify place
    assert checks.min_age_errors(delivery(e)) == [
        "pasta-class: min_age 18 has no source. Only a web page you read can state a minimum age (Viator and "
        "Geoapify give none, and a price label's age band is not one): set it to null, or cite the page that "
        "states it."]


@pytest.mark.parametrize("over", [
    {"min_age": None},                                                            # not stated: null
    {"min_age": 18, "opening_hours": {"text": "Daily 10:00", "slots": ["10:00"], "source": WEB_PAGE}},
])
def test_a_null_min_age_or_one_from_a_web_page_is_fine(over):
    assert checks.min_age_errors(delivery(experience("pasta-class", **over))) == []


def test_delivery_duplicate_ids_and_schedule_outside_the_trip():
    items = ten()
    items[1]["id"] = items[0]["id"]
    items[2]["schedule"] = {"day": 4, "start": "10:00", "end": "12:00"}              # a 3-day trip
    items[3]["schedule"] = {"day": 1, "start": "10:00", "end": "13:00"}              # 120 min, not 180
    errors = checks.delivery_errors(delivery(*items), P)
    assert any("item-0" in e and "twice" in e for e in errors)
    assert any("item-2" in e and "day 4" in e for e in errors)
    assert any("item-3" in e and "end" in e for e in errors)
