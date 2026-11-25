# Opening hours written as a simple sentence, in English or Italian, as a web page states them:
# "Ticket valid every day from 9 a.m. to 10 p.m.", "tutti i giorni dalle 9 alle 18",
# "Monday to Friday 9:00-17:00. Closed on Sundays.", "dal martedì alla domenica dalle 9 alle 19, chiuso il lunedì".
# Same answer as osm_hours.open_ranges: [(start_min, end_min)] on one local date, [] when closed, None when unclear.
# Every clause must be read in full: any other word (an exception, a date, a holiday, "last entry") makes the whole
# text unclear, so the hours check says so instead of guessing. Bare hours ("dalle 9 alle 18") are on the 24-hour
# clock; only an explicit a.m./p.m. or midnight may run past midnight.
import re
import unicodedata

_WEEKDAYS = [("monday", "mon", "lunedi"), ("tuesday", "tue", "tues", "martedi"), ("wednesday", "wed", "mercoledi"),
             ("thursday", "thu", "thur", "thurs", "giovedi"), ("friday", "fri", "venerdi"),
             ("saturday", "sat", "sabato", "sabati"), ("sunday", "sun", "domenica", "domeniche")]
_DAY_INDEX = {name: i for i, names in enumerate(_WEEKDAYS) for name in names}
_DAY = r"(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|mon|tues?|wed|thu(?:rs?)?|fri|sat" \
       r"|sun|lunedi|martedi|mercoledi|giovedi|venerdi|sabat[oi]|domenic(?:a|he))"
_ART = r"(?:(?:on|the|il|lo|la|i|le|di|nei|nelle)\s+)?"                    # "on Mondays", "il lunedì", "la domenica"
_EVERY = r"(?:every\s*day|daily|all\s+week|(?:7|seven)\s+days\s+a\s+week|tutti\s+i\s+giorni|ogni\s+giorno" \
         r"|tutta\s+la\s+settimana)"
_SPAN = rf"(?:(?:from|dal|dalla|da)\s+)?{_ART}{_DAY}\s*(?:-|to|through|until|till|al|alla|a|fino\s+al?)\s*{_ART}{_DAY}"
_LIST = rf"{_ART}{_DAY}(?:\s*(?:,|and|&|e|ed)\s*{_ART}{_DAY})*"
_DAYS = rf"(?:{_EVERY}|{_SPAN}|{_LIST})"
_TIME = r"(?:(?:ore\s+)?(?:\d{1,2}(?:[:.]\d{2})?(?:\s*[ap]m)?|noon|midday|midnight|mezzogiorno|mezzanotte))"
_RANGE = rf"(?:(?:from|dalle|dall|da)\s+)?{_TIME}\s*(?:-|to|until|till|alle|all|a)\s*{_TIME}"
_RANGES = rf"{_RANGE}(?:\s*(?:,|and|&|e|ed)\s*{_RANGE})*"
_LEAD = r"(?:(?:open|opens|opening\s+hours|hours|visiting\s+hours|tickets?\s+valid|valid|aperto|aperta|aperti|aperte" \
        r"|apertura|orario(?:\s+di\s+apertura)?|orari(?:\s+di\s+apertura)?|biglietto\s+valido|biglietti\s+validi)" \
        r"\s*:?\s*)?"
_SEP = r"\s*[,:]?\s*"
_OPEN = re.compile(rf"{_LEAD}(?P<days>{_DAYS}){_SEP}(?P<times>{_RANGES})|{_LEAD}(?P<times2>{_RANGES}){_SEP}"
                   rf"(?P<days2>{_DAYS})")
_CLOSED = re.compile(rf"(?:closed|chius[oa])\s+(?P<days>{_SPAN}|{_LIST})|(?P<days2>{_SPAN}|{_LIST})\s+(?:closed|chius[oa])")
_RANGE_PARTS = re.compile(r"(?:(?:from|dalle|dall|da)\s+)?(?P<a>(?:ore\s+)?[^\s-]+(?:\s*[ap]m)?)\s*"
                          r"(?:-|to|until|till|alle|all|a)\s*(?P<b>(?:ore\s+)?[^\s,&]+(?:\s*[ap]m)?)")
