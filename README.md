# Travel Itinerary Planner

You give a destination, dates, group, interests and budget. The app plans experiences day by day: activities, tours, food, nightlife and nature. The plan is shared as a brochure, both a web page and a PDF.
It works for any destination. It plans experiences only: no flights, no hotels, and it never books or pays for anything.
Every name, price, opening hour and address comes from a source (an API or a web page). The page shows that source's link and when it was checked.

## How to run it

Run every command from the project root (`travel-planner/`) with the project's own Python. Below, **PY** stands for:

| macOS | Windows |
|---|---|
| `.venv/bin/python` | `.venv/Scripts/python` |

**First time**

```bash
python3 -m venv .venv                     # Windows: python -m venv .venv
PY -m pip install -r requirements.txt
```

**Start the server**

```bash
PY -m uvicorn backend.main:app --reload
```

Then open http://127.0.0.1:8000. Health check: http://127.0.0.1:8000/health returns `{"ok": true}`.

**Tests**

```bash
PY -m pytest
```

`pytest.ini` limits the run to `tests/`. `make run` and `make verify` are shortcuts for the server and the tests.

Always use `PY -m …`. A bare `uvicorn` or `pytest` can pick up another Python (conda, for example), which fails with `ModuleNotFoundError: fastapi`.

### Demo mode (default)

`MODE=demo` needs no AI and no keys. It plans from real sample places saved in `data/samples/` (Lisbon, London, Matera). Its verdicts are always "not sure", because no verifier runs, so its items show as to check.

### Agents mode (Claude agents, paid)

1. Copy `.env.example` to `.env` (`cp .env.example .env`; Windows: `copy .env.example .env`). In `.env`, set:
   - `MODE=agents`
   - `ANTHROPIC_API_KEY`
   - the source keys (`VIATOR_API_KEY`, `GEOAPIFY_API_KEY`, `TAVILY_API_KEY`)
   - an `ACCESS_CODE`
   - the agent settings, if you want to change them (see Safety below)
2. Create the two agents (researcher and verifier) once. This writes `agents/agents.lock.json`:
   ```bash
   PY -m scripts.create_agents
   ```
   Run it again after any change to `prompts/`, `schemas/` or `AGENT_MODEL`. Until then, the agents keep their old instructions.
3. Start the server as above. On the questionnaire's last step, type the access code.

## Folder map

| Path | What it holds |
|---|---|
| `backend/` | FastAPI app (`main.py`). Trip steps and rules (`trips.py`), the only file that reads and writes trip files (`store.py`), the code checks (`checks.py`), money arithmetic (`budget.py`), the only file that calls the AI (`agents.py`), the access code and daily limit (`access.py`), code re-checks of Viator and Geoapify (`recheck.py`), brochure and PDF (`brochure.py`) |
| `backend/sources/` | Data tools: Viator, Geoapify, Frankfurter (exchange rates), Tavily, opening-hours parsers |
| `frontend/` | Plain HTML, CSS and JavaScript, no framework |
| `prompts/`, `schemas/` | The agents' instructions, and the JSON they must return |
| `agents/` | `agents.lock.json`: the ids of the agents created on Anthropic |
| `data/samples/` | Sample places for demo mode and tests. `data/trips/` (trip files) is not committed |
| `docs/` | The decisions: UX flow, data model, backend logic, design spec, hand checks, cost log, backlog |
| `scripts/` | Build the samples, create the agents |
| `tests/` | Every feature starts here with a failing test |
| `reference/` | An older similar project, for reading only |

## How trust works

The AI finds and explains. The code counts and checks. A second check judges what the first AI found. Every fact carries its source. Each field is one of four kinds (details in [docs/data-model.md](docs/data-model.md)):

