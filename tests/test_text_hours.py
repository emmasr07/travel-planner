# backend/sources/text_hours.py: opening hours written as a simple sentence, in English or Italian. Same answer as
# osm_hours.open_ranges: [(start_min, end_min)] that local date, [] closed, None when anything is unclear.
from datetime import date

import pytest

from backend.sources import text_hours
from tests.real_places import TREVI_HOURS

FRI, SAT, SUN, MON = date(2026, 12, 4), date(2026, 12, 5), date(2026, 12, 6), date(2026, 12, 7)


def hm(a, b):
    """(start, end) in minutes from "HH:MM" strings."""
    h1, m1 = map(int, a.split(":"))
    h2, m2 = map(int, b.split(":"))
    return h1 * 60 + m1, h2 * 60 + m2


def test_trevi_ticket_text_reads_every_day_9_to_22():
    # The real text of trip rome-20261122-231553-9b61, copied from turismoroma.it.
    for day in (FRI, SAT, SUN, MON):
        assert text_hours.open_ranges(TREVI_HOURS["text"], day) == [hm("09:00", "22:00")]


@pytest.mark.parametrize("text, expected", [
    ("tutti i giorni dalle 9 alle 18", [hm("09:00", "18:00")]),
    ("Aperto tutti i giorni dalle 9.30 alle 19.30", [hm("09:30", "19:30")]),
    ("Orario: ogni giorno dalle ore 10 alle ore 17", [hm("10:00", "17:00")]),
    ("Open daily 10:00–18:00", [hm("10:00", "18:00")]),
    ("Opening hours: every day, 9am-5:30pm", [hm("09:00", "17:30")]),
    ("9 a.m. to 6 p.m. every day", [hm("09:00", "18:00")]),
    ("tutti i giorni dalle 9 alle 13 e dalle 15 alle 19", [hm("09:00", "13:00"), hm("15:00", "19:00")]),
    ("Every day from 6 p.m. to 2 a.m.", [(18 * 60, 26 * 60)]),
    ("Every day from noon to midnight", [hm("12:00", "24:00")]),
])
def test_every_day_sentences(text, expected):
    assert text_hours.open_ranges(text, SUN) == expected


def test_weekday_ranges_and_lists_in_english_and_italian():
    assert text_hours.open_ranges("Monday to Friday from 9 a.m. to 5 p.m.", FRI) == [hm("09:00", "17:00")]
    assert text_hours.open_ranges("Monday to Friday from 9 a.m. to 5 p.m.", SAT) == []      # not listed: closed
    assert text_hours.open_ranges("dal lunedì al venerdì dalle 8 alle 14", MON) == [hm("08:00", "14:00")]
    assert text_hours.open_ranges("dal lunedì al venerdì dalle 8 alle 14", SUN) == []
    assert text_hours.open_ranges("Saturday and Sunday 10:00-18:00", SAT) == [hm("10:00", "18:00")]
    assert text_hours.open_ranges("sabato e domenica dalle 10 alle 18", FRI) == []
    assert text_hours.open_ranges("Fri-Sun 11:00-23:00", SUN) == [hm("11:00", "23:00")]


def test_closed_days_win_over_every_day_whatever_the_order():
    for text in ("Open every day from 9 a.m. to 6 p.m. Closed on Mondays.",
                 "Chiuso il lunedì; tutti i giorni dalle 9 alle 18",
                 "dal martedì alla domenica dalle 9 alle 18, chiuso il lunedì"):
        assert text_hours.open_ranges(text, MON) == [], text
        assert text_hours.open_ranges(text, SUN) == [hm("09:00", "18:00")], text


def test_a_later_sentence_replaces_the_hours_of_the_days_it_names():
    text = "Every day from 9 to 18. Sunday from 10 to 14."
    assert text_hours.open_ranges(text, SAT) == [hm("09:00", "18:00")]
    assert text_hours.open_ranges(text, SUN) == [hm("10:00", "14:00")]


@pytest.mark.parametrize("text", [
    "",
    "Open from 9 to 18",                                          # which days?
    "Every day from 9 to 18, last entry at 17",
    "Ultimo ingresso alle 17. Tutti i giorni dalle 9 alle 18",
    "Every day from 9 to 6",                                      # 24-hour clock: ends before it starts
    "Closed every day from 13 to 15",
    "Every day from 9 a.m. to 10 p.m. except on 25 December",
    "Open every day except Christmas",
    "tutti i giorni dalle 9 alle 18 tranne i festivi",
    "Ticket valid every day from 9 a.m. to 10 p.m. (including the first Sunday of the month)",
    "The museum is open every day from 9 to 18",                  # a word the reader doesn't know
    "Every day from 9 a.m. to sunset",
    "Mo-Su 09:30-19:30; Dec 24,31 09:30-14:00; Jan 01 off",       # OpenStreetMap syntax, not a sentence
    "Closed on Mondays",                                           # no opening hours at all
    "Every day from 25 to 26",
])
def test_anything_unclear_is_none(text):
    assert text_hours.open_ranges(text, SUN) is None
