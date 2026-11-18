# When a place is open on one local date, read from its OpenStreetMap opening_hours: a list of (start, end) in
# minutes after midnight (end past 1440 when it closes after midnight), [] when closed, None when too complex to
# read reliably. Most strings are real ones from data/samples (18 Nov 2026).
from datetime import date

import pytest

from backend.sources.osm_hours import has_holiday_rules, open_ranges

FRI, SAT, SUN, MON, TUE = (date(2026, 12, d) for d in (4, 5, 6, 7, 8))   # 4-8 Dec 2026
XMAS_EVE, XMAS = date(2026, 12, 24), date(2026, 12, 25)                  # Thu, Fri


def hm(text):
    h, m = map(int, text.split(":"))
    return h * 60 + m


def r(*pairs):
    return [(hm(a), hm(b) + (1440 if hm(b) <= hm(a) else 0)) for a, b in pairs]


@pytest.mark.parametrize("hours, day, expected", [
    ("Mo-Su 11:00-19:00", FRI, r(("11:00", "19:00"))),                             # Dona Ajuda
    ("Tu 09:00-18:00, Sa 09:00-18:00", SAT, r(("09:00", "18:00"))),                  # Feira da Ladra: additional rule
    ("Tu 09:00-18:00, Sa 09:00-18:00", FRI, []),
    ("Mo-Sa 07:00-14:00", SUN, []),                                                  # Mercado 31 de Janeiro
    ("Mo-Sa 07:00-14:00", MON, r(("07:00", "14:00"))),
    ("We-Sa 10:00-18:00; Jan 01,May 01,Dec 24-25 off", FRI, r(("10:00", "18:00"))),  # Museu do Dinheiro
    ("We-Sa 10:00-18:00; Jan 01,May 01,Dec 24-25 off", XMAS, []),
    ("We-Sa 10:00-18:00; Jan 01,May 01,Dec 24-25 off", date(2026, 5, 1), []),
    ("Tu-Su 10:00-18:00; Dec 24, Dec 31 10:00-14:00; Jan 01,May 01,Dec 25 off", XMAS_EVE, r(("10:00", "14:00"))),
    ("Tu-Su 10:00-18:00; Dec 24, Dec 31 10:00-14:00; Jan 01,May 01,Dec 25 off", MON, []),   # MUDE
    ("09:00-20:00; Oct 01-Mar 31: 09:00-17:00", FRI, r(("09:00", "17:00"))),        # Jardim Botânico, winter
    ("09:00-20:00; Oct 01-Mar 31: 09:00-17:00", date(2026, 8, 10), r(("09:00", "20:00"))),
    ("Su,We 10:00-00:00;Mo,Tu 10:00-23:00;Th-Sa 10:00-01:00", SAT, r(("10:00", "01:00"))),  # closes after midnight
    ("Su,We 10:00-00:00;Mo,Tu 10:00-23:00;Th-Sa 10:00-01:00", SUN, [(600, 1440)]),
    ("09:00-13:00,16:00-19:00", TUE, r(("09:00", "13:00"), ("16:00", "19:00"))),   # Museo Laboratorio, Matera
    ("Feb-Mar: Th-Tu 10:00-17:00; Apr-Oct: Th-Tu 10:00-19:00", FRI, []),             # Casa Noha: closed in Dec
    ("Feb-Mar: Th-Tu 10:00-17:00; Apr-Oct: Th-Tu 10:00-19:00", date(2026, 8, 10), r(("10:00", "19:00"))),
    ("Feb-Mar: Th-Tu 10:00-17:00; Apr-Oct: Th-Tu 10:00-19:00", date(2026, 8, 12), []),   # a Wednesday
    ("Mo-Fr 10:00-15:00; Sa-Su off", SAT, []),
    ("Mo-Fr 10:00-15:00; Sa-Su off", FRI, r(("10:00", "15:00"))),
    ("Mo 14:00-20:00; Tu-Su 09:00-20:00", MON, r(("14:00", "20:00"))),
    ("08:00-18:30; PH 10:00-17:30", FRI, r(("08:00", "18:30"))),                     # holiday rules are ignored
    ("Mo-Sa 10:00-12:00,14:00-17:00; PH off", SUN, []),
    ("Tu-Su 10:00-18:00; Jan 01,May 01,Jun 13,Dec 25 off; easter off", SAT, r(("10:00", "18:00"))),
    ("Mo-Su 10:00-18:00; Aug off", date(2026, 8, 10), []),
    ("Dec 01-24 10:00-20:00", XMAS_EVE, r(("10:00", "20:00"))),
    ("Dec 01-24 10:00-20:00", XMAS, []),
    ("24/7", SUN, [(0, 1440)]),
    ("Fr 12:00-20:00; Sa 11:00-20:00; Su 12:00-18:00", SAT, r(("11:00", "20:00"))),
])
def test_open_ranges(hours, day, expected):
    assert open_ranges(hours, day) == expected


@pytest.mark.parametrize("hours", [
    "07:30 - sunset",                                                                      # St. John's Church Gardens
    "week 1-13 Mo-Su 10:00-16:00; week 14-43 10:00-18:00; week 44-52 10:00-16:00",        # St Anne's Churchyard
    "Jan 01-Feb 15 08:30-16:30,Feb 16-Feb 29 08:30-17:30,Mar 01-Mar Su[4] 08:30-18:00",   # Victoria Embankment
    "Mo-Fr 09:00-17:00 || \"by appointment\"",
    '"by appointment"',
    "Mo-Fr",
    "10:00+",
    "",
    None,
])
def test_too_complex_is_not_guessed(hours):
    assert open_ranges(hours, FRI) is None


def test_holiday_rules_are_detected():
    assert has_holiday_rules("08:00-18:30; PH 10:00-17:30")
    assert has_holiday_rules("Tu-Su 10:00-18:00; easter off")
    assert not has_holiday_rules("Mo-Su 11:00-19:00")
