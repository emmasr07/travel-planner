# Frontend design spec: Travel Planner

Read this together with `docs/ux-flow.md` (what each screen does) and the images in `docs/prototype/` (what each screen looks like).

## Look in one line
Clean and modern: light grey page, white cards, near-black text, one blue accent, Inter font, soft shadows, pill buttons, lots of white space.

## Rules
1. Every page links `css/styles.css` and the Inter font from Google Fonts. Use its variables and classes; never type a hex colour in HTML.
2. Plain HTML, CSS and JavaScript. No framework, no build step, no CSS library.
3. One accent: only `--blue` for actions, links and selected states. Map days use `--day-1/2/3`.
4. Every price is shown with its source and checked-at time (`.caption`). Never show a price without them.
5. Until the backend exists, pages read example data from `frontend/js/mock-data.js`. The same shape will later come from the API.
6. Laptop first (content max 1200px, `.container`), but every page must still work at phone width (the side panel stacks under the main column).
7. Accessible: real `<button>` and `<a>`, `aria-pressed` on chips, `aria-label` on icon-only buttons, visible focus.

## Pages (one HTML file each in `frontend/`)

| File | Screen | Key parts (classes) |
|---|---|---|
| `index.html` | Home | `.site-header`, centred `.display` headline "Your trip, sorted in minutes.", `.btn-primary.btn-lg` "Plan my trip", preview card, "How it works" in `.section-alt` with three `.card`s |
| `plan.html` | Questionnaire | `.site-header` + `.progress`, one `.card` per question, 7 steps (see ux-flow.md), `.chips` with `.chip.is-on`, Back (`.btn-secondary`) and Next (`.btn-primary`). Answers kept in `sessionStorage` |
| `experiences.html` | Experience list | `h1` + caption, `.with-aside`: `.card-grid` of `.card.experience` (photo, `h3`, description, `.time-badge`, `.price` + source caption, `.why`, Keep / Remove / Swap), removed cards as `.experience.is-removed` with Restore, "More ideas" button; aside = `.card.budget` with `.budget-track`, kept list, "Build my trip" |
| `brochure.html` | Brochure | Title block (`.eyebrow`, `h1`, caption), cover photo, `.with-aside`: day sections (`h2` + coloured dot, one `.card` per experience with `.pin`, time, name, reason, price + source, "Book" `.btn-primary`); aside = map card with `.pin`s + legend, total card with "Prices checked on…" note. Header actions: Edit trip, Download PDF, Share link |

## Behaviour to build now (with mock data)
- Questionnaire chips toggle on and off; Next is disabled until a required question is answered.
- Experience list: Remove greys a card out (Restore brings it back); the budget total, bar and "€X left" update instantly; over budget the bar turns red, "Build my trip" is disabled and "Fit it to my budget" appears.
- Brochure is built from the kept experiences, grouped by day and ordered by time.

## Later (not now)
Real prices from the activities API, the AI suggestions, the real map, Swap alternatives, PDF export and share links.
