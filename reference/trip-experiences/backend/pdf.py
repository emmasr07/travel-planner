"""The PDF of the five picks, written by code from the trip JSON: no model call, so nothing in it is new.

Each experience carries its source links, the quote, the verifier's verdict and the cost the code computed.
"""
from datetime import date
from pathlib import Path

from fpdf import FPDF

# A Unicode font if the machine has one; otherwise Helvetica, which only covers Latin-1.
FONTS = ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "C:/Windows/Fonts/arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
INK, GREY, BLUE, GREEN = (29, 29, 31), (110, 110, 115), (10, 100, 214), (74, 83, 64)
STATE = {"verified": "Verified", "to_check": "To check before booking", "rejected": "Rejected"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


class Plan(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(True, 18)
        font = next((f for f in FONTS if Path(f).exists()), None)
        self.body_font = "Body" if font else "Helvetica"
        if font:
            self.add_font("Body", "", font)
            self.add_font("Body", "B", font)

    def para(self, size, value, color=INK, bold=False, h=None, link=""):
        self.set_font(self.body_font, "B" if bold else "", size)
        self.set_text_color(*color)
        value = value if self.body_font == "Body" else value.encode("latin-1", "replace").decode("latin-1")
        self.multi_cell(0, h or size * 0.5, value, link=link, new_x="LMARGIN", new_y="NEXT")

    def footer(self):
        self.set_y(-12)
        self.set_font(self.body_font, "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 5, f"{self.page_no()}", align="R")


def write(trip: dict, path: Path) -> Path:
    p, t = trip["profile"], trip["totals"]
    chosen = [e for i in trip["picks"] for e in trip["experiences"] if e["id"] == i]
    doc = Plan()
    doc.add_page()
    doc.para(9, "Five experiences", GREY)
    doc.para(22, p["destination"], GREEN, bold=True, h=11)
    doc.para(11, f"{p['start']} to {p['end']}", BLUE)
    who = ", ".join(f"{x['name']} ({x['age']})" for x in p["travellers"])
    doc.para(10, who, GREY)
    doc.ln(3)
    line = f"The five cost {t['picked_cost']:.0f} {t['currency']} for the group, out of {t['budget']:.0f}: {t['left']:.0f} left."
    doc.para(11, line)
    if t["not_counted"]:
        doc.para(9, "Not counted, price missing or in another currency: " + ", ".join(t["not_counted"]), GREY)
    if trip.get("mode") == "demo":
        doc.para(9, "Demo mode: invented data, no model was called.", (179, 38, 30))

    for n, e in enumerate(chosen, 1):
        if doc.get_y() > doc.h - 75:  # an experience does not start at the foot of a page
            doc.add_page()
        doc.ln(5)
        doc.para(14, f"{n}. {e['name']}", bold=True, h=7)
        months = ", ".join(MONTHS[m - 1] for m in e["months"]) or "all year"
        hours = f" · {e['duration_hours']:g} h" if e["duration_hours"] else ""
        doc.para(9.5, f"{e['place']} · {e['category']} · {months}{hours}", GREEN)
        cost = "free" if e["group_cost"] == 0 else (f"{e['group_cost']:.0f} {p['currency']} for the group"
                                                   if e["group_cost"] is not None else "price not counted")
        doc.para(9.5, f"{STATE[e['status']]} · {cost}", BLUE if e["status"] == "verified" else GREY)
        doc.ln(1)
        doc.para(10, e["description"])
        doc.para(10, "Why for you: " + e["why_you"], GREY)
        for s in e["sources"]:
            doc.para(9, f"Source: {s['title']}", BLUE, link=s["url"])
            doc.para(8.5, s["url"], BLUE, link=s["url"])
            doc.para(9, f"\u201c{s['quote']}\u201d", GREY)
        v = e.get("verdict") or {}
        if v.get("note"):
            doc.para(9, f"Verifier: {v['verdict'].replace('_', ' ')}. {v['note']}", GREY)
        if e.get("doubts"):
            doc.para(9, "Not sure: " + e["doubts"], GREY)

    doc.ln(6)
    doc.para(8, f"Prepared on {date.today().isoformat()} from {trip['id']}.json. Prices and seasons are as the sources "
                "stated them on the day of the research: check them before booking.", GREY)
    doc.output(str(path))
    return path
