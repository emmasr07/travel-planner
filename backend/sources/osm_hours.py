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
