# The brochure, built by code from the kept experiences, with no AI (docs/ux-flow.md section 5).
#   sublist / build: the stops by day and local start time, each a copy of its facts (price with its label and
#     source, booking link), the reason for its time, its status and note; the totals from budget.py and the
#     "Prices checked on ..." note. trips.py saves this in the trip file.
#   map_image: one Geoapify static map of the numbered stops, in day colours; when there is no key or the call
#     fails, the pin plot (pins placed by their coordinates on a blank square) and the reason.
#   render / pdf: the PDF in our design (Inter, one blue accent), drawn from the saved sublist on download.
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fpdf import FPDF

from backend import budget, checks
from backend.sources import geoapify
from backend.sources.common import SourceError, now_iso

FONTS = Path(__file__).resolve().parent / "fonts"
HTTP = None                       # httpx client for the static map; None = geoapify's own (tests set a fake one)
ATTRIBUTION = "Powered by Geoapify · © OpenStreetMap contributors"
ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"
# The colours of frontend/css/styles.css: --ink, --ink-muted, --line, --surface-alt, --blue, --day-1 to --day-3.
INK, MUTED, LINE, SURFACE_ALT, BLUE, WHITE = "#1d1d1f", "#636366", "#e5e5ea", "#f5f5f7", "#0a66e8", "#ffffff"
DAY_COLOURS = ("#0a66e8", "#c75a00", "#0e7c72")
PROVIDERS = {"viator": "Viator", "geoapify": "Geoapify (OpenStreetMap)", "web": "Web page", "frankfurter": "Frankfurter"}
GROUPS = {"solo": "Solo", "couple": "Couple", "friends": "Friends", "family": "Family", "business": "Business"}
SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}
WEEKDAYS = "Mon Tue Wed Thu Fri Sat Sun".split()
MONTHS = checks.MONTHS


def day_colour(day):
    return DAY_COLOURS[(day - 1) % len(DAY_COLOURS)]


# --- the sublist (saved in the trip file) ----------------------------------------------------------------------

def sublist(trip):
    """Kept, non-rejected experiences by day, then local start time, numbered as stops on the map."""
    profile = trip["profile"]
    kept = sorted((e for e in trip["experiences"] if budget.counts(e)),
                  key=lambda e: (e["schedule"]["day"], checks.minutes(e["schedule"]["start"])))
    return [_stop(n, e, profile) for n, e in enumerate(kept, start=1)]


def _stop(n, e, profile):
    s, best, p, loc = e["schedule"], e.get("best_time") or {}, e["price"], e["location"]
    suggested = best.get("start") == s["start"] and best.get("reason")
    return {
        "id": e["id"], "stop": n, "day": s["day"], "date": checks.date_of(profile, s["day"]).isoformat(),
        "start": s["start"], "end": s["end"], "name": e["name"],
        "time_why": ({"text": best["reason"], "kind": "suggestion"} if suggested
                     else {"text": "You picked this time", "kind": "user"}),
        "price": {k: p.get(k) for k in ("amount", "currency", "per", "label", "amount_eur", "fx", "source")},
        "cost_eur": budget.item_cost(p, profile),
        "status": e["status"], "note": _note(e), "booking_url": e["booking_url"],
        "location": {"lat": loc["lat"], "lng": loc["lng"], "address": loc.get("address")},
    }


def _note(e):
    """What to check before booking: the warnings and a verdict that is not "confirmed" (same as the list page)."""
    if e["status"] != "to_check":
        return None
    items = [c["detail"] for c in e["checks"] if c["result"] == "warn"]
    v = e.get("verdict")
    if not v:
        items.append("the verifier has not checked it")
    elif v["verdict"] != "confirmed" and v.get("note"):
        items.append(v["note"])
    return " · ".join(items) or None


def build(trip):
    """The brochure as saved in the trip file. `map` is filled by trips.py (map_image); the PDF is drawn on download."""
    profile, stops = trip["profile"], sublist(trip)
    names = {e["id"]: e["name"] for e in trip["experiences"]}
    totals = budget.totals(profile, trip["experiences"])
    checked = [s["price"]["source"]["retrieved_at"] for s in stops
               if s["price"]["source"] and (s["price"]["amount"] is not None or s["price"]["per"] == "free")]
    oldest = min(checked, key=datetime.fromisoformat) if checked else None
    note = (f"Prices checked on {local_time(oldest, profile.get('timezone'))}. They may change before you book."
            if oldest else "No prices from a source yet: experiences without a price are not counted.")
    return {"created_at": now_iso(), "stops": stops, "totals": totals,
            "not_counted": [{"id": i, "name": names[i]} for i in totals["not_counted"]],
            "prices_checked_at": oldest, "prices_note": note, "map": None, "pdf": None}


