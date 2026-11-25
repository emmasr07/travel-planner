# Data model and sources: Travel Planner

Roadmap step 3. This file defines what we store about a trip and each experience, the JSON the agents must return, where the data comes from, and how we prove every fact is true.

In one line: **the AI finds and explains, the code counts and checks, a second AI judges the first, and every fact carries its source.**

## 1. The one rule

Every field is one of these kinds:

| Kind | Who fills it | Rule |
|---|---|---|
| **FACT** | a source (API or web page) | Copied exactly, never written or guessed by the AI. Always carries a `source` block. If the source doesn't have it: `null` or `"unknown"`. |
| **SUGGESTION** | the AI | Only choices and explanations (best time, why it fits, which day). Marked `"kind": "suggestion"`. The code checks it against the facts. |
| **CHECK** | the code | Schema, season, age, price vs budget, time inside opening hours, quote on the page, no overlaps. The AI never does arithmetic. |
| **VERDICT** | a second AI (the verifier) | Reopens the source and says confirmed / contradicted / not_sure. It did not write the record it judges. |
| **USER** | the user | Kept/removed, order, changed time. Always wins over suggestions. |

Every `source` block has the same shape:

```json
{ "provider": "viator", "url": "https://…", "retrieved_at": "2026-11-17T14:42:00+01:00", "quote": "One sentence copied word for word from the page, or null for API data." }
```

`quote` is required when the fact comes from a web page (the code then checks that the sentence is really on that page). For API data it is `null`, because the API response itself is the evidence and is recorded in the log.

## 2. The trip: one JSON file per trip

Every trip is saved as `data/trips/<trip-id>.json` and rewritten after each step, so nothing is lost if something fails halfway.

```
trip
├── id, created, status         researching → checking → verifying → ready → done (or failed)
├── mode                        demo / agents: the mode the trip was planned in, kept for its swaps and quick searches
├── profile                     the questionnaire answers
├── steps []                    log of what each agent, the code and the user did, with times (shown to the user)
├── experiences []              see section 3
├── totals                      spent vs budget, computed by code (null until the checking step)
├── brochure                    null until built: the sublist (stops with facts, status, Book link), totals, not counted,
│                               the "Prices checked on" note and the map block; the PDF is drawn from it on download
├── sessions []                 agents mode only: one entry per agent session, with its cap and cost
├── search                      only after the first swap or quick search: the latest one, its checked options, the pick
└── error                       what went wrong, if status = failed; otherwise null
```

`id` is the destination, the date and time, and 4 random hex characters (`lisbon-20261123-131133-e1da`); only lowercase
letters, digits and dashes. `error` is the exception's type and message (`"AgentFailed: researcher stopped at its cost
cap ($1.00) before delivering"`). A trip or search cut off by a server restart becomes `failed` at the next start, with
the reason ("the server restarted while the trip was verifying, so it stopped there"; for a search, "…ask again").

### The code's blocks

