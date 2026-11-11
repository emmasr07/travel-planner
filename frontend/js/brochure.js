// Brochure: builds the day-by-day plan from the experiences kept on the list page (MOCK_TRIP minus removed ones).

(function () {
  const trip = MOCK_TRIP;
  const REMOVED_KEY = "tp.removed";
  const ANSWERS_KEY = "tp.answers";
  const GROUP_LABELS = { solo: "Solo", couple: "Couple", friends: "Friends", family: "Family" };

  // ---- helpers ----
  function readJSON(key, fallback) {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  function euro(amount, currency = "EUR") {
    return new Intl.NumberFormat("en-IE", {
      style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 2
    }).format(amount);
  }

  function clockTime(iso) {
    return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: trip.timeZone }).format(new Date(iso));
  }

  function checkedOn(iso) {
    const date = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: trip.timeZone }).format(new Date(iso));
    return `${date}, ${clockTime(iso)}`;
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Calendar dates are handled in UTC so no time zone can shift the day.
  function parseDate(s) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }

  function shortDateRange(start, end) {
    const a = parseDate(start), b = parseDate(end);
    const fmt = (d, opts) => new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" }).format(d);
    if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
      return `${fmt(a, { day: "numeric" })}–${fmt(b, { day: "numeric", month: "short" })}`;
    }
    return `${fmt(a, { day: "numeric", month: "short" })} – ${fmt(b, { day: "numeric", month: "short" })}`;
  }

  // "Thu 14 May" for trip day n (day 1 = start date).
  function dayDate(n) {
    const d = parseDate(trip.startDate);
    d.setUTCDate(d.getUTCDate() + n - 1);
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(d);
  }

  // Local end time from a local "HH:MM" start and a duration in minutes.
  function endTime(start, durationMin) {
    const [h, m] = start.split(":").map(Number);
    const total = (h * 60 + m + durationMin) % (24 * 60);
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  }

  function groupLabel(g) {
    return g.type === "solo" ? "Solo" : `${GROUP_LABELS[g.type]} (${g.size})`;
  }

  // Same budget rule as the list page: the questionnaire answer if given, otherwise the mock trip's budget.
  function currentBudget() {
    const answers = readJSON(ANSWERS_KEY, {});
    const amount = Number(answers.budgetAmount);
    if (amount > 0) return { amount, per: answers.budgetPer === "total" ? "total" : "person" };
    return { amount: trip.budget.amount, per: trip.budget.per };
  }

  // Display-only sum with mock data (in cents). Once the API exists, the total comes from backend/budget.py.
  function usedAmount(kept, budget) {
    const perPersonCents = kept.reduce((sum, e) => sum + Math.round(e.price * 100), 0);
    const cents = budget.per === "total" ? perPersonCents * trip.group.size : perPersonCents;
    return cents / 100;
  }

  // ---- data ----
  const removed = new Set(readJSON(REMOVED_KEY, []));
  const kept = trip.experiences
    .filter((e) => !removed.has(e.id))
    .sort((a, b) => a.day - b.day || a.start.localeCompare(b.start))    // visiting order
    .map((e, i) => ({ ...e, stop: i + 1 }));

  const days = [...new Set(kept.map((e) => e.day))];

  // ---- header ----
  document.getElementById("title").textContent = trip.destination;
  document.getElementById("subtitle").textContent =
    `${shortDateRange(trip.startDate, trip.endDate)} · ${groupLabel(trip.group)} · ` +
    `${kept.length} ${kept.length === 1 ? "experience" : "experiences"}`;

  if (kept.length === 0) {
    document.getElementById("plan").hidden = true;
    document.getElementById("empty").hidden = false;
    return;
  }

  // ---- day by day ----
  document.getElementById("days").innerHTML = days.map((day) => `
    <section class="day" aria-labelledby="day-${day}">
      <h2 class="day-title" id="day-${day}"><span class="day-dot day-${day}" aria-hidden="true"></span>Day ${day} · ${dayDate(day)}</h2>
      <ol class="plain stops">
        ${kept.filter((e) => e.day === day).map((e) => `
          <li class="card stop">
            <span class="pin day-${e.day}"><span class="visually-hidden">Stop </span>${e.stop}</span>
            <div class="stop-body">
              <p class="stop-time">${e.start} – ${endTime(e.start, e.durationMin)}</p>
              <h3>${esc(e.name)}</h3>
              <p class="stop-reason">${esc(e.timeReason)}</p>
              <p class="stop-price"><strong>${euro(e.price, e.currency)}</strong> <span class="caption">· ${esc(e.source)} · checked ${clockTime(e.checkedAt)}</span></p>
            </div>
            <button type="button" class="btn btn-primary" aria-disabled="true" title="Booking links are coming soon" aria-label="Book ${esc(e.name)}">Book</button>
          </li>`).join("")}
      </ol>
    </section>`).join("");

  // ---- map and legend ----
  const map = document.getElementById("map");
  map.setAttribute("aria-label", `Map placeholder with ${kept.length} numbered stops`);
  map.insertAdjacentHTML("beforeend", kept.map((e) =>
    `<span class="pin day-${e.day}" style="left: ${e.map.x}%; top: ${e.map.y}%">${e.stop}</span>`
  ).join(""));
  document.getElementById("legend").innerHTML = days.map((day) =>
    `<li><span class="day-dot day-${day}" aria-hidden="true"></span>Day ${day}</li>`
  ).join("");

  // ---- total ----
  const budget = currentBudget();
  const used = usedAmount(kept, budget);
  document.getElementById("total").textContent = euro(used);
  document.getElementById("total-of").textContent =
    `of ${euro(budget.amount)} ${budget.per === "total" ? `total for ${trip.group.size}` : "per person"}`;
  if (used > budget.amount) {
    const note = document.getElementById("over-note");
    note.textContent = `Over budget by ${euro(used - budget.amount)}`;
    note.hidden = false;
  }

  // Oldest price check among the kept experiences.
  const oldest = kept.map((e) => e.checkedAt).sort((a, b) => new Date(a) - new Date(b))[0];
  document.getElementById("checked-note").textContent =
    `Prices checked on ${checkedOn(oldest)}. They may change before you book.`;
})();
