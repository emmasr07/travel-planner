# FastAPI app: serves the frontend at /, a /health check, and (later) /api/plan on one port.
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="Travel Itinerary Planner")


@app.get("/health")
def health():
    return {"ok": True}


# Mounted last so /health and future /api routes take priority over static files.
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
