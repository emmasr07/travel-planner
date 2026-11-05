# CLAUDE.md: Travel Itinerary Planner

## What this is
A web app that turns a traveller's budget, dates and interests into a complete, bookable trip plan (flights, hotels, activities).
Theory: travellers reach a booked trip faster than planning by hand, as long as every price is real. So every flight, hotel and price comes from a live search API with its source and a timestamp; the model never writes a price.
Done by 26 Nov: re-running the searches within 30 minutes confirms 100% of items in the 20 test trips in data/test_trips.json at the quoted price, and the page shows each item's source and quote time. (The "50% faster" target is measured with users, not in code.)

## How to run it
All commands from the project root (travel-planner/). Use the project's own Python:
`.venv/bin/python` on macOS, `.venv/Scripts/python` on Windows (written as PY below).
- First time: `python3 -m venv .venv` (Windows: `python -m venv .venv`), then `PY -m pip install -r requirements.txt`
- Start the server: `PY -m uvicorn backend.main:app --reload`, then open http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/health returns {"ok": true}
- Tests: `PY -m pytest`

## Where things live
- backend/main.py: FastAPI app; serves frontend/ at / and API routes under /api. Define new routes before the static mount.
- backend/llm.py: the only file that calls the model. Model address and name come from .env (local Qwen via Ollama now, course API key later).
- backend/search/: one file each for flights, hotels, activities. Every result carries name, price, currency (EUR only for now), source and quoted_at; hotels and activities also carry address, category and opening hours; flights carry departure and arrival times with time zone.
- backend/budget.py: all money arithmetic, in Python.
- backend/schema.py: the itinerary JSON format; model output is validated against it.
- frontend/: plain HTML, CSS and JavaScript, no framework.
- data/: test trips and retrieval material.
- tests/: every feature starts here with a failing test.

## How to behave
How to work:
1. Before writing code, state your assumptions and a short plan (step → how you'll check it). If the request is ambiguous, ask.
2. For any code change, write a failing test first, then make it pass.
3. Make the smallest change that works; touch only the files the task needs.
4. When done, say exactly how you verified it (which tests ran, what you saw in the browser).

Every itinerary must pass these checks, in Python with a test each, before it reaches the page (rule 6 allows one exception):
5. Real items only: every flight, hotel and activity comes from a live search result; all its fields (listed under Where things live) are copied from that result, never written by the model.
6. Within budget: budget.py adds the prices. If the total is over budget, the model swaps items and the check runs again, up to 3 tries. If nothing fits, show the cheapest plan clearly marked "over budget by €X".
7. Right dates, times and logistics. Store every time with its time zone; compare exact moments (flight times) in UTC, and calendar dates and opening hours in local time.
   - Dates: the outbound flight departs on the start date and the return flight departs on the end date, each in its departure airport's local time; hotel nights = nights actually spent there; every activity inside the stay.
   - Time zones: an overnight or eastbound flight can land the next day; plan the first day from the real local arrival time.
   - Buffers and distance come from fields on the form, sent with each request and not stored (defaults: 2 h after landing, 2 h at the airport before departure, 45 min max between stops); never change them silently, and never let activities overlap. Travel time between stops (walking or public transport) is checked only once a maps service is added.
   - Opening hours: every activity happens while the place is open.
8. Matches interests: each activity's interest comes from the category in its search result, not from the model; every interest the user gave is covered at least once, and no activity serves none.

## What not to do
- Never read, print or edit .env, and never put a key in code or in a commit. New settings go in .env.example; tell us to copy them.
- Backend stays FastAPI, frontend stays plain HTML/JS. No database, no login. Never add a package to requirements.txt without asking.
- No features beyond the task; suggest extras, don't build them.
- Never edit or delete a test to make it pass, unless we ask.
- Outside tests/, never hard-code or estimate a price, not even as a placeholder. Tests may use fixed example prices.
- Never book or pay for anything; the app only plans.
- Never commit or push unless we ask.

## Mistakes we have seen
- Running uvicorn or pytest without the project's Python (PY) picked up conda's Python and failed with `ModuleNotFoundError: fastapi`. Always use `PY -m ...`.