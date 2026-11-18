"""What code checks and the model does not: the delivery schema, the season against the trip dates, ages, the
arithmetic of prices against the budget, whether the quoted sentence is on the source page, and the five picks.

Every check returns {"name", "result": "ok" | "warn" | "fail" | "skip", "detail"}. status() turns checks and the verifier's
verdict into one of three states: verified, to_check (a person decides), rejected.
"""
import html
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from agents.researcher import DELIVER_EXPERIENCES

PICKS = 5
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "null": type(None)}


# --- the delivery, against the same schema the agent was given ---------------------------------------------------

def schema_errors(value, schema: dict = DELIVER_EXPERIENCES["input_schema"], path: str = "$") -> list[str]:
    """A small validator for the keywords used in agents/researcher.py; bool is not a number here."""
    types = schema.get("type")
    if types:
        types = types if isinstance(types, list) else [types]
        if isinstance(value, bool) or not any(isinstance(value, TYPES[t]) for t in types):
            return [f"{path}: expected {'/'.join(types)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} is not one of {schema['enum']}"]
    errors = []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.append(f"{path}: {value} out of range")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errors += [f"{path}: missing {k}" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in props:
                errors += schema_errors(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field {k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: {len(value)} items, at least {schema['minItems']}")
        if len(value) > schema.get("maxItems", len(value)):
            errors.append(f"{path}: {len(value)} items, at most {schema['maxItems']}")
        for i, item in enumerate(value):
            errors += schema_errors(item, schema.get("items", {}), f"{path}[{i}]")
    return errors


def delivery_errors(payload: dict) -> list[str]:
    """Sent back to the researcher as the tool result, so it fixes its own delivery."""
    errors = schema_errors(payload)
    if errors:
        return errors
    ids = [e["id"] for e in payload["experiences"]]
    errors += [f"id {i} appears twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for e in payload["experiences"]:
        for s in e["sources"]:
            if not re.match(r"^https?://", s["url"]):
                errors.append(f"{e['id']}: source url {s['url']!r} is not a web address")
            if len(s["quote"].split()) < 5:
                errors.append(f"{e['id']}: the quote must be a sentence copied from the page")
    return errors


# --- one experience against the profile ---------------------------------------------------------------------------

def trip_months(profile: dict) -> list[int]:
    start, end = date.fromisoformat(profile["start"]), date.fromisoformat(profile["end"])
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def group_cost(profile: dict, e: dict) -> float | None:
    """The price for the whole group in the trip currency, or None when it cannot be counted."""
    p = e["price"]
    if p["per"] == "free":
        return 0.0
    if p["amount"] is None or p["currency"].upper() != profile["currency"].upper():
        return None
    people = len(profile["travellers"])
    return round(p["amount"] * (people if p["per"] == "person" else 1), 2)


def check(profile: dict, e: dict, page: str | None) -> list[dict]:
    out = []

    def add(name, result, detail):
        out.append({"name": name, "result": result, "detail": detail})

    months, trip = e["months"], trip_months(profile)
    if not months or set(months) & set(trip):
        add("season", "ok", "all year" if not months else f"runs in {_months(months)}")
    else:
        add("season", "warn", f"runs in {_months(months)}, the trip is in {_months(trip)}")

    youngest = min(profile["travellers"], key=lambda t: t["age"])
    if e["min_age"] is None:
        add("age", "ok", "no minimum age stated")
    elif youngest["age"] < e["min_age"]:
        add("age", "fail", f"{youngest['name']} is {youngest['age']}, minimum age {e['min_age']}")
    else:
        add("age", "ok", f"minimum age {e['min_age']}")

    cost, p = group_cost(profile, e), e["price"]
    if cost is None and p["amount"] is None:
        add("price", "warn", "no source states a price")
    elif cost is None:
        add("price", "warn", f"price in {p['currency']}, not counted in a {profile['currency']} budget")
    elif cost > profile["budget"]:
        add("price", "fail", f"{cost:.0f} {profile['currency']} for the group, more than the whole budget")
    else:
        add("price", "ok", f"{cost:.0f} {profile['currency']} for the group")

    if page is None:
        add("source", "skip", "source page not read (demo mode)")
    elif page == "":
        add("source", "warn", "source page did not load")
    elif _norm(e["sources"][0]["quote"]) in page:
        add("source", "ok", "the quote is on the source page")
    else:
        add("source", "warn", "the quote is not on the source page")
    return out


def status(checks: list[dict], verdict: dict | None) -> str:
    results = {c["result"] for c in checks}
    v = (verdict or {}).get("verdict", "not_sure")
    if "fail" in results or v == "contradicted":
        return "rejected"
    if "warn" in results or v == "not_sure":
        return "to_check"
    return "verified"


# --- the source pages, read by code ------------------------------------------------------------------------------

def read_pages(urls: list[str]) -> dict[str, str]:
    """url -> normalised page text, "" when it does not load. Many sites refuse scripts: that is a warn, not a fail."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(urls, pool.map(_read, urls)))


def _read(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "trip-experiences/0.1 (student project)"})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception:
        return ""
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return _norm(html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def _months(ms: list[int]) -> str:
    return " ".join("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[m - 1] for m in ms)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


# --- the five picks ----------------------------------------------------------------------------------------------

def picks(profile: dict, experiences: list[dict], ids: list[str]) -> tuple[list[str], dict]:
    by_id = {e["id"]: e for e in experiences}
    errors = []
    if len(ids) != PICKS or len(set(ids)) != PICKS:
        errors.append(f"pick exactly {PICKS} different experiences, not {len(set(ids))}")
    errors += [f"{i} is not in the list" for i in ids if i not in by_id]
    errors += [f"{by_id[i]['name']} was rejected by the checks" for i in ids if by_id.get(i, {}).get("status") == "rejected"]
    chosen = [by_id[i] for i in ids if i in by_id]
    counted = [e["group_cost"] for e in chosen if e.get("group_cost") is not None]
    total = round(sum(counted), 2)
    totals = {"picked_cost": total, "budget": profile["budget"], "left": round(profile["budget"] - total, 2),
              "currency": profile["currency"], "not_counted": [e["name"] for e in chosen if e.get("group_cost") is None]}
    if total > profile["budget"]:
        errors.append(f"the five cost {total:.0f} {profile['currency']}, the budget is {profile['budget']:.0f}")
    return errors, totals
