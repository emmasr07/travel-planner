# Reads which months a place is open from its OpenStreetMap opening_hours string (e.g. "Apr-Oct: Tu-Su 10:00-18:00").
# Rules are read in order and a later rule overrides an earlier one, as in OSM. Only what can be read reliably is used:
# anything else returns ([], False) so the caller can say so. Syntax: https://wiki.openstreetmap.org/wiki/Key:opening_hours
import re

MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
ALL_MONTHS = set(range(1, 13))
SHORT_DAYS = 7  # a dated rule this short is a special day (Christmas Eve hours, a holiday), not a season

_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?![a-z])"
_ITEM = rf"{_MON}(?:\s+(\d{{1,2}}))?(?:\s*-\s*(?:{_MON}(?:\s+(\d{{1,2}}))?|(\d{{1,2}})(?![\d:])))?"
_SELECTOR = re.compile(rf"^\s*((?:{_ITEM})(?:\s*,\s*(?:{_ITEM}))*)\s*(?::|(?=\s)|$)", re.I)
_ITEM_RE = re.compile(_ITEM, re.I)
_ANY_MONTH = re.compile(rf"\b{_MON}", re.I)
_CLOSED = re.compile(r"\b(off|closed)\b", re.I)
_COMMENT = re.compile(r'"[^"]*"')
_IGNORED = re.compile(r"^(PH|SH|easter)\b", re.I)               # holiday rules: say nothing about months
_TIMES = re.compile(r"^(mo|tu|we|th|fr|sa|su)\b|^\d{1,2}:\d{2}|^24/7|^(sunrise|sunset|dawn|dusk)\b", re.I)


class _TooComplex(Exception):
    pass


def months_open(hours):
    """(months, reliable). months is [] when open all year or no months are given; ([], False) when the
    hours are too complex to read reliably."""
    if not hours or not hours.strip():
        return [], True
    try:
        return _read(hours)
    except _TooComplex:
        return [], False


def _read(hours):
    if "||" in hours or "[" in hours:          # fallback rules, nth weekday ("Su[4]")
        raise _TooComplex
    open_months, special_months = set(), set()
    for rule in (r.strip() for r in hours.split(";")):
        if not rule:
            continue
        if rule.startswith('"') or rule.lower() in ("off", "closed"):
            raise _TooComplex
        closed = bool(_CLOSED.search(_COMMENT.sub("", rule)))
        selector = _SELECTOR.match(rule)
        rest = rule[selector.end():] if selector else rule
        if _ANY_MONTH.search(_COMMENT.sub("", rest)):   # a month we did not read, e.g. after a comma
            raise _TooComplex
        if not selector:
            if _IGNORED.match(rule):
                continue
            if not _TIMES.match(rule):            # "week 1-13", a year, "summer", free text
                raise _TooComplex
            if not closed:                        # no date selector: the rule covers every day of the year
                open_months = set(ALL_MONTHS)
            continue
        for months, short, dated in _items(selector.group(1)):
            if closed:
                if not dated:
                    open_months -= months         # "Nov-Mar off"
                elif not short:
                    raise _TooComplex             # a season closed by dates ("Nov 01-Mar 31 off")
            elif short:
                special_months |= months          # "Dec 24, Dec 31 10:00-14:00"
            else:
                open_months |= months
    months = open_months or special_months
    return ([] if months == ALL_MONTHS else sorted(months)), True


def _items(selector):
    """(months covered, is a short date window, has days) for each item of a month/date selector."""
    for m in _ITEM_RE.finditer(selector):
        mon1, day1, mon2, day2, day_only = m.groups()
        start = MONTH_NAMES.index(mon1.lower()) + 1
        end = MONTH_NAMES.index(mon2.lower()) + 1 if mon2 else start
        dated = bool(day1 or day2 or day_only)
        if day_only:                                   # "Dec 24-26"
            short = int(day_only) - int(day1 or 1) + 1 <= SHORT_DAYS
        elif mon2 is None:                             # "Dec 24" or "Aug"
            short = bool(day1)
        else:                                          # "Feb 16-Feb 29", "Jun 15-Sep 15", "Apr-Oct"
            short = start == end and day1 and day2 and int(day2) - int(day1) + 1 <= SHORT_DAYS
        yield _span(start, end), bool(short), dated


def _span(start, end):
    if start <= end:
        return set(range(start, end + 1))
    return set(range(start, 13)) | set(range(1, end + 1))   # wraps past December: "Oct-Apr"


# --- Opening hours on one local date --------------------------------------------------------------------------
# open_ranges() reads a common subset of the syntax: rules split by ";" (a later rule overrides the days it names),
# additional rules after "HH:MM," (they add, not override), month/date selectors ("Apr-Oct:", "Oct 01-Mar 31:",
# "Dec 24-25", "Jan 01,May 01"), weekdays ("Mo-Fr", "Th-Tu", "Sa,Su"), several time ranges, "off"/"closed" and
# "24/7". Public-holiday rules (PH, SH, easter) are skipped: we don't know the holidays (see has_holiday_rules).
# Anything else (sunset, week numbers, "Su[4]", comments, "||", "10:00+") gives None.