def _in_zone(iso, tz):
    """The time in the destination's zone and its label; the recorded offset if that zone is not known here."""
    at = datetime.fromisoformat(iso)
    try:
        if tz:
            return at.astimezone(ZoneInfo(tz)), f"{tz.split('/')[-1].replace('_', ' ')} time"
    except (ZoneInfoNotFoundError, ValueError):
        pass
    offset = at.strftime("%z")
    return at, f"UTC{offset[:3]}:{offset[3:]}"


def local_time(iso, tz):
    """'17 Nov 2026, 13:42 (Lisbon time)'."""
    at, label = _in_zone(iso, tz)
    return f"{at.day} {MONTHS[at.month - 1]} {at.year}, {at:%H:%M} ({label})"


def checked_on(iso, tz):
    """'17 Nov, 13:42' in the destination's time, as the page shows it."""
    at, _ = _in_zone(iso, tz)
    return f"{at.day} {MONTHS[at.month - 1]}, {at:%H:%M}"


# --- the map -----------------------------------------------------------------------------------------------------

def map_image(stops):
    """(map block, PNG or None). The PNG is a Geoapify static map; without it the page and PDF draw the pin plot."""
    points = [{"lat": s["location"]["lat"], "lng": s["location"]["lng"], "text": str(s["stop"]),
               "color": day_colour(s["day"])} for s in stops]
    try:
        got = geoapify.static_map(points, client=HTTP)
    except SourceError as exc:
        return {"kind": "plot", "reason": str(exc)}, None
    return {"kind": "static", "source": got["source"], "attribution": ATTRIBUTION}, got["png"]


def plot_positions(stops):
    """Each stop's place in the pin plot, in percent of the square (10-90), from its coordinates."""
    lats, lngs = [s["location"]["lat"] for s in stops], [s["location"]["lng"] for s in stops]
    span_lat, span_lng = max(lats) - min(lats), max(lngs) - min(lngs)
    return [(10 + 80 * (s["location"]["lng"] - min(lngs)) / span_lng if span_lng else 50,
             10 + 80 * (max(lats) - s["location"]["lat"]) / span_lat if span_lat else 50) for s in stops]


# --- text the page and the PDF share ---------------------------------------------------------------------------------

def money(amount, currency="EUR"):
    """'€35', '€35.5', '£1,200' or '35 CHF': formatting only (the amount is rounded by budget.money)."""
    text = f"{budget.money(amount):,.2f}"
    text = text[:-3] if text.endswith(".00") else text.rstrip("0") if "." in text else text
    return f"{SYMBOLS[currency]}{text}" if currency in SYMBOLS else f"{text} {currency}"


def date_range(profile):
    a, b = date.fromisoformat(profile["start_date"]), date.fromisoformat(profile["end_date"])
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {MONTHS[b.month - 1]}"
    return f"{a.day} {MONTHS[a.month - 1]} – {b.day} {MONTHS[b.month - 1]}"


def day_title(stop_date, day):
    d = date.fromisoformat(stop_date)
    return f"Day {day} · {WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def group_label(profile):
    return "Solo" if profile["group_type"] == "solo" else f"{GROUPS[profile['group_type']]} ({profile['group_size']})"


def price_lines(stop, tz):
    """(price, caption): the price as the source states it, then its source and checked-at time."""
    p = stop["price"]
    source = p["source"]
    where = f"{PROVIDERS.get(source['provider'], source['provider'])} · checked {checked_on(source['retrieved_at'], tz)}" \
        if source else "no source"
    if p["per"] == "free":
        return "Free", where
    if p["amount"] is None or not source:
        return "No price yet", "No source states a price · not counted"
    label = f" · {p['label']}" if p["label"] else ""
    per = "per group" if p["per"] == "group" else "per person"
    if p["currency"] != "EUR" and p["amount_eur"] is not None and p["fx"]:
        where += f" · {money(p['amount_eur'])} at the {p['fx']['date']} rate (Frankfurter)"
    elif p["currency"] != "EUR" and p["amount_eur"] is None:
        where += " · not converted, not counted"
    return f"{money(p['amount'], p['currency'])}{label} · {per}", where


def status_line(stop):
    if stop["status"] == "verified":
        return "Verified"
    return f"To check: {stop['note']}" if stop["note"] else "To check"


