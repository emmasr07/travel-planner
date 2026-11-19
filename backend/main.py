# FastAPI app: the API under /api (docs/backend-logic.md section 4), /health, and the frontend at / on one port.
# Each route only translates HTTP to backend/trips.py and its errors back: 400 bad input (with the field),
# 404 unknown trip, 409 wrong state, 501 not built yet, 503 agents mode not set up.
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()

from backend import agents, store, trips  # noqa: E402  (after load_dotenv: agents reads MODE)

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="Travel Itinerary Planner")


def _error(status, detail, field=None):
    body = {"detail": detail}
    if status == 400:
        body["field"] = field
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(RequestValidationError)
async def _invalid(request, exc):
    err = exc.errors()[0]
    loc = [str(part) for part in err["loc"] if part != "body"]
    field = ".".join(loc) or None
    message = err["msg"].removeprefix("Value error, ")
    return _error(400, f"{field}: {message}" if field else message, field)


@app.exception_handler(trips.BadInput)
async def _bad_input(request, exc):
    return _error(400, str(exc), exc.field)


@app.exception_handler(trips.NotFound)
async def _not_found(request, exc):
    return _error(404, str(exc))


@app.exception_handler(trips.WrongState)
async def _wrong_state(request, exc):
    return _error(409, str(exc))


@app.exception_handler(trips.NotBuilt)
async def _not_built(request, exc):
    return _error(501, str(exc))


@app.exception_handler(trips.NotReady)
async def _not_ready(request, exc):
    return _error(503, str(exc))


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"mode": agents.mode(), "demo_destinations": agents.demo_destinations()}


@app.post("/api/trips", status_code=201)
def new_trip(profile: trips.Profile, background: BackgroundTasks):
    trip = trips.create_trip(profile)
    background.add_task(trips.run_pipeline, trip["id"])
    return {"id": trip["id"]}


@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: str):
    return trips.get_trip(trip_id)


@app.post("/api/trips/{trip_id}/experiences/{exp_id}")
def change_experience(trip_id: str, exp_id: str, change: trips.Change):
    return trips.change_experience(trip_id, exp_id, change)


@app.post("/api/trips/{trip_id}/fit-budget")
def fit_budget(trip_id: str):
    return trips.fit_budget(trip_id)


@app.post("/api/trips/{trip_id}/brochure")
def build_brochure(trip_id: str):
    return trips.build_brochure(trip_id)


@app.get("/api/trips/{trip_id}/brochure.pdf")
def brochure_pdf(trip_id: str):
    pdf = trips.brochure_pdf(trip_id)             # the id is already checked: lowercase letters, digits, dashes
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{trip_id}.pdf"'})


@app.get("/api/trips/{trip_id}/brochure/map.png")
def brochure_map(trip_id: str):
    """The Geoapify map image saved at build time: the page gets it from here, so the key stays on the server."""
    return Response(trips.brochure_map(trip_id), media_type="image/png")


@app.post("/api/trips/{trip_id}/swap/{exp_id}", status_code=202)
def swap(trip_id: str, exp_id: str, background: BackgroundTasks):
    trip = trips.start_swap(trip_id, exp_id)
    background.add_task(trips.run_search, trip_id)
    return trip


@app.post("/api/trips/{trip_id}/quick", status_code=202)
def quick(trip_id: str, ask: trips.Ask, background: BackgroundTasks):
    trip = trips.start_quick(trip_id, ask)
    background.add_task(trips.run_search, trip_id)
    return trip


@app.post("/api/trips/{trip_id}/options/{option_id}")
def pick_option(trip_id: str, option_id: str):
    return trips.pick_option(trip_id, option_id)


@app.get("/api/trips/{trip_id}/json")
def trip_json(trip_id: str):
    trips.get_trip(trip_id)
    return FileResponse(store.path(trip_id), media_type="application/json", filename=f"{trip_id}.json")


# Mounted last so /health and the /api routes take priority over static files.
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
