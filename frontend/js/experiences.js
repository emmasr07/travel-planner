// Experience list: renders MOCK_TRIP experiences, handles Remove/Restore and keeps the budget bar in sync.

(function () {
  const trip = MOCK_TRIP;
  const REMOVED_KEY = "tp.removed";
  const ANSWERS_KEY = "tp.answers";
  const GROUP_LABELS = { solo: "Solo", couple: "Couple", friends: "Friends", family: "Family" };

  const grid = document.getElementById("kept-grid");
  const removedList = document.getElementById("removed-list");
  const budgetCard = document.getElementById("budget");
  const buildBtn = document.getElementById("build");
  const fitBtn = document.getElementById("fit");

  // ---- helpers ----
  function readJSON(key, fallback) {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  function writeJSON(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage blocked */ }
  }

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

  function shortDateRange(start, end) {
    const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
    const a = parse(start), b = parse(end);
    const fmt = (d, opts) => new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" }).format(d);
    if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
      return `${fmt(a, { day: "numeric" })}–${fmt(b, { day: "numeric", month: "short" })}`;
    }
    return `${fmt(a, { day: "numeric", month: "short" })} – ${fmt(b, { day: "numeric", month: "short" })}`;
  }

  function groupLabel(g) {
    return g.type === "solo" ? "Solo" : `${GROUP_LABELS[g.type]} (${g.size})`;
  }

  function duration(min) {
    const hours = min / 60;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`;
  }

  // Budget from the questionnaire (step 6) if answered, otherwise the mock trip's budget.
  function currentBudget() {
    const answers = readJSON(ANSWERS_KEY, {});
    const amount = Number(answers.budgetAmount);
    if (amount > 0) return { amount, per: answers.budgetPer === "total" ? "total" : "person" };
    return { amount: trip.budget.amount, per: trip.budget.per };
  }

  // Display-only sum for the live budget bar with mock data (summed in cents).
  // Once the API exists, the authoritative total comes from backend/budget.py.
  function usedAmount(kept, budget) {
    const perPersonCents = kept.reduce((sum, e) => sum + Math.round(e.price * 100), 0);
    const cents = budget.per === "total" ? perPersonCents * trip.group.size : perPersonCents;
    return cents / 100;
  }

  // ---- state ----
  const knownIds = new Set(trip.experiences.map((e) => e.id));
  let removed = new Set(readJSON(REMOVED_KEY, []).filter((id) => knownIds.has(id)));

  function keptExperiences() {
    return trip.experiences.filter((e) => !removed.has(e.id));
  }

  // ---- rendering ----
  const CLOCK_ICON = '<svg class="icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.25"/><path d="M8 4.75V8l2.25 1.5"/></svg>';

  function keptCard(e) {
    const name = esc(e.name);
    return `
      <article class="card experience" data-id="${e.id}">
        <div class="photo photo-placeholder" role="img" aria-label="Photo of ${name} (placeholder)">Photo</div>
        <div class="body">
          <div class="text">
            <h3 class="name">${name}</h3>
            <p class="desc">${esc(e.description)}</p>
          </div>
          <button type="button" class="time-badge" aria-disabled="true" title="Changing the time is coming soon">
            <span class="when">${CLOCK_ICON}Day ${e.day} · ${esc(e.timeOfDay)}, ${e.start} · ${duration(e.durationMin)}</span>
            <span class="reason">${esc(e.timeReason)}</span>
          </button>
          <div class="price-row">
            <span class="price">${euro(e.price, e.currency)}</span>
            <span class="caption">${esc(e.source)} · checked ${clockTime(e.checkedAt)}</span>
          </div>
          <p class="why">You picked ${esc(e.interest)}</p>
          <div class="actions">
            <button type="button" class="btn btn-secondary btn-sm is-on" aria-pressed="true" aria-label="Keep ${name}">Keep</button>
            <button type="button" class="btn btn-secondary btn-sm" data-action="remove" aria-label="Remove ${name}">Remove</button>
            <button type="button" class="btn btn-secondary btn-sm" aria-disabled="true" title="Coming soon" aria-label="Swap ${name}">Swap</button>
          </div>
        </div>
      </article>`;
  }

  function removedCard(e) {
    const name = esc(e.name);
    return `
      <article class="card experience is-removed" data-id="${e.id}">
        <div>
          <h3 class="name">${name}</h3>
          <p class="caption">Removed · ${euro(e.price, e.currency)} freed up</p>
        </div>
        <button type="button" class="btn btn-secondary btn-sm btn-accent" data-action="restore" aria-label="Restore ${name}">Restore</button>
      </article>`;
  }

  function renderBudget(kept) {
    const budget = currentBudget();
    const used = usedAmount(kept, budget);
    const over = used > budget.amount;

    document.getElementById("budget-used").textContent = euro(used);
    document.getElementById("budget-of").textContent = `of ${euro(budget.amount)}`;
    document.getElementById("budget-per").textContent =
      budget.per === "total" ? `total for ${trip.group.size}` : "per person";
    document.getElementById("budget-fill").style.width = `${Math.min(used / budget.amount, 1) * 100}%`;
    document.getElementById("budget-left").textContent =
      over ? `${euro(used - budget.amount)} over budget` : `${euro(budget.amount - used)} left`;

    const track = document.getElementById("budget-track");
    track.setAttribute("aria-valuemax", String(budget.amount));
    track.setAttribute("aria-valuenow", String(Math.min(used, budget.amount)));
    track.setAttribute("aria-valuetext", `${euro(used)} of ${euro(budget.amount)}`);

    budgetCard.classList.toggle("is-over", over);
    buildBtn.disabled = over || kept.length === 0;
    fitBtn.hidden = !over;

    document.getElementById("kept-title").textContent = `Kept (${kept.length})`;
    document.getElementById("kept-list").innerHTML = kept.map((e) =>
      `<li><span>${esc(e.name)}</span><span class="cost">${euro(e.price, e.currency)}</span></li>`
    ).join("");
  }

  function render() {
    const kept = keptExperiences();
    const gone = trip.experiences.filter((e) => removed.has(e.id));

    document.getElementById("title").textContent = `Your experiences in ${trip.destination}`;
    document.getElementById("subtitle").textContent =
      `${shortDateRange(trip.startDate, trip.endDate)} · ${groupLabel(trip.group)} · ` +
      `${kept.length} picked for you. Click a time to change it.`;

    grid.innerHTML = kept.map(keptCard).join("");
    removedList.innerHTML = gone.map(removedCard).join("");
    removedList.hidden = gone.length === 0;
    renderBudget(kept);
  }

  // ---- actions ----
  function setRemoved(id, isRemoved) {
    isRemoved ? removed.add(id) : removed.delete(id);
    writeJSON(REMOVED_KEY, [...removed]);
    render();
    // Keep keyboard focus on the same experience after it moves.
    const action = isRemoved ? "restore" : "remove";
    const target = document.querySelector(`[data-id="${id}"] [data-action="${action}"]`);
    if (target) target.focus();
  }

  document.querySelector(".with-aside .main").addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const id = button.closest("[data-id]").dataset.id;
    if (button.dataset.action === "remove") setRemoved(id, true);
    if (button.dataset.action === "restore") setRemoved(id, false);
  });

  buildBtn.addEventListener("click", () => {
    if (buildBtn.disabled) return;
    writeJSON(REMOVED_KEY, [...removed]);
    window.location.href = "brochure.html";
  });

  render();
})();