| Block | Shape |
|---|---|
| `steps[]` | `{ "at", "who", "text" }`; `who` is code / researcher / verifier / user |
| `totals` | `{ "per", "group_size", "budget", "used", "left", "over_by", "over", "kept", "counted", "not_counted" }`: money in EUR as 2-place strings (`"86.00"`), in the budget's unit (per person or total, as the user chose); `kept` is how many count (kept and not rejected); `counted` / `not_counted` are lists of experience ids |
| `sessions[]` | `{ "role", "purpose", "session_id", "model", "cap", "list_cost", "active_seconds", "stop", "deliveries", "tool_calls", "ended" }`: role researcher / verifier, purpose research / verify / quick; `cap` and `list_cost` are `{ "amount", "currency": "USD" }` in whole US cents as strings, as the API states them (`"100"` = $1.00); `list_cost` null if the platform did not answer; `stop` is the platform's stop reason (`end_turn`, `budget_reached`…) |
| `search` | `{ "kind", "for", "request", "day", "status", "options", "error", "picked", "started" }`: kind swap / quick, `for` the swapped experience's id (null for quick), status searching / ready / failed, `options` 0–3 experiences checked and verified like the list (each with `checks`, `verdict`, `status`, `user`, `cost_eur`), `picked` the chosen option's id or null |
| `brochure` | `{ "created_at", "stops", "totals", "not_counted", "prices_checked_at", "prices_note", "map", "pdf" }`: `not_counted` as `{ "id", "name" }`; `prices_checked_at` the oldest price check among the stops (null when none has a price); `pdf` always null (the PDF is never stored) |
| a brochure stop | `{ "id", "stop", "day", "date", "start", "end", "name", "time_why", "price", "cost_eur", "status", "note", "booking_url", "location" }`: numbered by day, then start time; `time_why` is `{ "text", "kind" }`, kind suggestion (the AI's reason) or user ("You picked this time"); `price` is the experience's price block; `note` says what to check before booking (to_check only); `location` is `{ "lat", "lng", "address" }` |
| brochure `map` | `{ "kind": "static", "source", "attribution" }` when the Geoapify image was saved beside the trip (`<trip-id>.map.png`), or `{ "kind": "plot", "reason" }` when the page and PDF place the pins by their coordinates |

### `profile` (from the questionnaire)

| Field | Type | Example |
|---|---|---|
| `destination` | string | `"Lisbon"` (demo: the sample's city name; agents: as typed) |
| `start_date`, `end_date` | date | `"2026-12-04"`, `"2026-12-06"` |
| `timezone` | string | `"Europe/Lisbon"` (found by code: from the sample in demo mode, from Geoapify at the research step in agents mode) |
| `group_type` | enum | solo / couple / friends / family / business |
| `group_size` | integer | `4` |
| `age_range` | enum | 18-24 / 25-34 / 35-49 / 50+ (plus `youngest_age` for families with children) |
| `interests` | string[] | `["food", "culture", "adventure"]`, from culture, food, nature, nightlife, relax, adventure, shopping |
| `budget` | object | `{ "amount": "250", "currency": "EUR", "per": "person" }`; per is person / total; the amount is saved as a string, the exact decimal the user typed |
| `pace` | enum | chill / balanced / packed |
| `notes` | string | `"no museums, one of us uses a wheelchair"` |

## 3. One experience: 6 layers

### 3a. Facts (from sources, each block with its `source`)

| Field | Type | Example | Notes |
|---|---|---|---|
| `id` | string | `"viator-12345p1"` | lowercase-with-dashes, unique in the trip |
| `name` | string | `"Alfama food walk"` | |
| `description` | string | `"Taste pastries, cheese and ginjinha…"` | two sentences at most, from the source |
| `category` | enum | `"food"` | one of the 7 interests, mapped by code from the source's tags |
| `tags` | string[] | `["wine tasting", "walking tour"]` | more specific: trekking, spa, wine… |
| `location` | object | `{ "city", "address", "lat", "lng", "timezone", "source" }` | `lat`/`lng` **required** for the map |
| `duration_min` | integer or null | `180` | |
| `price` | object | `{ "amount", "currency", "per", "label", "amount_eur", "fx", "source" }` | `per`: person / group / free. `amount` null if no source states it. `label`: which of the place's prices, copied word for word ("Adult (non-resident)"); null if the source names none. Viator: the age band its schedule gives for the from-price ("Adult (18–65)", "Adult (18–99), when 2 book together"), null when the schedule doesn't show it; a Viator UNIT price (per vehicle or group) has `per` group. `amount_eur` and `fx` filled by code |
| `opening_hours` | object or null | `{ "text": "Daily 10:00 and 14:00", "slots": ["10:00","14:00"], "source" }` | |
| `months` | integer[] | `[]` | months it runs or is best, as the source states; `[]` = all year |
| `min_age` | integer or null | `12` | only if a source states it; never from a price label or age band ("Adult (18–99)" is not 18+). Viator and Geoapify give none, so an agent's experience with a `min_age` and no web source goes back to the agent to fix |
| `rating` | object or null | `{ "value": 4.7, "scale": 5, "review_count": 1243, "source" }` | |
| `indoor_outdoor` | enum | `"outdoor"` | indoor / outdoor / mixed / unknown |
| `accessibility` | object | `{ "wheelchair": "limited", "notes", "source" }` | yes / limited / no / unknown. **Never guessed** |
| `suitable_for` | object | `{ "values": ["friends","couple"], "kind": "fact" or "suggestion" }` | solo, couple, friends, family, business |
| `booking_url` | string | `"https://www.viator.com/…"` | where "Book" goes |
| `photo_url` | string or null | `"https://…"` | |

### 3b. Agent honesty (from the researcher agent)

| Field | Type | Example |
|---|---|---|
| `certainty` | enum | high / medium / low |
| `doubts` | string or null | `"Price found only on a blog from 2025"` |

"Not found" is an allowed answer; a guessed number is not.

### 3c. Suggestions (from the AI, checked by code)

| Field | Type | Example | Checked by code |
|---|---|---|---|
| `best_time` | object | `{ "slot": "sunset", "start": "18:30", "reason": "Best light over the river", "kind": "suggestion" }` | only its shape: the hours check uses `schedule.start`; the reason is shown while the user keeps that time |
| `why_fits` | object | `{ "text": "You picked food", "kind": "suggestion" }` | only its shape: shown as the AI wrote it, marked as a suggestion |
| `schedule` | object | `{ "day": 1, "start": "18:30", "end": "20:30" }` | day within the trip and `end = start + duration_min` (sent back to the agent if not); then the `hours`, `overlap` and `pace` checks |

### 3d. Checks (from the code)

A list, one entry per check, always in this order: `{ "name", "result": "ok" | "warn" | "fail" | "skip", "detail" }`.
`schema` and `source` are decided once, at the checking step; the others run again after every keep, remove or time
change. `skip` means the check could not apply (in demo mode no source page is read, so `source` is skipped).

| Check | fail / warn when |
|---|---|
| `schema` | always ok here: a delivery that does not match the schema never gets this far (it goes back to the agent to fix, up to 3 deliveries) |
| `source` | warn if the quote is not on the source page, or the page doesn't load |
| `season` | warn if `months` doesn't include the trip dates |
| `age` | fail if the youngest traveller is under `min_age` |
| `price` | warn if no price, a currency that could not be converted, or free / 0 with no source that says so; fail if it alone exceeds the whole budget |
| `hours` | warn if `schedule.start` is outside `opening_hours`, the place is closed that day, or no hours are known (OpenStreetMap syntax or Viator's dated hours) |
| `closure` | fail if the source's description says the place is closed or temporarily closed, in any of six languages (closed days such as "Closed on Mondays" are left to the hours check) |
| `overlap` | warn if it overlaps another kept item that day in time, or (said on the later of the two) is the same place as an earlier kept item (same normalised name, or within 15 m in the same category), the same visit (a guided tour whose source says entry is included + an entry ticket to that place) or maybe the same visit (the tour's source doesn't say) |
| `pace` | warn if its day holds more kept items than the pace allows (chill 2, balanced 3, packed 4) |
| `accessibility` | warn if the notes mention a wheelchair and `wheelchair` is no / unknown |

### 3e. Verdict (from the code and the verifier agent)

```json
{ "id": "alfama-food-walk", "verdict": "confirmed", "url_read": "https://…", "passage": "What the page says, copied word for word.", "contested_fields": [], "note": "The page supports name, price and hours." }
```

`id` is the experience's id. In demo mode every verdict is not_sure, with empty `url_read` and `passage` and a note
saying the verifier did not run. `verdict`: confirmed (the page supports the record) / contradicted (it says something else, listed in `contested_fields`) / not_sure (page didn't load, behind a login, or doesn't say).

Who checks what (`backend/recheck.py`): facts whose source is Viator or Geoapify are fetched again by the code through the same API (Viator: the product and its schedule, by the product code in the link; Geoapify: the stored URL with our key) and compared: price amount, currency, per and label, rating and review count, hours, coordinates and wheelchair access. A rating within ±0.1 stars and up to 5% more reviews still match (fewer reviews is a difference), and the note says "within tolerance". A difference is contradicted with its fields (`price.amount`, `rating.review_count`, `opening_hours`, `location`, `accessibility.wheelchair`…); no answer, an inactive product, a link without a product code or a price in another currency than the schedule is not_sure. The verifier agent gets only the facts from web pages. One verdict per experience: contradicted if either contradicts, confirmed only if both confirm, otherwise not_sure; its `note` starts "Checked by the code" for the code's part, and `url_read` / `passage` come from the page the agent read.

### 3f. User and final status

| Field | Who | Values |
|---|---|---|
| `user.status` | user | kept / removed (suggestions start as kept up to the pace limit per day, best fit first; the rest start removed) |
| `user.alternative` | code | `true` on a candidate the code left out to keep the pace, or because it is the same place as one kept; gone once the user keeps or removes it |
| `user.same_as` | code | on an alternative left out for the same place (or the same visit, entry included): the id of the kept experience it repeats; the `overlap` check says "Same place as <name>"; gone once the user keeps or removes it |
| `user.position` | user | order within the day after reordering; not used yet (no reordering), always null |
| `cost_eur` | code | the item's cost in EUR in the budget's unit (per person or total, as the user chose), a 2-place string (`"30.00"`); null when it can't be counted (no price, or a currency with no rate) |
| `status` | code | **verified** (all checks ok + confirmed) / **to_check** (any warn or not_sure: shown with a note, the user decides) / **rejected** (any fail or contradicted: not shown) |

## 4. JSON the agents must return

Each agent returns its data by calling one tool with exactly this shape. The code validates it with the same schema; if it's wrong, the errors go back to the agent to fix.

### Researcher: `deliver_experiences`

Returns up to 15 experiences, best fit first, with layers 3a, 3b and 3c: fewer when fewer are real, never padded (an empty list is allowed). Example values are illustrative, not real data.

```json
{
  "experiences": [
    {
      "id": "alfama-food-walk",
      "name": "Alfama food walk",
      "description": "Taste pastries, cheese and ginjinha in the old town.",
      "category": "food",
      "tags": ["food tour", "walking tour"],
      "location": {
        "city": "Lisbon",
        "address": "Largo do Chafariz de Dentro, Lisbon",
        "lat": 38.7115,
        "lng": -9.1295,
        "timezone": "Europe/Lisbon",
        "source": { "provider": "geoapify", "url": "https://api.geoapify.com/…", "retrieved_at": "2026-11-17T14:42:05+01:00", "quote": null }
      },
      "duration_min": 180,
      "price": {
        "amount": 35.0,
        "currency": "EUR",
        "per": "person",
        "label": null,
        "amount_eur": null,
        "fx": null,
        "source": { "provider": "viator", "url": "https://www.viator.com/…", "retrieved_at": "2026-11-17T14:42:00+01:00", "quote": null }
      },
      "opening_hours": {
        "text": "Daily 10:00 and 14:00",
        "slots": ["10:00", "14:00"],
        "source": { "provider": "web", "url": "https://…", "retrieved_at": "2026-11-17T14:43:10+01:00", "quote": "Tours depart daily at 10:00 and 14:00." }
      },
      "months": [],
      "min_age": null,
      "rating": {
        "value": 4.7,
        "scale": 5,
        "review_count": 1243,
        "source": { "provider": "viator", "url": "https://www.viator.com/…", "retrieved_at": "2026-11-17T14:42:00+01:00", "quote": null }
      },
      "indoor_outdoor": "outdoor",
      "accessibility": { "wheelchair": "unknown", "notes": null, "source": null },
      "suitable_for": { "values": ["friends", "couple"], "kind": "suggestion" },
      "booking_url": "https://www.viator.com/…",
      "photo_url": "https://…",
      "certainty": "high",
      "doubts": null,
      "best_time": { "slot": "morning", "start": "10:00", "reason": "Markets are freshest in the morning", "kind": "suggestion" },
      "why_fits": { "text": "You picked food", "kind": "suggestion" },
      "schedule": { "day": 1, "start": "10:00", "end": "13:00" }
    }
  ]
}
```

### Verifier: `deliver_verdicts`

```json
{
  "verdicts": [
    { "id": "alfama-food-walk", "verdict": "confirmed", "url_read": "https://…", "passage": "Tours depart daily at 10:00 and 14:00.", "contested_fields": [], "note": "Hours match; price shown as from €35." }
  ]
}
```

Rules for both:
- Missing fact → `null` or `"unknown"`, never a guess.
- Every non-null fact block has a `source`; web facts also have a `quote`.
- Prices are numbers as the source states them, in its currency. The agent never converts or adds up: the code does.
- Every AI field has `"kind": "suggestion"`.
- An experience without `lat`/`lng` or `booking_url` is dropped by the code, not repaired by the AI.

## 5. The pipeline (who fills what, in order)

1. **Questionnaire** → `profile`.
2. **Researcher agent** (APIs + web search) → `experiences` (up to 15) with facts, honesty, suggestions.
3. **Code** → schema check (sent back to the agent if wrong), currency conversion, the checks in 3d.
4. **Verifier agent** → one verdict per experience.
5. **Code** → final `status`; rejected ones are hidden.
6. **User** → keeps, removes, reorders.
7. **Code** → `totals`, then the brochure.

Every step adds a line to `steps`, so the user (and your professor) can see the loop.

## 6. Sources (checked 17 Nov 2026)

### Used

| Source | What we take | Cost | Key | Limits |
|---|---|---|---|---|
| **Viator Partner API, Basic Access** | experiences: name, description, tags, "from" price + currency, rating + review count, photos, product URL (= booking link) | free | yes: free affiliate account → Tools → Affiliate API, after email verification | Basic Access covers a subset of endpoints (product search, destinations, tags); bookings happen on viator.com |
| **Geoapify** (OpenStreetMap data) | coordinates, address, timezone, opening hours and wheelchair info where OSM has them; routing for distances on the map | free plan | yes: free account, no credit card | 3,000 credits/day, 5 requests/second; attribution to Geoapify and OpenStreetMap required |
| **Frankfurter** | exchange rates for `amount_eur` | free | no key | daily reference rates (ECB and other central banks), not live quotes |
| **Tavily** (web search for agents) | experiences not on Viator, last-minute requests, official pages for hours, prices, minimum age | free plan | yes: free account, no credit card | 1,000 credits/month (basic search = 1 credit) |
| **Official websites** of museums, attractions, tourism boards | facts when they are the original source; preferred over blogs and aggregators | free | — | reached through Tavily; the page URL and a copied quote go in `source` |

Alternative to Tavily if the course gives an API budget: Claude's own web search tool (about $10 per 1,000 searches), with a cost cap per trip.

### Checked and not used

| Source | Why not |
|---|---|
| GetYourGuide Partner API | No public self-serve access: the access token is issued by GetYourGuide on request. |
| Tiqets Distributor API | Free, but aimed at distribution partners; about 200 orders a month is the stated minimum. |
| Amadeus Tours & Activities | The Amadeus self-service portal was shut down on 17 July 2026 and its API keys disabled. |
| Google Places API | Rating, review count, opening hours and price are "Enterprise" fields (1,000 free calls/month) and need a Google Cloud billing account. Possible later if Geoapify isn't enough. |

### Keys go in `.env`, never in the code or on GitHub

Add these lines to `.env.example` (empty) and to your own `.env` (with the real keys):

```
VIATOR_API_KEY=
GEOAPIFY_API_KEY=
TAVILY_API_KEY=
```

## 7. Recording where every fact came from

1. **In the data:** every fact block carries its own `source` (provider, URL, time retrieved, quote for web pages). The app shows it next to the value: "€35 · Viator · checked 14:42".
2. **In a log:** every call to a source appends one line to `data/sources-log.jsonl`, written by the code, not the AI. Keys and personal data are never logged.

```json
{"at": "2026-11-17T14:42:00+01:00", "provider": "viator", "request": "products/search destination=Lisbon", "status": 200, "items": ["alfama-food-walk", "tram-28-viewpoints"]}
```

## 8. Still to do in step 3

- **Item 4:** the agent instructions (researcher and verifier) as prompt files, following these rules, plus a single-search mode for last-minute requests.
- **Item 5:** `data/samples/<city>.json` for the test destinations (Lisbon, London, Matera): up to 25 real places each, mixed so every interest can have a few, never padded, fetched from the sources above in this format (facts only; `best_time`, `why_fits` and `schedule` come later from the agent). `scripts/build_sample_places.py <city>` writes the Geoapify places; `scripts/build_sample.py <city>` then puts up to 15 Viator experiences (production) first and keeps those places, unchanged, up to 25, leaving out the later of two that are the same place (the trip's `overlap` rule; on 24 Nov this removed Ipogeo MateraSum, 5 duplicate Jerónimos/São Jorge items in Lisbon and a second Frameless in London). Viator items are placed only from Viator's own meeting-point coordinates: most products give only a Google place id or a hotel pickup, so Matera has 1.
