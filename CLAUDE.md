# CLAUDE.md: Travel Itinerary Planner

## What this is
A web app that turns a traveller's destination, dates, group, interests and budget into a day-by-day plan of experiences (activities, tours, food, nightlife, nature), shared as a brochure. No flights, no hotels. Any destination.
Theory: travellers reach a plan they trust faster than planning by hand, as long as every fact is real. So every name, price, opening hour and address comes from a source (API or web page) with its link and the time it was checked; the model chooses and explains, the code checks and counts, a second agent re-checks the sources.
Done by 26 Nov: on 20 experiences checked by hand against their sources (docs/hand-checks.md), the ones marked "verified" are right at least 19 times, and the page shows each item's source and checked-at time.

## How to run it
All commands from the project root (travel-planner/). Use the project's own Python:
`.venv/bin/python` on macOS, `.venv/Scripts/python` on Windows (written as PY below).
- First time: `python3 -m venv .venv` (Windows: `python -m venv .venv`), then `PY -m pip install -r requirements.txt`
- Start the server: `PY -m uvicorn backend.main:app --reload`, then open http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/health returns {"ok": true}
- Tests: `PY -m pytest` (pytest.ini limits it to tests/)
- MODE=demo (default) runs without AI, on data/samples/. MODE=agents needs ANTHROPIC_API_KEY.

## Where things live
- docs/: the decisions. Read before changing behaviour: ux-flow.md, data-model.md, backend-logic.md, design-spec.md, hand-checks.md.
- backend/main.py: FastAPI app; API routes under /api, defined before the static mount of frontend/.
- backend/trips.py: the business layer: a trip's steps (researching, checking, verifying, ready, done, failed) and rules.
- backend/store.py: the only file that reads and writes trip files (data/trips/<id>.json, not committed).
- backend/checks.py: every code check (schema, source quote, season, age, price, hours, closure, overlap, pace, accessibility).
- backend/budget.py: all money arithmetic, with Decimal, rounded to 2 places.
- backend/agents.py: the only file that calls the AI, or returns demo data when MODE=demo (each trip keeps its own mode). (backend/llm.py is an old stub: do not use.)
- backend/access.py: who may start a paid agents run (ACCESS_CODE, sent in the X-Access-Code header, never stored) and how many a day (DAILY_AGENT_LIMIT, counted in data/agent-usage.json, not committed).
- backend/recheck.py: verifies Viator and Geoapify facts by fetching the same record again; the verifier agent checks only web pages.
- backend/brochure.py: the brochure sublist, the static map call and the PDF (fpdf2), no AI. backend/fonts/: Inter TTF for the PDF (OFL licence in LICENSE.txt).
- backend/sources/: data tools: viator.py, geoapify.py, fx.py (Frankfurter), tavily.py, osm_hours.py. Every record carries a source block; every call adds a line to data/sources-log.jsonl.
- prompts/: agent instructions (researcher, verifier, quick-search). schemas/: the JSON the agents must return.
- data/samples/: real sample places for Lisbon, London, Matera (demo mode and tests). scripts/: builds the samples.
- frontend/: plain HTML, CSS and JavaScript, no framework; css/styles.css holds the design tokens.
- reference/: an older similar project, for reading only. Never import from it or edit it.
- tests/: every feature starts here with a failing test.

## How to behave
How to work:
1. Before writing code, state your assumptions and a short plan (step → how you'll check it). If the request is ambiguous, ask.
2. For any code change, write a failing test first, then make it pass.
3. Make the smallest change that works; touch only the files the task needs.
4. When done, say exactly how you verified it (which tests ran, what you saw in the browser).

Every trip must pass these checks, in Python with a test each, before it reaches the page:
5. Real facts only: every name, price, hours, address, rating and accessibility value is copied from a source, with its source block. Unknown is null or "unknown", never a guess. The model only writes suggestions (best_time, why_fits, schedule), each marked "kind": "suggestion".
6. Within budget: budget.py converts every price to EUR and adds the kept items. Items without a price are listed as "not counted". Over budget: the bar turns red, the brochure is refused, and fit-budget proposes removals (last-added first); the user confirms. Nothing is removed silently.
7. Right times: every experience is inside the trip dates, starts while the place is open (local time of the destination), fits its season (months), does not overlap another kept item that day, and respects the pace (chill 2, balanced 3, packed 4 per day).
8. Fits the group and interests: the category comes from the source, not the model; the youngest traveller meets min_age; a wheelchair need in the notes is checked against the accessibility field.
9. Status: any fail or a "contradicted" verdict means rejected (hidden); any warn or "not_sure" means to_check (shown with a note); otherwise verified.

## What not to do
- Never read, print or edit .env, and never put a key in code, logs or a commit. New settings go in .env.example; tell us to copy them.
- Backend stays FastAPI, frontend stays plain HTML/JS. No database, no login. Never add a package to requirements.txt without asking.
- No features beyond the task; suggest extras, don't build them.
- Never edit or delete a test to make it pass, unless we ask.
- Outside tests/, never hard-code or estimate a price, not even as a placeholder. Tests may use fixed example prices.
- Never pad a list: fewer real results is fine, an empty list is allowed.
- Never book or pay for anything; the app only plans.
- Never commit or push unless we ask.

## Mistakes we have seen
- Running uvicorn or pytest without the project's Python (PY) picked up conda's Python and failed with `ModuleNotFoundError: fastapi`. Always use `PY -m ...`.
- OpenStreetMap can be wrong (Casa Noha, Matera: "Recinto Canove" instead of "Recinto Cavone"). Copy the source faithfully; the verifier and hand checks catch it.
- Geoapify sometimes answers a slow query with "200, no places"; the builder retries. Geoapify name search can match the wrong place: use coordinates or a 30 km limit.
- Viator keys returned 401 "Invalid API Key" until 19 Nov; the production key works since. Most Viator products give only a Google place id or a hotel pickup (no coordinates), so build_sample places about 1 in 10 and keeps the Geoapify places alongside.
- After any change to prompts/, schemas/ or AGENT_MODEL, the agents keep their old instructions until we run `PY -m scripts.create_agents`; always tell us to run it.
