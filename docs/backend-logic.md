# Backend logic (business layer): Travel Planner

Roadmap step 4, item 1. This file defines **what the backend does and in what order**, before any code is written.
Read it with `docs/data-model.md` (what the data looks like) and `docs/ux-flow.md` (what the user sees).

## 1. What the business layer is

The website shows things and sends clicks. The **business layer** decides what each click means: which rules apply,
who is allowed to fill which field, when an agent runs, and when the trip is ready. It sits between the pages and
everything else:

```
frontend (4 pages)
   │  HTTP + JSON
   ▼
backend/main.py ─────────── API: receives requests, returns the trip
   │
   ▼
backend/trips.py ────────── business layer: the trip's steps and rules
   ├── backend/checks.py     code checks (season, age, hours, overlaps, budget, quote on page...)
   ├── backend/budget.py     all money arithmetic (Decimal, rounded to 2 places)
   ├── backend/agents.py     the only file that talks to the AI (or demo mode)
   ├── backend/sources/      data tools: Viator, Geoapify, Frankfurter, Tavily
   ├── backend/brochure.py   the sublist and the PDF (no AI)
   └── backend/store.py      one JSON file per trip in data/trips/
```

Rule: **each file has one job**. Only `agents.py` calls the AI, only `budget.py` does money arithmetic,
only `store.py` reads and writes trip files.

## 2. Who fills what

| Who | Fills | Never fills |
|---|---|---|
| **Sources** (via `backend/sources/`) | facts: name, price, hours, coordinates, rating, accessibility, links | suggestions |
| **Researcher agent** | which experiences to propose, `best_time`, `why_fits`, `schedule`, `certainty`, `doubts` | prices, conversions, totals, facts it did not copy |
| **Code** | schema check, currency conversion, every check in section 5, totals, final status, the brochure | any fact or suggestion |
| **Verifier agent** | one verdict per experience | anything else; it never repairs a record |
| **User** | kept / removed, order, changed time, questionnaire answers | — |

## 3. The life of a trip

Every trip is one file, `data/trips/<trip-id>.json` (shape in `docs/data-model.md`, section 2). Its `status` moves
through these steps. After each step the file is saved, and one line is added to `steps` so the page can show progress.

| Status | What happens | Who |
|---|---|---|
| `researching` | the researcher proposes up to 15 experiences with the source tools, fewer when fewer are real (never padded; an empty list is allowed) | agent (or demo data) |
| `checking` | schema check, currency conversion, all checks in section 5; going down the researcher's list (best fit first), an experience is kept while its day has room for the pace (chill 2, balanced 3, packed 4), unless it is the same place (or the same visit) as one already kept; the rest start removed as alternatives the user can restore, a same-place one with a note "Same place as …" (picked again after the verifier) | code |
| `verifying` | Viator and Geoapify facts: the code fetches the same record again and compares (`recheck.py`); facts from web pages: the verifier reopens the page | code + agent (or demo verdicts) |
| `ready` | final status per experience; rejected ones are hidden; the user keeps, removes, swaps, changes times | code + user |
| `done` | the brochure (sublist + PDF) is built from the kept experiences | code |
| `failed` | something went wrong; `error` says what, and everything done before is kept | — |

