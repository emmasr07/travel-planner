// Experience list: shows the trip from GET /api/trips/{id}. While the backend researches, checks and verifies, it
// polls every 2 seconds and shows the steps; then it renders the experiences. Keep/Remove/Restore and time changes go
// to the API, which re-runs the checks and returns the trip with its totals (all money is counted in backend/budget.py).

(function () {
  const BUSY = ["researching", "checking", "verifying"];
  const POLL_MS = 2000;
  const GROUP_LABELS = { solo: "Solo", couple: "Couple", friends: "Friends", family: "Family", business: "Business" };
  const SLOT_LABELS = {
    early_morning: "Early morning", morning: "Morning", midday: "Midday", afternoon: "Afternoon",
    sunset: "Sunset", evening: "Evening", night: "Night"
  };
  const PROVIDERS = { viator: "Viator", geoapify: "Geoapify (OpenStreetMap)", web: "Web page", frankfurter: "Frankfurter" };
  const STATUS_TEXT = {
    researching: "Looking for experiences that match your answers.",
    checking: "Checking the schema, prices, dates, opening hours and ages.",
    verifying: "Double-checking every source."
  };

  const tripId = TP.tripId();
  const grid = document.getElementById("kept-grid");
  const removedList = document.getElementById("removed-list");
  const statusCard = document.getElementById("status");
  const budgetCard = document.getElementById("budget");
  const buildBtn = document.getElementById("build");
  const fitBtn = document.getElementById("fit");
  const actionError = document.getElementById("action-error");

  let trip = null;
  let editing = null;    // id of the card whose time is being changed
  let busy = false;      // a change is on its way to the API

  // ---- helpers ----
  function esc(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Formats an amount the API or a source gave; never adds anything up.
  function money(amount, currency = "EUR") {
    return new Intl.NumberFormat("en-IE", {
      style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 2
    }).format(Number(amount));
  }

  function clockTime(iso) {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit", minute: "2-digit", timeZone: trip.profile.timezone || undefined
    }).format(new Date(iso));
  }

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

  function tripDayCount() {
    return Math.round((parseDate(trip.profile.end_date) - parseDate(trip.profile.start_date)) / 86400000) + 1;
  }

  // "Fri 4 Dec" for trip day n (day 1 = start date); calendar dates in UTC so no time zone shifts the day.
  function dayDate(n) {
    const d = parseDate(trip.profile.start_date);
    d.setUTCDate(d.getUTCDate() + n - 1);
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(d);
  }

  function groupLabel(p) {
    return p.group_type === "solo" ? "Solo" : `${GROUP_LABELS[p.group_type]} (${p.group_size})`;
  }

  function duration(min) {
    const hours = min / 60;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`;
  }

  function showError(message) {
    actionError.textContent = message ? message.charAt(0).toUpperCase() + message.slice(1) : "";
    actionError.hidden = !message;
  }

  function visible() {
    return trip.experiences.filter((e) => e.status !== "rejected");
  }

  // ---- loading the trip ----
  async function load() {
    try {
      trip = await TP.api.get(TP.tripPath(tripId));
    } catch (error) {
      showStatus("We couldn't load your trip", `${esc(error.message)} <a href="plan.html">Plan a new trip</a>.`);
      return;
    }
    render();
    if (BUSY.includes(trip.status)) setTimeout(load, POLL_MS);
  }

  function showStatus(title, html, steps) {
    statusCard.innerHTML = `
      <h2>${esc(title)}</h2>
      <p class="muted">${html}</p>
      ${steps && steps.length ? `<ul class="plain">${steps.map((s) =>
        `<li class="caption">${esc(clockTime(s.at))} · ${esc(s.who)} · ${esc(s.text)}</li>`).join("")}</ul>` : ""}`;
    statusCard.hidden = false;
    grid.innerHTML = "";
    removedList.hidden = true;
    budgetCard.hidden = true;
  }

  // ---- rendering ----
  const CLOCK_ICON = '<svg class="icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.25"/><path d="M8 4.75V8l2.25 1.5"/></svg>';

  function timeBadge(e) {
    const s = e.schedule;
    const suggested = e.best_time && e.best_time.start === s.start;
    const slot = suggested ? SLOT_LABELS[e.best_time.slot] : "Your time";
    const length = e.duration_min ? `${s.start} · ${duration(e.duration_min)}` : `${s.start}–${s.end}`;
    const reason = suggested ? e.best_time.reason : "You picked this time";
    return `
      <button type="button" class="time-badge" data-action="edit-time" aria-label="Change the time of ${esc(e.name)}">
        <span class="when">${CLOCK_ICON}Day ${s.day} · ${esc(slot)}, ${esc(length)}</span>
        <span class="reason">${esc(reason)}</span>
      </button>`;
  }

  function timeEditor(e) {
    const s = e.schedule;
    const days = Array.from({ length: tripDayCount() }, (_, i) => i + 1).map((n) =>
      `<option value="${n}"${n === s.day ? " selected" : ""}>Day ${n} · ${esc(dayDate(n))}</option>`).join("");
    return `
      <div class="field-row">
        <label class="field">
          <span class="field-label">Day</span>
          <select class="input" data-edit="day">${days}</select>
        </label>
        <label class="field">
          <span class="field-label">Start</span>
          <input class="input" type="time" data-edit="start" value="${esc(s.start)}" step="300">
        </label>
      </div>
      <div class="actions">
        <button type="button" class="btn btn-primary btn-sm" data-action="save-time">Save time</button>
        <button type="button" class="btn btn-secondary btn-sm" data-action="cancel-time">Cancel</button>
      </div>`;
  }

  function sourceCaption(source) {
    if (!source) return "no source";
    return `${esc(PROVIDERS[source.provider] || source.provider)} · checked ${esc(clockTime(source.retrieved_at))}`;
  }

  // The price as the source states it, with its source and checked-at time; never a price without them.
  function priceRow(e) {
    const p = e.price;
    if (p.per === "free") {
      return `<span class="price">Free</span><span class="caption">${sourceCaption(p.source)}</span>`;
    }
    if (p.amount === null || p.amount === undefined || !p.source) {
      return '<span class="price">No price yet</span><span class="caption">No source states a price · not counted</span>';
    }
    const per = p.per === "group" ? "per group" : "per person";
    const inEuro = p.currency !== "EUR" && p.amount_eur !== null && p.fx
      ? ` · ${esc(money(p.amount_eur))} at the ${esc(p.fx.date)} rate (Frankfurter)` : "";
    const notConverted = p.currency !== "EUR" && p.amount_eur === null ? " · not converted, not counted" : "";
    return `<span class="price">${esc(money(p.amount, p.currency))}</span>
      <span class="caption">${per} · ${sourceCaption(p.source)}${inEuro}${notConverted}</span>`;
  }

  function note(e) {
    if (e.status !== "to_check") return "";
    const warns = e.checks.filter((c) => c.result === "warn").map((c) => c.detail);
    const verdict = e.verdict && e.verdict.verdict !== "confirmed" ? [e.verdict.note] : [];
    const items = [...warns, ...verdict];
    return items.length ? `<p class="caption">To check: ${esc(items.join(" · "))}</p>` : "";
  }

  function keptCard(e) {
    const name = esc(e.name);
    const photo = e.photo_url
      ? `<img class="photo" src="${esc(e.photo_url)}" alt="">`
      : `<div class="photo photo-placeholder" role="img" aria-label="No photo of ${name}">Photo</div>`;
    return `
      <article class="card experience" data-id="${esc(e.id)}">
        ${photo}
        <div class="body">
          <div class="text">
            <h3 class="name">${name}</h3>
            <p class="desc">${esc(e.description || e.location.address || e.location.city)}</p>
          </div>
          ${editing === e.id ? timeEditor(e) : timeBadge(e)}
          <div class="price-row">${priceRow(e)}</div>
          <p class="why">${esc(e.why_fits.text)}</p>
          ${note(e)}
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
    const freed = e.cost_eur === null ? "not counted in your budget" : `${esc(money(e.cost_eur))} freed up`;
    return `
      <article class="card experience is-removed" data-id="${esc(e.id)}">
        <div>
          <h3 class="name">${name}</h3>
          <p class="caption">Removed · ${freed}</p>
        </div>
        <button type="button" class="btn btn-secondary btn-sm btn-accent" data-action="restore" aria-label="Restore ${name}">Restore</button>
      </article>`;
  }

  function renderBudget(kept) {
    const t = trip.totals;
    const budget = Number(t.budget);
    document.getElementById("budget-used").textContent = money(t.used);
    document.getElementById("budget-of").textContent = `of ${money(t.budget)}`;
    document.getElementById("budget-per").textContent = t.per === "total" ? `total for ${t.group_size}` : "per person";
    // Bar width only: the totals themselves come from backend/budget.py.
    document.getElementById("budget-fill").style.width = `${Math.min(Number(t.used) / budget, 1) * 100}%`;
    document.getElementById("budget-left").textContent =
      t.over ? `${money(t.over_by)} over budget` : `${money(t.left)} left`;

    const track = document.getElementById("budget-track");
    track.setAttribute("aria-valuemax", t.budget);
    track.setAttribute("aria-valuenow", String(Math.min(Number(t.used), budget)));
    track.setAttribute("aria-valuetext", `${money(t.used)} of ${money(t.budget)}`);

    budgetCard.classList.toggle("is-over", t.over);
    buildBtn.disabled = t.over || t.kept === 0 || !["ready", "done"].includes(trip.status);
    fitBtn.hidden = !t.over;

    document.getElementById("kept-title").textContent = `Kept (${t.kept})`;
    document.getElementById("kept-list").innerHTML = kept.map((e) =>
      `<li><span>${esc(e.name)}</span><span class="cost">${e.cost_eur === null ? "no price" : esc(money(e.cost_eur))}</span></li>`
    ).join("");
    const notCounted = document.getElementById("not-counted");
    const n = t.not_counted.length;
    notCounted.textContent = n ? `${n} without a price ${n === 1 ? "is" : "are"} not counted.` : "";
    notCounted.hidden = n === 0;
    budgetCard.hidden = false;
  }

  function render() {
    const p = trip.profile;
    document.getElementById("title").textContent =
      BUSY.includes(trip.status) ? `Finding experiences in ${p.destination}` : `Your experiences in ${p.destination}`;
    const intro = `${shortDateRange(p.start_date, p.end_date)} · ${groupLabel(p)}`;

    if (BUSY.includes(trip.status)) {
      document.getElementById("subtitle").textContent = `${intro} · ${trip.status}…`;
      showStatus(trip.status.charAt(0).toUpperCase() + trip.status.slice(1), esc(STATUS_TEXT[trip.status]), trip.steps);
      return;
    }
    if (trip.status === "failed") {
      document.getElementById("subtitle").textContent = intro;
      showStatus("Something went wrong", `${esc(trip.error)}. <a href="plan.html">Try again</a>.`, trip.steps);
      return;
    }
    const shown = visible();
    if (shown.length === 0) {
      document.getElementById("subtitle").textContent = intro;
      showStatus("No experiences found",
        `We found nothing in ${esc(p.destination)} for ${esc(p.interests.join(", "))}, and we never invent one. ` +
        'Try widening your interests or your budget: <a href="plan.html">edit my answers</a>.');
      return;
    }

    statusCard.hidden = true;
    const kept = shown.filter((e) => e.user.status === "kept");
    const gone = shown.filter((e) => e.user.status !== "kept");
    const hidden = trip.experiences.length - shown.length;
    document.getElementById("subtitle").textContent =
      `${intro} · ${kept.length} picked for you` +
      (hidden ? `, ${hidden} hidden because ${hidden === 1 ? "it" : "they"} failed a check` : "") +
      (trip.mode === "demo" ? ". Demo data, not verified" : "") +
      ". Click a time to change it.";

    grid.innerHTML = kept.map(keptCard).join("");
    removedList.innerHTML = gone.map(removedCard).join("");
    removedList.hidden = gone.length === 0;
    renderBudget(kept);
  }

  // ---- actions ----
  async function change(expId, payload, focusAction) {
    if (busy) return;
    busy = true;
    showError("");
    try {
      trip = await TP.api.post(TP.tripPath(tripId, `/experiences/${encodeURIComponent(expId)}`), payload);
      editing = null;
      render();
      // Keep keyboard focus on the same experience after it moves.
      const target = focusAction && document.querySelector(`[data-id="${CSS.escape(expId)}"] [data-action="${focusAction}"]`);
      if (target) target.focus();
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
    }
  }

  document.querySelector(".with-aside .main").addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || !trip) return;
    const card = button.closest("[data-id]");
    const id = card.dataset.id;
    const action = button.dataset.action;
    if (action === "remove") change(id, { status: "removed" }, "restore");
    if (action === "restore") change(id, { status: "kept" }, "remove");
    if (action === "edit-time") {
      editing = id;
      render();
      const select = document.querySelector(`[data-id="${CSS.escape(id)}"] [data-edit="day"]`);
      if (select) select.focus();
    }
    if (action === "cancel-time") {
      editing = null;
      render();
    }
    if (action === "save-time") {
      const day = Number(card.querySelector('[data-edit="day"]').value);
      const start = card.querySelector('[data-edit="start"]').value;
      if (!start) {
        showError("Pick a start time.");
        return;
      }
      change(id, { day, start }, "edit-time");
    }
  });

  fitBtn.addEventListener("click", async () => {
    if (busy) return;
    showError("");
    let proposal;
    try {
      proposal = await TP.api.post(TP.tripPath(tripId, "/fit-budget"));
    } catch (error) {
      showError(error.message);
      return;
    }
    if (!proposal.remove.length) {
      showError("You are already within your budget.");
      return;
    }
    const lines = proposal.remove.map((r) => `• ${r.name} (${money(r.cost_eur)})`).join("\n");
    const ok = window.confirm(
      `To fit your budget, remove:\n${lines}\n\nNew total: ${money(proposal.used_after)} of ${money(proposal.budget)}.`);
    if (!ok) return;
    for (const r of proposal.remove) {
      await change(r.id, { status: "removed" });
    }
  });

  buildBtn.addEventListener("click", async () => {
    if (buildBtn.disabled || busy) return;
    if (trip.status === "done") {
      window.location.href = `brochure.html?trip=${encodeURIComponent(tripId)}`;
      return;
    }
    busy = true;
    showError("");
    try {
      await TP.api.post(TP.tripPath(tripId, "/brochure"));
      window.location.href = `brochure.html?trip=${encodeURIComponent(tripId)}`;
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
    }
  });

  if (!tripId) {
    document.getElementById("subtitle").textContent = "";
    statusCard.innerHTML = '<h2>No trip yet</h2><p class="muted">Answer seven quick questions and we\'ll find experiences for you. <a href="plan.html">Plan my trip</a>.</p>';
    statusCard.hidden = false;
  } else {
    load();
  }
})();
