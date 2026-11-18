"""The web server: the page and the API on one port, and the pipeline research -> code checks -> verifier.

    uvicorn backend.main:app --reload        then http://127.0.0.1:8000

Every trip is one JSON file in data/trips/<id>.json, rewritten after each step; the PDF sits next to it.
"""
import json
import re
import threading
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from backend import checks, llm, pdf  # noqa: E402  (after load_dotenv: llm reads MODE)

ROOT = Path(__file__).resolve().parent.parent
TRIPS = ROOT / "data" / "trips"
TRIPS.mkdir(parents=True, exist_ok=True)
SAVE = threading.Lock()

app = FastAPI(title="trip-experiences")


class Traveller(BaseModel):
    name: str = Field(min_length=1)
    age: int = Field(ge=0, le=110)


class Profile(BaseModel):
    destination: str = Field(min_length=2)
    start: date
    end: date
    budget: float = Field(gt=0)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    travellers: list[Traveller] = Field(min_length=1)
    interests: list[str] = []
    notes: str = ""


class Picks(BaseModel):
    ids: list[str]


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"mode": llm.mode()}


@app.post("/api/trips")
def new_trip(profile: Profile):
    if profile.end < profile.start:
        raise HTTPException(400, "the trip ends before it starts")
    slug = re.sub(r"[^a-z0-9]+", "-", profile.destination.lower()).strip("-")[:30]
    trip = {"id": f"{slug}-{datetime.now():%Y%m%d-%H%M%S}", "created": datetime.now().isoformat(timespec="seconds"),
            "mode": llm.mode(), "profile": profile.model_dump(mode="json"), "status": "researching", "steps": [],
            "experiences": [], "picks": None, "totals": None, "pdf": None, "sessions": {}, "error": None}
    save(trip)
    threading.Thread(target=pipeline, args=(trip,), daemon=True).start()
    return {"id": trip["id"]}


@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: str):
    return load(trip_id)


@app.post("/api/trips/{trip_id}/picks")
def choose(trip_id: str, body: Picks):
    trip = load(trip_id)
    if trip["status"] not in ("ready", "done"):
        raise HTTPException(409, f"the list is not ready yet: {trip['status']}")
    errors, totals = checks.picks(trip["profile"], trip["experiences"], body.ids)
    if errors:
        raise HTTPException(400, "; ".join(errors))
    trip.update(picks=body.ids, totals=totals, status="done")
    trip["pdf"] = pdf.write(trip, TRIPS / f"{trip_id}.pdf").name
    save(trip)
    return trip


@app.get("/api/trips/{trip_id}/pdf")
def get_pdf(trip_id: str):
    trip = load(trip_id)
    if not trip["pdf"]:
        raise HTTPException(404, "no PDF yet: pick five experiences first")
    return FileResponse(TRIPS / trip["pdf"], media_type="application/pdf", filename=trip["pdf"])


@app.get("/api/trips/{trip_id}/json")
def get_json(trip_id: str):
    load(trip_id)
    return FileResponse(TRIPS / f"{trip_id}.json", media_type="application/json", filename=f"{trip_id}.json")


def pipeline(trip: dict) -> None:
    """Researcher, then code checks, then verifier; one step line per event so the page shows the loop."""
    profile = trip["profile"]

    def step(who: str, text: str) -> None:
        trip["steps"].append({"at": datetime.now().strftime("%H:%M:%S"), "who": who, "text": text})
        save(trip)

    try:
        found, trip["sessions"]["researcher"] = llm.research(profile, step, checks.delivery_errors)
        trip["status"] = "checking"
        step("code", f"{len(found)} experiences received, checking schema, season, ages, prices and sources")
        errors = checks.delivery_errors({"experiences": found})
        if errors:
            raise llm.AgentFailed(f"{len(errors)} schema errors left after {llm.MAX_DELIVERIES} deliveries: {errors[0]}")
        urls = [e["sources"][0]["url"] for e in found]
        pages = checks.read_pages(urls) if trip["mode"] == "agents" else {}
        for e in found:
            e["checks"] = checks.check(profile, e, pages.get(e["sources"][0]["url"]))
            e["group_cost"] = checks.group_cost(profile, e)
        trip.update(experiences=found, status="verifying")
        step("code", "checks done, the verifier reopens every source")

        verdicts, trip["sessions"]["verifier"] = llm.verify(profile, found, step)
        by_id = {v["id"]: v for v in verdicts}
        for e in found:
            e["verdict"] = by_id.get(e["id"])
            e["status"] = checks.status(e["checks"], e["verdict"])
        counts = {s: sum(e["status"] == s for e in found) for s in ("verified", "to_check", "rejected")}
        trip["status"] = "ready"
        step("code", f"{counts['verified']} verified, {counts['to_check']} to check, {counts['rejected']} rejected")
    except Exception as exc:  # the page shows the error; the JSON keeps what was done before it
        trip.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save(trip)


def save(trip: dict) -> None:
    with SAVE:
        tmp = TRIPS / f"{trip['id']}.json.tmp"
        tmp.write_text(json.dumps(trip, ensure_ascii=False, indent=2))
        tmp.replace(TRIPS / f"{trip['id']}.json")


def load(trip_id: str) -> dict:
    path = TRIPS / f"{trip_id}.json"
    if not re.fullmatch(r"[a-z0-9-]+", trip_id) or not path.exists():
        raise HTTPException(404, "no such trip")
    return json.loads(path.read_text())


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