| Kind | Filled by | Rule |
|---|---|---|
| **Fact** | a source (API or web page) | Copied exactly, with a `source` block: provider, link, `retrieved_at`, and a word-for-word quote from a web page. If the source doesn't say, the value is `null` or `"unknown"`, never a guess. Names, prices, hours, addresses, ratings, accessibility and categories are all facts. |
| **Suggestion** | the AI | Only choices and explanations: best time, why it fits, which day. Marked `"kind": "suggestion"`. A suggestion may explain a fact, but never add one. |
| **Check** | the code (`backend/checks.py`) | Schema, source quote, season, age, price, opening hours, closure, suggestion, overlap / same place, pace, accessibility. Each check gives `ok`, `warn`, `fail` or `skip`. Arithmetic is done in code, never by the AI. |
| **Verdict** | not the AI that wrote it | `confirmed`, `contradicted` or `not_sure`. Viator and Geoapify facts are fetched again by the code (`backend/recheck.py`). Web-page facts are reopened by the verifier agent. |

Each experience then gets a status:

- **rejected**: any `fail`, or a `contradicted` verdict. It is hidden.
- **to_check**: any `warn`, or a `not_sure` verdict. It is shown with a note saying what to check.
- **verified**: every check passed, and the verdict is `confirmed`.

Budget: `backend/budget.py` converts every price to EUR (Frankfurter's daily rate) and adds up the kept items. Items without a price are listed as "not counted". When the plan goes over budget:

- the bar turns red;
- the brochure is refused;
- "fit budget" proposes items to remove, last-added first.

The user confirms each removal. Nothing is removed silently.

## Results

- **Hand checks**, in [docs/hand-checks.md](docs/hand-checks.md). The file holds 24 checks we did ourselves against the sources, 18–25 Nov, in Lisbon, London, Matera and Rome:
  - 20 were right (✅), 3 were wrong (❌) and 1 was a finding (⚠️).
  - All 7 items the app had marked "verified" matched their source page.
  - The goal for 26 Nov: check 20 experiences by hand, and the ones marked "verified" must be right at least 19 times. So far, 7 verified items have been checked.
  - Most findings became a check. A closed place was suggested, so there is now the `closure` check. The same place was listed twice, so the `overlap` check now catches the same place. A fact slipped into a suggestion, so there is now the `suggestion` check.
  - One finding has no check: an address typo in OpenStreetMap. The address is copied as the source writes it, and hand checks catch typos like this.
- **Cost of agents mode**, in [docs/cost-log.md](docs/cost-log.md). It logs 4 trips:
  - each cost $0.24 to $0.77 and took 1 min 15 s to 3 min 20 s;
  - the latest (25 Nov, Lisbon, 3 days) cost $0.24, with 7 experiences kept, 3 verified, and the plan within budget.

## Safety

- **Keys live only in `.env`**, which git ignores. Copy `.env.example` and fill it in; never put a key in code, logs or a commit. Every source call is logged in `data/sources-log.jsonl`, without the key.
- **Access code.** Agents runs cost money, so each one needs `ACCESS_CODE`:
  - The page sends the code in the `X-Access-Code` header. It is only compared, never written to a trip file, a log or an answer.
  - With no code set on the server, every agents run is refused (403). Demo trips never need it.
- **Daily limit.** `DAILY_AGENT_LIMIT` (10 by default) caps how many agents runs a day are allowed:
  - a new trip, a swap or a quick search counts as 1 run;
  - runs are counted per UTC day in `data/agent-usage.json`;
  - over the limit, the server refuses with 429; `0` turns the agents off.
- **Caps per session**, set in `.env.example`:
  - a cost cap of `RESEARCHER_CAP_CENTS=100` ($1.00) and `VERIFIER_CAP_CENTS=50` ($0.50). The platform pauses a session at its cap, and the trip fails with its cost recorded;
  - `AGENT_DEADLINE_S=600`, a 10-minute limit. After it, the step fails.
- **Privacy.** Trip files (`data/trips/`) hold questionnaire answers and are never committed.