# --- the PDF -----------------------------------------------------------------------------------------------------

PT = 0.3528          # mm per point
WIDTH = 174          # A4 width minus 18 mm margins


class Sheet(FPDF):
    """A4 in Inter. `drawn` keeps every string written, so tests can read the text (the TTF glyphs are encoded)."""

    def __init__(self):
        super().__init__(format="A4")
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(True, 18)
        self.add_font("Inter", "", FONTS / "Inter-Regular.ttf")
        self.add_font("Inter", "B", FONTS / "Inter-Bold.ttf")
        self.set_creator("Travel Planner")
        self.drawn = []

    def style(self, size, colour=INK, bold=False):
        self.set_font("Inter", "B" if bold else "", size)
        self.set_text_color(colour)

    def say(self, text, size, colour=INK, bold=False, w=0, x=None, link="", gap=1.35):
        """One paragraph at the current line (or at x), wrapped to w; moves below it."""
        self.drawn.append(text)
        self.style(size, colour, bold)
        if x is not None:
            self.set_x(x)
        self.multi_cell(w, size * PT * gap, text, align="L", link=link, new_x="LMARGIN", new_y="NEXT")

    def height(self, text, size, w, bold=False, gap=1.35):
        self.style(size, bold=bold)
        return self.multi_cell(w, size * PT * gap, text, align="L", dry_run=True, output="HEIGHT")

    def pin(self, cx, cy, number, colour, r=3.6):
        self.set_fill_color(colour)
        self.circle(x=cx, y=cy, radius=r, style="F")
        self.style(r * 2.4, WHITE, bold=True)
        self.set_xy(cx - r, cy - r)
        self.cell(2 * r, 2 * r, str(number), align="C")

    def dot(self, x, cy, colour, r=1.4):
        self.set_fill_color(colour)
        self.circle(x=x + r, y=cy, radius=r, style="F")

    def footer(self):
        self.set_y(-12)
        self.style(8, MUTED)
        self.cell(0, 4, "Travel Planner · prices and hours as the sources stated them: check them before you book")
        self.set_x(self.l_margin)
        self.cell(0, 4, f"{self.page_no()} / {{nb}}", align="R")


def pdf(trip, map_png=None):
    return bytes(render(trip, map_png).output())


def render(trip, map_png=None):
    p, b = trip["profile"], trip["brochure"]
    stops = b["stops"]
    doc = Sheet()
    doc.set_title(f"{p['destination']} · your trip brochure")
    doc.add_page()
    doc.say("Travel Planner", 12, bold=True)
    doc.ln(5)
    doc.say("Your trip brochure", 11, BLUE, bold=True)
    doc.say(p["destination"], 30, bold=True, gap=1.15)
    n = len(stops)
    doc.say(f"{date_range(p)} · {group_label(p)} · {n} {'experience' if n == 1 else 'experiences'}", 12, MUTED)
    if trip.get("mode") == "demo":
        doc.say("Demo data, not verified: sample places with fixed suggestions.", 9.5, MUTED)
    doc.ln(5)
    _overview(doc, p, b, stops, map_png)
    for day in sorted({s["day"] for s in stops}):
        _day(doc, p, [s for s in stops if s["day"] == day])
    return doc


def _overview(doc, profile, b, stops, map_png):
    """The map (left) beside the day legend and the total (right)."""
    top, side, size = doc.get_y(), doc.l_margin, 92
    if b["map"] and b["map"]["kind"] == "static" and map_png:
        doc.image(BytesIO(map_png), x=side, y=top, w=size, h=size)
        caption, link = b["map"]["attribution"], ATTRIBUTION_URL
    else:
        _plot(doc, stops, side, top, size)
        reason = (b["map"] or {}).get("reason") or "no map image"
        caption, link = f"Pins placed by their coordinates (no map image: {reason})", ""
    doc.set_xy(side, top + size + 1.5)
    doc.say(caption, 7.5, MUTED, w=size, link=link)
    left_end = doc.get_y()

    x, w = side + size + 8, WIDTH - size - 8
    doc.set_xy(x, top)
    doc.say("Your days", 12, bold=True, x=x, w=w)
    doc.ln(1)
    for day in sorted({s["day"] for s in stops}):
        mine = [s for s in stops if s["day"] == day]
        y = doc.get_y()
        doc.dot(x, y + 2.3, day_colour(day))
        doc.say(f"{day_title(mine[0]['date'], day)} · {len(mine)} {'stop' if len(mine) == 1 else 'stops'}",
                10, x=x + 5, w=w - 5)
    doc.ln(4)
    _total(doc, profile, b, x, w)
    doc.set_y(max(left_end, doc.get_y()) + 4)


