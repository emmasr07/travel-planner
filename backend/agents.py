# The only file that talks to the AI (session 2: Claude Managed Agents), or stands in for it in demo mode.
#   MODE=demo (default): research = the matching sample in data/samples/<city>.json plus fixed suggestions;
#                        verification = fixed "not_sure" verdicts, clearly labelled demo. Free, no key, no network.
#   MODE=agents:         not built yet (session 2).
# Every function returns data in the agents' delivery shape (schemas/*.schema.json), so trips.py treats both alike.
import json
import os
import time
from pathlib import Path

from backend.checks import PACE_LIMIT, clock, minutes, trip_days

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"
DEMO_PAUSE_S = 0.6          # between demo step lines, so the page can show the loop; 0 in tests
MAX_ITEMS = 15
DEFAULT_VISIT_MIN = 120     # demo visit length when the source gives no duration
START_TIMES = {"chill": ["10:00", "15:00"], "balanced": ["10:00", "14:00", "17:00"],
               "packed": ["09:30", "12:00", "14:30", "17:00"]}
DEMO_REASON = "Demo suggestion: a fixed time slot, not chosen for this place"
DEMO_NOTE = "Demo mode: not verified. The verifier did not reopen the source; check it on the booking page."


class NotBuilt(Exception):
    """A feature planned for a later session."""


def mode():
    return "agents" if os.getenv("MODE", "demo").strip().lower() == "agents" else "demo"


# --- the samples --------------------------------------------------------------------------------------------

def _samples():
    """slug -> (destination name, experiences) for every data/samples/<slug>.json. The name comes from the file
    ("london" -> "London"): the places' own city can be wider ("Greater London")."""
    out = {}
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        exps = json.loads(path.read_text(encoding="utf-8"))["experiences"]
        out[path.stem] = (path.stem.replace("-", " ").title(), exps)
    return out


def demo_destinations():
    return sorted(city for city, _ in _samples().values())


def find_sample(destination):
    """(slug, city, experiences) for a destination like "Lisbon" or "london, England"; None without a sample."""
    wanted = destination.split(",")[0].strip().lower()
    for slug, (city, exps) in _samples().items():
        aliases = {slug, city.lower()} | {e["location"]["city"].lower() for e in exps}
        if wanted in aliases:
            return slug, city, exps
    return None


def sample_rates(destination):
    """currency -> fx block, from prices the sample builder already converted (Frankfurter), so demo stays offline."""
    found = find_sample(destination)
    rates = {}
    for e in (found[2] if found else []):
        fx = e["price"].get("fx")
        if fx:
            rates.setdefault(fx["from"], fx)
    return rates


# --- research and verification ------------------------------------------------------------------------------

def research(profile, step):
    """{"experiences": [...]} in the researcher's delivery shape."""
    if mode() != "demo":
        raise NotBuilt("agents mode is not built yet (session 2): set MODE=demo")
    slug, city, sample = find_sample(profile["destination"])
    step("researcher", f"demo mode, no AI: reading data/samples/{slug}.json ({len(sample)} places in {city})")
    _pause()
    interests = profile["interests"]
    matching = [e for e in sample if e["category"] in interests]
    days, pace = trip_days(profile), profile["pace"]
    chosen = matching[:min(days * PACE_LIMIT[pace], MAX_ITEMS)]
    if not matching:
        step("researcher", f"nothing in the {city} sample matches {', '.join(interests)}: "
                           "try widening your interests")
    else:
        step("researcher", f"{len(matching)} places match {', '.join(interests)}; proposing {len(chosen)} "
                           f"for {days} {'day' if days == 1 else 'days'} at a {pace} pace")
    _pause()
    delivered = [_with_demo_suggestions(e, i, days, pace) for i, e in enumerate(chosen)]
    if delivered:
        step("researcher", "fixed demo suggestions for the day, the time and why each one fits")
        _pause()
    return {"experiences": delivered}


def verify(profile, experiences, step):
    """{"verdicts": [...]} in the verifier's delivery shape."""
    if mode() != "demo":
        raise NotBuilt("agents mode is not built yet (session 2): set MODE=demo")
    step("verifier", "demo mode: the verifier did not run, so every experience is marked not sure")
    _pause()
    return {"verdicts": [{"id": e["id"], "verdict": "not_sure", "url_read": "", "passage": "",
                          "contested_fields": [], "note": DEMO_NOTE} for e in experiences]}


def _with_demo_suggestions(sample_item, i, days, pace):
    e = json.loads(json.dumps(sample_item))
    e["price"]["amount_eur"] = None              # as the agent delivers it: the code converts
    e["price"]["fx"] = None
    day, start = i % days + 1, START_TIMES[pace][i // days]
    length = e["duration_min"] or DEFAULT_VISIT_MIN
    e["best_time"] = {"slot": _slot(start), "start": start, "reason": DEMO_REASON, "kind": "suggestion"}
    e["why_fits"] = {"text": f"You picked {e['category']}", "kind": "suggestion"}
    e["schedule"] = {"day": day, "start": start, "end": clock(minutes(start) + length)}
    return e


def _slot(start):
    m = minutes(start)
    return "morning" if m < 12 * 60 else "midday" if m < 14 * 60 else "afternoon" if m < 17 * 60 else "evening"


def _pause():
    if DEMO_PAUSE_S:
        time.sleep(DEMO_PAUSE_S)
