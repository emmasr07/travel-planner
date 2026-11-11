# UX flow: Travel Itinerary Planner

Scope for now: **experiences only** (activities, tours, food, events). No flights, no hotels.
Rule that shapes every screen: **the AI never writes a price.** Every price comes from a search API and shows its source and the time it was checked.

## 1. Flow

Home → Questionnaire → Experience list → (select / remove / swap / add) → Brochure → Share

| Screen | User goal | Moves on when |
|---|---|---|
| Home | Understand what the app does | Clicks "Plan my trip" |
| Questionnaire | Tell us about the trip | Answers all required questions, clicks "Find experiences" |
| Experience list | Pick what to do | Clicks "Build my trip" (only when within budget) |
| Brochure | See and share the final plan | Clicks "Share link" or "Download PDF" |

Back navigation is always allowed. Going back to the questionnaire keeps the answers.

## 2. Questionnaire

One question per screen, with a progress bar (step 3 of 7).

| # | Question | Input | Required |
|---|---|---|---|
| 1 | Where are you going? | City text field | Yes |
| 2 | When? | Start and end date | Yes |
| 3 | Who's going? | Buttons: solo / couple / friends / family, plus group size | Yes |
| 4 | Age | Ranges: 18–24 / 25–34 / 35–49 / 50+ | Yes |
| 5 | What do you want from this trip? | Multi-select chips: culture, food, nature, nightlife, relax, adventure, shopping | Yes (at least 1) |
| 6 | Budget for experiences | Number in €, toggle per person / total | Yes |
| 7 | Anything else? | Pace slider (chill ↔ packed) and optional free text (e.g. "no museums", "wheelchair access") | No |

Answers are saved as structured data (not one free-text blob) so the AI and the budget check can use them.

## 3. Experience list

**Top bar:** destination, dates, and a **budget bar**: `€180 of €250 used`. It turns red when over budget.

**Each experience card shows:**
- Name, photo, one-line description
- Suggested day, best time of day, and duration (e.g. "Day 2 · sunset, 18:30 · 2h"), with a short reason ("best light at sunset", "less crowded early morning")
- **Price, source, checked at** (e.g. "€35 · GetYourGuide · checked 10:42")
- "Why this fits you" in one line, linked to their answers (e.g. "You picked food")
- Buttons: ✓ Keep · ✕ Remove · ⇄ Swap

First load: about 8–12 suggestions, all marked "Keep" by default.

## 4. Selecting and modifying

- **Change time:** tapping the suggested time lets the user pick another slot. If the new slot clashes with another experience that day, show a warning.
- **Remove:** the card greys out and can be restored. The budget bar updates instantly.
- **Swap:** opens 2–3 alternatives of a similar type and price. Picking one replaces the card.
- **Add:** a "+ More ideas" button loads more suggestions. Users can't type in their own priced item, because prices must come from a source.
- **Over budget:** the bar turns red, "Build my trip" is disabled, and a "Fit it to my budget" button appears. The app proposes removals or cheaper swaps, and the user confirms.
- **Empty result:** if the search finds nothing, say so plainly and suggest widening the interests or the budget. Never invent experiences.

## 5. Brochure

- Header: destination, dates, group, cover photo
- **Map** of all experiences, with numbered pins in visiting order and one colour per day
- Day by day: each experience with suggested time slot (and why), price, source, and a **Book** link. Experiences on the same day are ordered by time.
- Footer: total cost compared with budget, plus "Prices checked on [date, time]; they may change."
- Actions: **Share link** · **Download PDF** · **Edit trip** (back to the list)

## Decisions

- The brochure includes a map of the experiences.
- The app suggests the best time of day for each experience and says why. The user can change it.

## Open questions

- Which activities API? (decide in the backend step)