def _plot(doc, stops, x, y, size):
    doc.set_fill_color(SURFACE_ALT)
    doc.rect(x, y, size, size, style="F", round_corners=True, corner_radius=4)
    for s, (px, py) in zip(stops, plot_positions(stops)):
        doc.pin(x + size * px / 100, y + size * py / 100, s["stop"], day_colour(s["day"]), r=3.2)


def _total(doc, profile, b, x, w):
    t = b["totals"]
    unit = f"total for {t['group_size']}" if t["per"] == "total" else "per person"
    top = doc.get_y()
    pad = 4
    body = [("Total", 10, MUTED, True), (money(t["used"]), 22, INK, True), (f"of {money(t['budget'])} {unit}", 10, MUTED, False)]
    if b["not_counted"]:
        names = ", ".join(n["name"] for n in b["not_counted"])
        body.append((f"Not counted: {names} (no price from a source)", 8.5, MUTED, False))
    body.append((b["prices_note"], 8.5, MUTED, False))
    h = sum(doc.height(text, size, w - 2 * pad, bold) for text, size, _, bold in body) + 2 * pad + len(body)
    doc.set_draw_color(LINE)
    doc.rect(x, top, w, h, style="D", round_corners=True, corner_radius=3)
    doc.set_xy(x + pad, top + pad)
    for text, size, colour, bold in body:
        doc.say(text, size, colour, bold, w=w - 2 * pad, x=x + pad)
        doc.ln(1)
        doc.set_x(x + pad)
    doc.set_y(top + h)


def _day(doc, profile, stops):
    if doc.will_page_break(12 + _stop_height(doc, profile, stops[0])):
        doc.add_page()
    doc.ln(5)
    day = stops[0]["day"]
    y = doc.get_y()
    doc.dot(doc.l_margin, y + 3.3, day_colour(day), r=1.7)
    doc.say(day_title(stops[0]["date"], day), 15, bold=True, x=doc.l_margin + 6)
    doc.ln(2)
    for s in stops:
        _stop_block(doc, profile, s)


PAD, PIN_COL, BOOK_COL = 4.5, 12, 30
TEXT_W = WIDTH - 2 * PAD - PIN_COL - BOOK_COL


def _stop_lines(profile, s):
    price, where = price_lines(s, profile.get("timezone"))
    return [(f"{s['start']} – {s['end']}", 10, BLUE, True), (s["name"], 13, INK, True),
            (s["time_why"]["text"], 10, MUTED, False), (price, 11, INK, True), (where, 8.5, MUTED, False),
            (status_line(s), 8.5, MUTED, False)]


def _stop_height(doc, profile, s):
    return sum(doc.height(t, size, TEXT_W, bold) + 0.6 for t, size, _, bold in _stop_lines(profile, s)) + 2 * PAD


def _stop_block(doc, profile, s):
    h = _stop_height(doc, profile, s)
    if doc.will_page_break(h + 3):
        doc.add_page()
    x, top = doc.l_margin, doc.get_y()
    doc.set_draw_color(LINE)
    doc.rect(x, top, WIDTH, h, style="D", round_corners=True, corner_radius=3)
    doc.pin(x + PAD + 4.5, top + h / 2, s["stop"], day_colour(s["day"]), r=4.5)
    doc.set_xy(x + PAD + PIN_COL, top + PAD)
    for text, size, colour, bold in _stop_lines(profile, s):
        doc.say(text, size, colour, bold, w=TEXT_W, x=x + PAD + PIN_COL)
        doc.ln(0.6)
    # Book: a blue pill linked to the booking page, its host under it.
    bx, by = x + WIDTH - PAD - 24, top + h / 2 - 6
    doc.set_fill_color(BLUE)
    doc.rect(bx, by, 24, 8.5, style="F", round_corners=True, corner_radius=4)
    doc.drawn.append("Book")
    doc.style(10.5, WHITE, bold=True)
    doc.set_xy(bx, by)
    doc.cell(24, 8.5, "Book", align="C", link=s["booking_url"])
    host = (urlsplit(s["booking_url"]).hostname or "").removeprefix("www.")
    doc.drawn.append(host)
    doc.style(7.5, MUTED)
    doc.set_xy(bx - 6, by + 9.5)
    doc.cell(36, 4, host, align="C", link=s["booking_url"])
    doc.set_xy(x, top + h + 3)
