// Brochure: shows the sublist the backend built (POST /api/trips/{id}/brochure): the kept experiences by day and
// time, numbered stops on the map, real "Book" links, and the total from backend/budget.py.

(function () {
  const GROUP_LABELS = { solo: "Solo", couple: "Couple", friends: "Friends", family: "Family", business: "Business" };
  const PROVIDERS = { viator: "Viator", geoapify: "Geoapify (OpenStreetMap)", web: "Web page", frankfurter: "Frankfurter" };
  const DAY_COLOURS = 3;    // styles.css has --day-1 to --day-3; later days reuse them

  const tripId = TP.tripId();
  let trip = null;

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

  function checkedOn(iso) {
    const date = new Intl.DateTimeFormat("en-GB", {
      day: "numeric", month: "short", timeZone: trip.profile.timezone || undefined
    }).format(new Date(iso));
    return `${date}, ${clockTime(iso)}`;
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
    const d = parseDate(trip.profile.start_date);
    d.setUTCDate(d.getUTCDate() + n - 1);
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(d);
  }

  function colour(day) {
    return ((day - 1) % DAY_COLOURS) + 1;
  }

  function groupLabel(p) {
    return p.group_type === "solo" ? "Solo" : `${GROUP_LABELS[p.group_type]} (${p.group_size})`;
  }

  function priceLine(e) {
    const p = e.price;
    if (p.per === "free") return `<strong>Free</strong>`;
    if (p.amount === null || p.amount === undefined || !p.source) {
      return '<strong>No price yet</strong> <span class="caption">· no source states a price, not counted</span>';
    }
    const per = p.per === "group" ? "per group" : "per person";
    const source = `${esc(PROVIDERS[p.source.provider] || p.source.provider)} · checked ${esc(clockTime(p.source.retrieved_at))}`;
    return `<strong>${esc(money(p.amount, p.currency))}</strong> <span class="caption">· ${per} · ${source}</span>`;
  }

  function showEmpty(title, html) {
    document.getElementById("plan").hidden = true;
    document.getElementById("empty-title").textContent = title;
    document.getElementById("empty-text").innerHTML = html;
    document.getElementById("empty").hidden = false;
  }

  // Pins placed inside the stops' bounding box (the real map comes later).
  function pinPosition(e, box) {
    const spanLng = box.maxLng - box.minLng, spanLat = box.maxLat - box.minLat;
    const x = spanLng ? 10 + 80 * (e.location.lng - box.minLng) / spanLng : 50;
    const y = spanLat ? 10 + 80 * (box.maxLat - e.location.lat) / spanLat : 50;
    return { x: x.toFixed(1), y: y.toFixed(1) };
  }

  // ---- page ----
  function render() {
    const p = trip.profile;
    const listLink = `experiences.html?trip=${encodeURIComponent(tripId)}`;
    document.getElementById("edit-trip").href = listLink;
    document.getElementById("title").textContent = p.destination;

    if (trip.status !== "done" || !trip.brochure) {
      document.getElementById("subtitle").textContent = shortDateRange(p.start_date, p.end_date);
      showEmpty("Your brochure isn't built yet",
        `Keep the experiences you want, then use "Build my trip". <a href="${esc(listLink)}">Go back to your experiences</a>.`);
      return;
    }

    const byId = Object.fromEntries(trip.experiences.map((e) => [e.id, e]));
    const stops = trip.brochure.stops.map((s) => ({ ...byId[s.id], stop: s.stop, day: s.day, start: s.start, end: s.end }));
    const days = [...new Set(stops.map((e) => e.day))];

    document.getElementById("subtitle").textContent =
      `${shortDateRange(p.start_date, p.end_date)} · ${groupLabel(p)} · ` +
      `${stops.length} ${stops.length === 1 ? "experience" : "experiences"}`;

    // ---- day by day ----
    document.getElementById("days").innerHTML = days.map((day) => `
      <section class="day" aria-labelledby="day-${day}">
        <h2 class="day-title" id="day-${day}"><span class="day-dot day-${colour(day)}" aria-hidden="true"></span>Day ${day} · ${esc(dayDate(day))}</h2>
        <ol class="plain stops">
          ${stops.filter((e) => e.day === day).map((e) => {
            const reason = e.best_time && e.best_time.start === e.start ? e.best_time.reason : "You picked this time";
            return `
            <li class="card stop">
              <span class="pin day-${colour(e.day)}"><span class="visually-hidden">Stop </span>${e.stop}</span>
              <div class="stop-body">
                <p class="stop-time">${esc(e.start)} – ${esc(e.end)}</p>
                <h3>${esc(e.name)}</h3>
                <p class="stop-reason">${esc(reason)}</p>
                <p class="stop-price">${priceLine(e)}</p>
              </div>
              <a class="btn btn-primary" href="${esc(e.booking_url)}" target="_blank" rel="noopener noreferrer" aria-label="Book ${esc(e.name)} (opens a new tab)">Book</a>
            </li>`;
          }).join("")}
        </ol>
      </section>`).join("");

    // ---- map and legend ----
    const box = {
      minLat: Math.min(...stops.map((e) => e.location.lat)), maxLat: Math.max(...stops.map((e) => e.location.lat)),
      minLng: Math.min(...stops.map((e) => e.location.lng)), maxLng: Math.max(...stops.map((e) => e.location.lng))
    };
    const map = document.getElementById("map");
    map.setAttribute("aria-label", `Map placeholder with ${stops.length} numbered stops`);
    map.insertAdjacentHTML("beforeend", stops.map((e) => {
      const pos = pinPosition(e, box);
      return `<span class="pin day-${colour(e.day)}" style="left: ${pos.x}%; top: ${pos.y}%">${e.stop}</span>`;
    }).join(""));
    document.getElementById("legend").innerHTML = days.map((day) =>
      `<li><span class="day-dot day-${colour(day)}" aria-hidden="true"></span>Day ${day}</li>`
    ).join("");

    // ---- total (from backend/budget.py) ----
    const t = trip.totals;
    document.getElementById("total").textContent = money(t.used);
    document.getElementById("total-of").textContent =
      `of ${money(t.budget)} ${t.per === "total" ? `total for ${t.group_size}` : "per person"}`;
    if (t.over) {
      const over = document.getElementById("over-note");
      over.textContent = `Over budget by ${money(t.over_by)}`;
      over.hidden = false;
    }

    // Oldest price check among the stops that have a sourced price.
    const checked = stops.filter((e) => e.price.amount !== null && e.price.source).map((e) => e.price.source.retrieved_at)
      .sort((a, b) => new Date(a) - new Date(b));
    const notCounted = t.not_counted.length;
    const uncounted = notCounted ? ` ${notCounted} without a price ${notCounted === 1 ? "is" : "are"} not counted.` : "";
    document.getElementById("checked-note").textContent = checked.length
      ? `Prices checked on ${checkedOn(checked[0])}. They may change before you book.${uncounted}`
      : `No prices from a source yet: experiences without a price are not counted.`;
  }

  async function load() {
    if (!tripId) {
      showEmpty("No trip yet", 'Plan one first: <a href="plan.html">answer seven quick questions</a>.');
      return;
    }
    try {
      trip = await TP.api.get(TP.tripPath(tripId));
    } catch (error) {
      showEmpty("We couldn't load your trip", `${esc(error.message)} <a href="plan.html">Plan a new trip</a>.`);
      return;
    }
    render();
  }

  load();
})();
