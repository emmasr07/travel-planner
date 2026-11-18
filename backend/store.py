# The only file that reads and writes trip files: one JSON file per trip in data/trips/<trip-id>.json,
# rewritten after each step (atomically, so a half-written file is never read).
import json
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIPS_DIR = ROOT / "data" / "trips"
TRIP_ID = re.compile(r"[a-z0-9-]{1,80}")
_LOCK = threading.Lock()


class TripNotFound(Exception):
    pass


def path(trip_id):
    if not isinstance(trip_id, str) or not TRIP_ID.fullmatch(trip_id):
        raise TripNotFound("no such trip")
    return TRIPS_DIR / f"{trip_id}.json"


def save(trip):
    target = path(trip["id"])
    with _LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(trip, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)


def load(trip_id):
    target = path(trip_id)
    if not target.exists():
        raise TripNotFound("no such trip")
    return json.loads(target.read_text(encoding="utf-8"))