A step that fails stops the pipeline and sets `failed`. It never silently skips to the next step.
The pipeline and the searches run inside the server process, so a restart cuts them off: at startup, a trip still in
`researching`, `checking` or `verifying` becomes `failed` ("the server restarted while the trip was verifying, so it
stopped there") and a search still `searching` becomes `failed` ("…ask again"), so nothing waits forever.

## 4. API endpoints

All answers are JSON, except the PDF. Every endpoint that changes a trip returns the whole updated trip.

| Method and path | Does | When allowed |
|---|---|---|
| `GET /health` | `{"ok": true}` | always |
| `GET /api/config` | `{"mode": "demo" or "agents", "demo_destinations": [...]}` | always |
| `POST /api/trips` | body = questionnaire profile; validates it, creates the trip, starts the pipeline in the background; returns `{id}`. `?mode=demo` plans a demo trip on the samples even when the server runs the agents | always; agents mode: the access code (section 7) |
| `GET /api/trips/{id}` | the trip (the page polls this every 2 seconds while it is not `ready`) | always |
| `POST /api/trips/{id}/experiences/{exp_id}` | body `{"status": "kept" or "removed"}` and/or `{"day", "start"}`; re-runs the time and budget checks | `ready` or `done` |
| `POST /api/trips/{id}/fit-budget` | returns a proposal (which items to remove, cheapest last-added first) without applying it; the user confirms with the endpoint above | `ready` |
| `POST /api/trips/{id}/brochure` | builds the sublist (saved in the trip file: stops with facts, time reason, status, Book link; totals; not counted; "Prices checked on" note) and fetches one Geoapify static map (`data/trips/<id>.map.png`); without a key or when the call fails, the map block says why and the page and PDF place the pins by their coordinates; sets `done` | `ready`, kept total within budget, at least 1 kept |
| `GET /api/trips/{id}/brochure.pdf` | downloads the PDF, drawn on download from the saved sublist (no PDF file is stored) | `done` |
| `GET /api/trips/{id}/brochure/map.png` | the saved map image (the key stays on the server); 404 when the brochure uses the pin plot | `done` |
| `GET /api/trips/{id}/json` | downloads the trip file | always |
| `POST /api/trips/{id}/swap/{exp_id}` | **202**: 2–3 alternatives searched in the background into `search.options`, checked and verified (agents: quick-search researcher + verifier; demo: same-category items from the sample) | `ready`, no search running; an agents trip: the access code, and the server in agents mode |
| `POST /api/trips/{id}/quick` | body `{"request", "day"}`: **202**, last-minute search in the background, 0–3 options in `search.options` (demo: the request's words matched in the sample) | `ready` or `done`, no search running; an agents trip: as swap |
| `POST /api/trips/{id}/options/{option_id}` | the user's pick: adds the option as kept; for a swap the replaced item becomes removed | `ready` or `done`, search ready, option not rejected, nothing picked yet |

A request in the wrong state gets **409** with a plain message ("the list is not ready yet: verifying").
Invalid input gets **400** with the field that is wrong. An unknown trip gets **404**. In agents mode, missing
settings or a missing `agents/agents.lock.json` get **503** saying what to set or run. An agents run (new trip, swap,
quick search) without the right access code gets **403**, and one over today's limit **429** (section 7).

## 5. The rules the code checks

Each check returns `{"name", "result": "ok" | "warn" | "fail" | "skip", "detail"}`, stored in the experience's `checks`.

| Check | `fail` when | `warn` when |
|---|---|---|
| `schema` | the agent's delivery does not match `schemas/experiences.schema.json` (sent back to the agent, max 3 tries) | — |
| `source` | — | the quote is not on the source page, or the page does not load |
| `season` | — | `months` does not include the trip dates |
| `age` | the youngest traveller is under `min_age` | — (an agent's `min_age` with no web source never gets here: the delivery goes back to the agent) |
| `price` | the item alone costs more than the whole budget | no price, a currency that could not be converted, or free / 0 with no source that says so |
| `hours` | — | `schedule.start` is outside `opening_hours`, or no hours are known. OpenStreetMap syntax ("Mo-Sa 07:00-14:00") or Viator's dated hours ("Open 2026-12-04 11:00:00–20:00:00"); a trip day Viator doesn't list is unknown, not closed |
| `closure` | the source's description says the place is closed (closed, encerrado, chiuso, geschlossen, fermé, cerrado), e.g. "Encerrado temporariamente"; a sentence that only names closed days or holidays ("Closed on Mondays") is left to `hours`, unless it says temporarily or permanently | — |
| `suggestion` | — | `why_fits`, or `best_time.reason` while the suggested time is kept, names a price, a clock time, a date, "free" (gratis, gratuito…) or open/closed that the record's sourced facts (price, opening hours, web quotes) don't state: "suggestion mentions a fact not in the sources: "free", "6 Dec"" |
| `overlap` | — | two kept items overlap in time on the same day; or, on the later of two kept items anywhere in the trip: the same place (the same name after normalising, or within 15 m in the same category), the same visit (a guided tour whose source says entry is included, and an entry ticket to that place), or maybe the same visit (the tour's source doesn't say; "skip-the-line" alone doesn't count). A tour whose source says entry is not included is no overlap |
| `pace` | — | more items in a day than the pace allows (chill 2, balanced 3, packed 4) |
| `accessibility` | — | the notes mention a wheelchair and `wheelchair` is `no` or `unknown` |

**Final status** (shown on the card):
- **rejected**: any `fail`, or the verifier says `contradicted`. Hidden from the list, kept in the file.
- **to_check**: any `warn`, or the verifier says `not_sure`. Shown with a note; the user decides.
- **verified**: everything `ok` and the verifier says `confirmed`.

## 6. The budget (always in `budget.py`)

- Every price is converted to EUR by code (`amount_eur`), with the rate and date in `fx`.
- The budget is compared per person or in total, as the user chose in the questionnaire, so one item's cost
  (`cost_eur`) is in that unit, from `amount_eur`:
  - per-person budget: `per: person` → amount; `per: group` → amount ÷ group size;
  - total budget: `per: person` → amount × group size; `per: group` → amount;
  - `per: free` → 0 in both.
- Items without a price are **not counted** and are listed under "not counted" so the user sees it.
- Kept total over budget: the page shows red, `brochure` is refused (409), `fit-budget` is offered.
- Money is `Decimal`, rounded to 2 places, never `float`.

## 7. Two modes

| | `MODE=demo` | `MODE=agents` |
|---|---|---|
| research | the matching sample in `data/samples/<city>.json`, plus fixed suggestions | researcher agent on Claude Managed Agents |
| verification | fixed "not_sure" verdicts, clearly labelled demo | verifier agent |
| destinations | only the samples (Lisbon, London, Matera); others get a clear 400 | any |
| cost | free, no key | capped per session (`RESEARCHER_CAP_CENTS`, `VERIFIER_CAP_CENTS`) |
| who may run it | anyone | whoever sends `ACCESS_CODE` in the `X-Access-Code` header (asked once on the questionnaire, kept for the browser tab only); no code set on the server = 403 for everyone |
| how often | always | `DAILY_AGENT_LIMIT` runs a UTC day (default 10; a trip, a swap and a quick search each count 1, when accepted), counted in `data/agent-usage.json`; 429 over it, 0 = off |

Demo mode exists so the app always works for a presentation, and the tests never call the AI or cost money.
Demo data is never presented as verified.
Each trip keeps the mode it was planned in (`trip.mode`): a server in agents mode still plans a demo trip
(`POST /api/trips?mode=demo`, no code, never counted), whose swap and quick search stay on the samples; an agents trip's
swap and quick search are refused (409) by a server in demo mode. The access code is only compared in
`backend/access.py`: never stored in a trip file, a log or an answer.

## 8. What is never allowed

- A fact without a source, or a price written by the AI.
- Arithmetic outside `budget.py`.
- Keys or personal data in logs or trip files (the profile holds only what the questionnaire asked).
- A step that fails silently.
- Editing an existing test to make it pass.

## 9. Built in which session

1. **Session 1, backend without AI:** sections 1, 3, 4 (except swap/quick), 5, 6, 7 demo mode; the 4 pages connected to the API.
2. **Session 2, agents:** `agents.py` with Claude Managed Agents (researcher, verifier, quick search, swap), agents mode.
3. **Session 3, brochure:** `brochure.py`, the sublist and the PDF.
