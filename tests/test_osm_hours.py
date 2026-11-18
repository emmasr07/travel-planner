# Months a place is open, read from its OpenStreetMap opening_hours. [] means all year or no months given;
# hours too complex to read reliably give ([], False). Most strings are real ones from the samples (18 Nov 2026).
import pytest

from backend.sources.osm_hours import months_open

SPRING_TO_AUTUMN = [2, 3, 4, 5, 6, 7, 8, 9, 10]


@pytest.mark.parametrize("hours, months", [
    # Seasonal: the months are in the hours.
    ("Feb-Mar: Th-Tu 10:00-17:00; Apr-Oct: Th-Tu 10:00-19:00", SPRING_TO_AUTUMN),   # Casa Noha, Matera
    ("Apr-Sep: Mo-Su 09:00-19:00", [4, 5, 6, 7, 8, 9]),
    ("Nov-Feb: Sa,Su 10:00-16:00", [1, 2, 11, 12]),                                    # wraps past December
    ("Jun 15-Sep 15 10:00-18:00", [6, 7, 8, 9]),
    ("Apr-Oct 10:00-18:00; Nov-Mar off", [4, 5, 6, 7, 8, 9, 10]),
    ("Mo-Su 10:00-18:00; Aug off", [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12]),
    ("Feb-Mar: Th-Tu 10:00-17:00; Apr-Oct: Th-Tu 10:00-19:00; Nov-Jan off", SPRING_TO_AUTUMN),
    ("feb-oct: 10:00-18:00", SPRING_TO_AUTUMN),
    ("Dec 01-24 10:00-20:00", [12]),                                                   # a Christmas market
    ("Dec 24-26 10:00-18:00", [12]),
    # All year: every month, or no month selector at all.
    ("Oct-Apr: Tu-Su 10:00-17:30; May-Sep: Tu-Su 10:00-18:30", []),                    # Torre de Belém
    ("Tu-Su 10:00-18:00; Dec 24, Dec 31 10:00-14:00; Jan 01,May 01,Dec 25 off", []),   # MUDE
    ("Tu-Su 10:00-18:00; Jan 01,May 01,Jun 13,Dec 25 off; easter off", []),
    ("Oct-May: Tu-Su 10:00-18:00; Jun-Sep: Tu-Su 10:00-19:00; Jan 01,May 01,Dec 25 off", []),
    ("09:00-20:00; Oct 01-Mar 31: 09:00-17:00", []),                                   # Jardim Botânico
    ("Apr-Oct: 10:00-18:00; Mo-Fr 09:00-17:00", []),                                   # later rule covers all dates
    ("Su,We 10:00-00:00;Mo,Tu 10:00-23:00;Th-Sa 10:00-01:00", []),
    ("Mo 14:00-20:00; Tu-Su 09:00-20:00", []),
    ("Mo-Fr 10:00-15:00; Sa-Su off", []),
    ("Mo-Sa 10:00-12:00,14:00-17:00; PH off", []),
    ("07:30 - sunset", []),
    ("24/7", []),
    ("PH off", []),
    (None, []),
    ("", []),
])
def test_months_read_reliably(hours, months):
    assert months_open(hours) == (months, True)


@pytest.mark.parametrize("hours", [
    "Jan 01-Feb 15 08:30-16:30,Feb 16-Feb 29 08:30-17:30,Mar 01-Mar Su[4] 08:30-18:00",  # Victoria Embankment
    "week 1-13 Mo-Su 10:00-16:00; week 14-43 10:00-18:00; week 44-52 10:00-16:00",       # St Anne's Churchyard
    "Mo-Fr 10:00-12:00, Jun-Aug Sa 10:00-12:00",   # a month after a comma, not at the start of a rule
    "Mo-Su[1] 10:00-12:00",
    "2026 Jan-Mar 10:00-12:00",
    "summer: 10:00-18:00",
    '"by appointment"',
    "Mo-Fr 09:00-17:00 || \"by appointment\"",
    "10:00-18:00; Nov 01-Mar 31 off",              # a season closed by dates, not whole months
    "off",
])
def test_hours_too_complex_are_not_guessed(hours):
    assert months_open(hours) == ([], False)
