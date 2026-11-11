// Home page: fills the example-trip preview card (map pins, Day 1 items, budget bar) from MOCK_TRIP.

(function () {
  const trip = MOCK_TRIP;

  function euro(amount, currency = "EUR") {
    return new Intl.NumberFormat("en-IE", {
      style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 2
    }).format(amount);
  }

  function clockTime(iso) {
    return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: trip.timeZone }).format(new Date(iso));
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Days in the trip, counting both the first and the last day (calendar dates, no time zone shift).
  function tripDays(start, end) {
    const toUTC = (s) => { const [y, m, d] = s.split("-").map(Number); return Date.UTC(y, m - 1, d); };
    return Math.round((toUTC(end) - toUTC(start)) / 86400000) + 1;
  }

  // Visiting order: by day, then by local start time.
  const ordered = [...trip.experiences].sort((a, b) => a.day - b.day || a.start.localeCompare(b.start));

  document.getElementById("preview-city").textContent = trip.destination;
  document.getElementById("preview-meta").textContent =
    `${tripDays(trip.startDate, trip.endDate)} days · ${trip.group.size} ${trip.group.type}`;

  document.getElementById("preview-map").innerHTML = ordered.map((e, i) =>
    `<span class="pin day-${e.day}" style="left: ${e.map.x}%; top: ${e.map.y}%">${i + 1}</span>`
  ).join("");

  document.getElementById("preview-list").innerHTML = ordered.filter((e) => e.day === 1).map((e) => `
    <li>
      <div>
        <p class="name">${esc(e.name)}</p>
        <p class="caption">${euro(e.price, e.currency)} · ${esc(e.source)} · checked ${clockTime(e.checkedAt)}</p>
      </div>
      <span class="badge">${esc(e.timeOfDay)} ${e.start}</span>
    </li>`).join("");

  // Display-only sum of the example prices. Once the API exists, totals come from backend/budget.py.
  const used = trip.experiences.reduce((sum, e) => sum + Math.round(e.price * 100), 0) / 100;
  const budget = trip.budget.amount;
  document.getElementById("preview-used").textContent = `${euro(used)} of ${euro(budget)}`;
  document.getElementById("preview-left").textContent =
    used <= budget ? `${euro(budget - used)} left` : `${euro(used - budget)} over`;
  document.getElementById("preview-fill").style.width = `${Math.min(used / budget, 1) * 100}%`;
})();
