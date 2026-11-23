# Going online: who may start a paid agents run, and how many a day. One job, nothing else.
# ACCESS_CODE: the code the page sends in the X-Access-Code header for an agents trip, swap or quick search. With no
# code set on the server, every agents run is refused (403): nothing that costs money runs by accident.
# DAILY_AGENT_LIMIT (default 10): agents runs a day (a new trip, a swap, a quick search each count 1, once accepted),
# counted in data/agent-usage.json for the UTC day; over it, 429. A demo trip needs neither and never counts.
# The code is only compared here: never written to a trip file, a log or an answer.
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.agents import NotReady

ROOT = Path(__file__).resolve().parent.parent
USAGE_PATH = ROOT / "data" / "agent-usage.json"
DEFAULT_LIMIT = 10
_LOCK = threading.Lock()


class Forbidden(Exception):
    """403: no access code, a wrong one, or none set on the server."""


class LimitReached(Exception):
    """429: today's agents runs are used up."""


def require_code(given):
    expected = os.getenv("ACCESS_CODE", "").strip()
    if not expected:
        raise Forbidden("the AI agents are locked on this server (no access code is set): plan a demo trip instead")
    if not given or not secrets.compare_digest(given.strip().encode("utf-8"), expected.encode("utf-8")):
        raise Forbidden("the AI agents need the access code: ask us for it, or plan a demo trip instead")


def daily_limit():
    value = os.getenv("DAILY_AGENT_LIMIT", "").strip()
    if not value:
        return DEFAULT_LIMIT
    if not re.fullmatch(r"[0-9]+", value):
        raise NotReady("agents mode is not set up: DAILY_AGENT_LIMIT must be a whole number, 0 or more "
                       "(see .env.example)")
    return int(value)


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def usage():
    """{"date", "count"} for today (UTC). A missing or damaged file, or another day's, counts from 0."""
    today = _today()
    try:
        data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    count = data.get("count") if isinstance(data, dict) and data.get("date") == today else 0
    return {"date": today, "count": count if isinstance(count, int) and count >= 0 else 0}


def count_run():
    """Counts one more agents run today, or raises LimitReached when today's are used up. Returns how many are left."""
    limit = daily_limit()
    with _LOCK:
        now = usage()
        if now["count"] >= limit:
            if limit == 0:
                raise LimitReached("the AI agents are switched off on this server today: plan a demo trip instead")
            raise LimitReached(f"today's {limit} AI agent runs are used up: try again tomorrow (the count restarts at "
                               "midnight UTC), or plan a demo trip instead")
        now["count"] += 1
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = USAGE_PATH.with_name(USAGE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(now), encoding="utf-8")
        tmp.replace(USAGE_PATH)                               # atomically: a half-written count is never read
    return limit - now["count"]
