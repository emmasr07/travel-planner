# The code's own check of facts that come from our API tools: the same record is fetched again through
# backend/sources/ (Viator: the product and its schedule; Geoapify: the stored URL, asked again with our key) and
# compared field by field. The verifier agent cannot do this (Viator's pages block it, Geoapify URLs need our key), so
# it checks only facts from web pages (prompts/verifier.md); combine() makes one verdict per experience from both.
# A difference is contradicted, with the fields; an answer that cannot be compared is not_sure, never contradicted.
import json

from backend.sources import geoapify, viator
from backend.sources.common import SourceError

API_PROVIDERS = ("viator", "geoapify")
SOURCED_FIELDS = ("price", "rating", "opening_hours", "location", "accessibility")   # fact fields with a source
NAMES = {"viator": "Viator", "geoapify": "Geoapify"}
RATING_TOLERANCE = 0.1      # stars, either way: Viator's average moves with each review
REVIEWS_GROWTH_PCT = 5      # new reviews between the research and the check; fewer reviews is a difference


def _source(e, field):
    value = e.get(field)
    return value.get("source") if isinstance(value, dict) else None


def _provider(e, field):
    return (_source(e, field) or {}).get("provider")


def has_web_facts(e):
    return any(_provider(e, f) == "web" for f in SOURCED_FIELDS)


def web_only(e):
    """The experience without its Viator and Geoapify facts: what the verifier agent checks. `e` is not changed."""
    return {k: v for k, v in e.items() if not (k in SOURCED_FIELDS and _provider(e, k) in API_PROVIDERS)}


def verdict(profile, e, *, client=None):
    """A verdict on the experience's Viator and Geoapify facts, fetched again; None when it has none."""
    by_url = {}
    for field in SOURCED_FIELDS:
        if _provider(e, field) in API_PROVIDERS:
            source = _source(e, field)
            by_url.setdefault((source["provider"], source["url"]), []).append(field)
    if not by_url:
        return None
    dates = (profile["start_date"], profile["end_date"])
    contested, lines, matched = [], [], []
    for (provider, url), fields in by_url.items():
        name = NAMES[provider]
        try:
            answer = _ask(provider, url, dates, client)
        except SourceError as err:
            answer = f"{name} did not answer ({err})"
        if isinstance(answer, str):                       # nothing to compare with: why
            lines.append(f"{', '.join(fields)} not compared: {answer}")
            continue
        for field in fields:
            result = _compare(provider, field, e[field], answer)
            if isinstance(result, str):
                lines.append(f"{field} not compared: {result}")
                continue
            close = [(path, mine, theirs) for path, mine, theirs, *within in result if within]
            differ = [(path, mine, theirs) for path, mine, theirs, *within in result if not within]
            lines += [f"{path}: record {_show(mine)}, {name} {_show(theirs)}, within tolerance"
                      for path, mine, theirs in close]
            if differ:
                contested += [path for path, _, _ in differ]
                lines += [f"{path}: record {_show(mine)}, {name} {_show(theirs)}" for path, mine, theirs in differ]
            else:
                matched.append(field)
    providers = " and ".join(NAMES[p] for p in dict.fromkeys(p for p, _ in by_url))
    if matched:
        lines.append(f"{', '.join(matched)} match")
    return {"id": e["id"],
            "verdict": "contradicted" if contested else "not_sure" if len(matched) < _count(by_url) else "confirmed",
            "url_read": next(iter(by_url))[1], "passage": "", "contested_fields": contested,
            "note": f"Checked by the code against {providers}, fetched again: {'; '.join(lines)}."}


def combine(id, parts):
    """One verdict from the code's and the verifier's: contradicted if either contradicts (with every contested field),
    confirmed if all confirm, else not_sure. url_read and passage come from the last part (the page the verifier read)."""
    parts = [p for p in parts if p]
    if not parts:
        return {"id": id, "verdict": "not_sure", "url_read": "", "passage": "", "contested_fields": [],
                "note": "No fact with a source to check."}
    verdicts = [p["verdict"] for p in parts]
    return {"id": id,
            "verdict": "contradicted" if "contradicted" in verdicts
            else "confirmed" if all(v == "confirmed" for v in verdicts) else "not_sure",
            "url_read": parts[-1]["url_read"], "passage": parts[-1]["passage"],
            "contested_fields": list(dict.fromkeys(f for p in parts for f in p["contested_fields"])),
            "note": " ".join(p["note"] for p in parts if p["note"])}