DAY_NAMES = ["mo", "tu", "we", "th", "fr", "sa", "su"]
_DAY = r"(mo|tu|we|th|fr|sa|su)(?![a-z])"
_D = r"(\d{1,2})(?!\d)(?!:\d)"   # a day of the month, not the hour of "10:00"
_DATE_ITEM = re.compile(rf"\s*{_MON}(?:\s+{_D})?(?:\s*-\s*(?:{_MON}(?:\s+{_D})?|{_D}))?", re.I)
_DAY_ITEM = re.compile(rf"\s*{_DAY}(?:\s*-\s*{_DAY})?", re.I)
_LIST_SEP = re.compile(r"\s*,\s*")
_COLON = re.compile(r"\s*:")
_HOLIDAY = re.compile(r"\s*(PH|SH|easter)(?![a-z])", re.I)
_TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_ADDITIONAL = re.compile(r"(?<=\d\d:\d\d)\s*,\s*(?=[A-Za-z])")   # "Tu 09:00-18:00, Sa 09:00-18:00"
_HOLIDAY_ANYWHERE = re.compile(r"\b(PH|SH|easter)\b", re.I)


def has_holiday_rules(hours):
    return bool(hours and _HOLIDAY_ANYWHERE.search(hours))


def open_ranges(hours, day):
    """[(start_min, end_min)] when the place is open on this local date, [] when closed, None when too complex."""
    if not hours or not hours.strip():
        return None
    if '"' in hours or "||" in hours or "[" in hours:
        return None
    ranges = []
    try:
        for rule in (r.strip() for r in hours.split(";")):
            for i, part in enumerate(_ADDITIONAL.split(rule) if rule else []):
                parsed = _parse_rule(part.strip())
                if parsed is None:                      # a holiday rule
                    continue
                dates, days, times = parsed
                if _matches_date(dates, day) and (days is None or day.weekday() in days):
                    ranges = ranges + times if i else list(times)
    except _TooComplex:
        return None
    return sorted(ranges)


def _parse_rule(rule):
    """(date items, weekday set or None, time ranges), or None for a holiday rule we skip."""
    pos, dates = 0, []
    m = _DATE_ITEM.match(rule, pos)
    while m:
        dates.append(_date_span(*m.groups()))
        pos = m.end()
        sep = _LIST_SEP.match(rule, pos)
        m = _DATE_ITEM.match(rule, sep.end()) if sep else None
        if m:
            pos = m.start()
    if dates:
        colon = _COLON.match(rule, pos)
        pos = colon.end() if colon else pos
    if _HOLIDAY.match(rule, pos):
        return None
    days = None
    m = _DAY_ITEM.match(rule, pos)
    while m:
        days = (days or set()) | _day_span(*m.groups())
        pos = m.end()
        sep = _LIST_SEP.match(rule, pos)
        m = _DAY_ITEM.match(rule, sep.end()) if sep else None
    rest = rule[pos:].strip()
    if rest.lower() in ("off", "closed"):
        times = []
    elif rest == "24/7":
        times = [(0, 1440)]
    elif rest:
        times = _times(rest)
    else:
        raise _TooComplex                                # a selector without times
    return dates, days, times


def _times(text):
    out = []
    for piece in _LIST_SEP.split(text):
        m = _TIME_RANGE.fullmatch(piece.strip())
        if not m:
            raise _TooComplex
        h1, m1, h2, m2 = map(int, m.groups())
        if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
            raise _TooComplex
        start, end = h1 * 60 + m1, h2 * 60 + m2
        out.append((start, end + 1440 if end <= start else end))   # "10:00-01:00" closes after midnight
    return out


def _date_span(mon1, day1, mon2, day2, day_only):
    start_m = MONTH_NAMES.index(mon1.lower()) + 1
    end_m = MONTH_NAMES.index(mon2.lower()) + 1 if mon2 else start_m
    start = (start_m, int(day1) if day1 else 1)
    if day_only:
        end = (start_m, int(day_only))
    elif mon2:
        end = (end_m, int(day2) if day2 else 31)
    else:
        end = (start_m, int(day1)) if day1 else (start_m, 31)
    return start, end


def _matches_date(dates, day):
    if not dates:
        return True
    key = (day.month, day.day)
    return any((start <= key <= end) if start <= end else (key >= start or key <= end) for start, end in dates)


def _day_span(first, last):
    a = DAY_NAMES.index(first.lower())
    b = DAY_NAMES.index(last.lower()) if last else a
    return set(range(a, b + 1)) if a <= b else set(range(a, 7)) | set(range(0, b + 1))   # "Th-Tu" wraps