_TIME_PARTS = re.compile(r"(?:ore\s+)?(?:(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?(?:\s*(?P<half>[ap])m)?|(?P<word>\w+))")
_NAMED = {"noon": 720, "midday": 720, "mezzogiorno": 720, "midnight": 1440, "mezzanotte": 1440}
_AM_PM = re.compile(r"\b(\d{1,2}(?:[:.]\d{2})?)\s*([ap])\.?\s?m\b(\.?)", re.I)
# Clauses end at ";", a new line, a full stop that is not inside "9.30", or a comma before "closed"/"chiuso".
_CLAUSES = re.compile(r";|\n|(?<!\d)\.|\.(?!\d)|,\s*(?=(?:closed|chius[oa])\b)")


class _Unclear(Exception):
    pass


def open_ranges(text, day):
    """[(start_min, end_min)] when the place is open on this local date, [] when closed, None when unclear."""
    try:
        week = _read(text)
    except _Unclear:
        return None
    return sorted(week[day.weekday()])


def _read(text):
    """The seven weekdays' ranges. A later clause replaces the days it names; closed days win whatever the order."""
    week, closed, opened = {d: [] for d in range(7)}, set(), False
    for clause in _CLAUSES.split(_plain(text or "")):
        clause = clause.strip(" ,:")
        if not clause:
            continue
        m = _OPEN.fullmatch(clause)
        if m:
            ranges = _ranges(m["times"] or m["times2"])
            for d in _days(m["days"] or m["days2"]):
                week[d] = list(ranges)
            opened = True
            continue
        m = _CLOSED.fullmatch(clause)
        if m:
            closed |= _days(m["days"] or m["days2"])
            continue
        raise _Unclear
    if not opened:
        raise _Unclear
    for d in closed:
        week[d] = []
    return week


def _plain(text):
    """Lowercase, no accents, one kind of dash, and "9 a.m." as "9am" so its dots don't end a clause; the last dot
    still ends one when the sentence ends there ("...to 6 p.m. Closed on Mondays.")."""
    text = _AM_PM.sub(_am_pm, text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[‐-―−]", "-", text)                  # hyphens, en and em dashes, minus


def _am_pm(m):
    rest = m.string[m.end():]
    ends = m[3] and (not rest.strip() or re.match(r"\s+[A-Z]", rest))
    return f"{m[1]}{m[2].lower()}m" + ("." if ends else "")


def _days(text):
    text = text.strip()
    if re.fullmatch(_EVERY, text):
        return set(range(7))
    names = re.findall(rf"\b{_DAY}\b", text)                        # not the "thu" of "through"
    if re.fullmatch(_SPAN, text):
        a, b = _DAY_INDEX[_one(names[0])], _DAY_INDEX[_one(names[1])]
        return set(range(a, b + 1)) if a <= b else set(range(a, 7)) | set(range(0, b + 1))   # "Fri-Mon" wraps
    return {_DAY_INDEX[_one(n)] for n in names}


def _one(name):
    """'mondays' -> 'monday'; Italian plurals and short names are in the table."""
    return name if name in _DAY_INDEX else name[:-1]


def _ranges(text):
    out = []
    for m in _RANGE_PARTS.finditer(text):
        (start, _), (end, explicit) = _minutes(m["a"]), _minutes(m["b"])
        if start >= 1440:
            raise _Unclear
        if end <= start:
            if not explicit:                       # "from 9 to 6" on a 24-hour clock: unclear
                raise _Unclear
            end += 1440                            # "from 6 p.m. to 2 a.m.": closes after midnight
        out.append((start, end))
    if not out:
        raise _Unclear
    return out


def _minutes(text):
    """(minutes after midnight, explicit) for "9", "9.30", "9am", "10:15pm", "noon", "mezzanotte"."""
    m = _TIME_PARTS.fullmatch(text.strip())
    if not m:
        raise _Unclear
    if m["word"]:
        if m["word"] not in _NAMED:
            raise _Unclear
        return _NAMED[m["word"]], True
    h, mins, half = int(m["h"]), int(m["m"] or 0), m["half"]
    if mins > 59:
        raise _Unclear
    if half:
        if not 1 <= h <= 12:
            raise _Unclear
        h = (0 if h == 12 else h) + (12 if half == "p" else 0)
        return h * 60 + mins, True
    if h > 24 or (h == 24 and mins):
        raise _Unclear
    return h * 60 + mins, h == 24