# --- asking again ---------------------------------------------------------------------------------------------------

def _ask(provider, url, dates, client):
    """The source's answer now, as a dict to compare with, or a string saying why there is none."""
    if provider == "viator":
        code = viator.product_code(url)
        if not code:
            return "no Viator product code in its link"
        facts = viator.product_facts(code, dates, client=client)
        if facts["status"] != "ACTIVE":
            return f"Viator lists the product as {facts['status']}"
        return facts
    facts = geoapify.answer_facts(url, geoapify.refetch(url, client=client))
    return facts if facts is not None else "no result in Geoapify's answer"


def _compare(provider, field, mine, answer):
    """[(path, record value, source value)] that differ, plus (path, record, source, "within") for a rating close
    enough; [] when all match; a string when it cannot be compared."""
    if provider == "viator":
        if field == "price":
            theirs = answer["price"]
            if theirs["amount"] is None:
                return "no from-price in Viator's schedule"
            if theirs["currency"] != mine.get("currency"):
                return f"Viator's schedule prices it in {theirs['currency']}, the record in {mine.get('currency')}"
            return _diff("price", mine, theirs, ("amount", "currency", "per", "label"))
        if field == "rating":
            return _rating(mine, answer["rating"] or {"value": None, "review_count": None})
        if field == "opening_hours":
            theirs = answer["opening_hours"] or {"text": None, "slots": None}
            same = mine.get("text") == theirs["text"] and list(mine.get("slots") or []) == list(theirs["slots"] or [])
            return [] if same else [("opening_hours", mine.get("text"), theirs["text"])]
        return "Viator gives no such field"
    if field == "location":
        if answer.get("lat") is None or answer.get("lng") is None:
            return "no coordinates in Geoapify's answer"
        mine_at, theirs_at = [mine.get("lat"), mine.get("lng")], [answer["lat"], answer["lng"]]
        same = all(_same(a, b, 6) for a, b in zip(mine_at, theirs_at))
        return [] if same else [("location", mine_at, theirs_at)]
    if field == "opening_hours":
        if "opening_hours" not in answer:
            return "this Geoapify answer has no opening hours"
        return [] if mine.get("text") == answer["opening_hours"] else [("opening_hours", mine.get("text"),
                                                                          answer["opening_hours"])]
    if field == "accessibility":
        if "wheelchair" not in answer:
            return "this Geoapify answer has no wheelchair access"
        return [] if mine.get("wheelchair") == answer["wheelchair"] else [
            ("accessibility.wheelchair", mine.get("wheelchair"), answer["wheelchair"])]
    return "Geoapify gives no such field"


def _diff(prefix, mine, theirs, keys):
    out = []
    for key in keys:
        a, b = mine.get(key), theirs.get(key)
        numbers = isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
        if not (_same(a, b, 2) if numbers else a == b):
            out.append((f"{prefix}.{key}", a, b))
    return out


def _rating(mine, theirs):
    """Rating within RATING_TOLERANCE stars and up to REVIEWS_GROWTH_PCT more reviews count as the same."""
    out = []
    a, b = mine.get("value"), theirs.get("value")
    if a != b:
        close = a is not None and b is not None and round(abs(float(a) - float(b)), 6) <= RATING_TOLERANCE
        out.append(("rating.value", a, b, "within") if close else ("rating.value", a, b))
    a, b = mine.get("review_count"), theirs.get("review_count")
    if a != b:
        close = a is not None and b is not None and a <= b and b * 100 <= a * (100 + REVIEWS_GROWTH_PCT)
        out.append(("rating.review_count", a, b, "within") if close else ("rating.review_count", a, b))
    return out


def _same(a, b, places):
    return a is not None and b is not None and round(float(a), places) == round(float(b), places)


def _count(by_url):
    return sum(len(fields) for fields in by_url.values())


def _show(value):
    return json.dumps(value, ensure_ascii=False)
