// Brochure: shows the sublist the backend built and saved (POST /api/trips/{id}/brochure, backend/brochure.py):
// the stops by day and time with their price, source, checked-at time, status and Book link; the total, the items
// not counted and the "Prices checked on" note, all as the backend wrote them. The map is the Geoapify image saved
// at build time, or the pin plot (pins placed by their coordinates) when there is none. Download PDF gets the PDF
// drawn from the same sublist. Nothing is added up here.

(function () {
  const GROUP_LABELS = { solo: "Solo", couple: "Couple", friends: "Friends", family: "Family", business: "Business" };
  const PROVIDERS = { viator: "Viator", geoapify: "Geoapify (OpenStreetMap)", web: "Web page", frankfurter: "Frankfurter" };
  const DAY_COLOURS = 3;    // styles.css has --day-1 to --day-3; later days reuse them

  const tripId = TP.tripId();
  const pdfLink = document.getElementById("download-pdf");
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

  // "17 Nov, 13:42" in the destination's time, as the PDF writes it.
  function checkedOn(iso) {
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: trip.profile.timezone || undefined
    }).format(new Date(iso));
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

  // "Fri 4 Dec" for a stop's date.
  function dayDate(iso) {
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })
      .format(parseDate(iso));
  }

  function colour(day) {
    return ((day - 1) % DAY_COLOURS) + 1;
  }

  function groupLabel(p) {
    return p.group_type === "solo" ? "Solo" : `${GROUP_LABELS[p.group_type]} (${p.group_size})`;
  }

  // The price as the source states it, with its label, source and checked-at time; never a price without them.
  function priceLine(s) {
    const p = s.price;
    const source = p.source
      ? `${esc(PROVIDERS[p.source.provider] || p.source.provider)} · checked ${esc(checkedOn(p.source.retrieved_at))}`
      : "no source";
    if (p.per === "free") return `<strong>Free</strong> <span class="caption">· ${source}</span>`;
    if (p.amount === null || p.amount === undefined || !p.source) {
      return '<strong>No price yet</strong> <span class="caption">· no source states a price · not counted</span>';
    }
    const label = p.label ? ` · ${esc(p.label)}` : "";
    const per = p.per === "group" ? "per group" : "per person";
    const inEuro = p.currency !== "EUR" && p.amount_eur !== null && p.fx
      ? ` · ${esc(money(p.amount_eur))} at the ${esc(p.fx.date)} rate (Frankfurter)` : "";
    const notConverted = p.currency !== "EUR" && p.amount_eur === null ? " · not converted, not counted" : "";
    return `<strong>${esc(money(p.amount, p.currency))}</strong>${label}
      <span class="caption">· ${per} · ${source}${inEuro}${notConverted}</span>`;
  }

  function statusLine(s) {
    if (s.status === "verified") return '<span class="badge">Verified</span>';
    return `<span class="caption">To check${s.note ? `: ${esc(s.note)}` : ""}</span>`;
  }

  function showEmpty(title, html) {
    document.getElementById("plan").hidden = true;
    document.getElementById("empty-title").textContent = title;
    document.getElementById("empty-text").innerHTML = html;
    document.getElementById("empty").hidden = false;
  }

  function pdfReady(ready) {
    if (ready) {
      pdfLink.href = TP.tripPath(tripId, "/brochure.pdf");
      pdfLink.removeAttribute("aria-disabled");
      pdfLink.removeAttribute("title");
    } else {
      pdfLink.removeAttribute("href");
      pdfLink.setAttribute("aria-disabled", "true");
      pdfLink.title = "Build your trip first";
    }
  }

  // ---- the map: the saved Geoapify image, or pins placed inside the stops' bounding box ----
  function pinPosition(s, box) {
    const spanLng = box.maxLng - box.minLng, spanLat = box.maxLat - box.minLat;
    const x = spanLng ? 10 + 80 * (s.location.lng - box.minLng) / spanLng : 50;
    const y = spanLat ? 10 + 80 * (box.maxLat - s.location.lat) / spanLat : 50;
    return { x: x.toFixed(1), y: y.toFixed(1) };
  }

  function drawPlot(stops, reason) {
    const lats = stops.map((s) => s.location.lat), lngs = stops.map((s) => s.location.lng);
    const box = { minLat: Math.min(...lats), maxLat: Math.max(...lats), minLng: Math.min(...lngs), maxLng: Math.max(...lngs) };
    const map = document.getElementById("map");
    map.classList.remove("has-image");
    map.setAttribute("aria-label", `Pins of the ${stops.length} stops placed by their coordinates, numbered in visiting order`);
    map.innerHTML = stops.map((s) => {
      const pos = pinPosition(s, box);
      return `<span class="pin day-${colour(s.day)}" style="left: ${pos.x}%; top: ${pos.y}%">${s.stop}</span>`;
    }).join("");
    document.getElementById("map-note").textContent = `Pins placed by their coordinates (no map image: ${reason}).`;
  }

  function drawMap(stops, m) {
    if (!m || m.kind !== "static") {
      drawPlot(stops, (m && m.reason) || "none was made");
      return;
    }
    const map = document.getElementById("map");
    map.classList.add("has-image");
    map.removeAttribute("role");
    map.removeAttribute("aria-label");
    map.innerHTML = `<img class="map-image" src="${esc(TP.tripPath(tripId, "/brochure/map.png"))}"
      alt="Map of the ${stops.length} stops, numbered in visiting order, one colour per day">`;
    map.querySelector("img").addEventListener("error", () => {
      map.setAttribute("role", "img");
      drawPlot(stops, "the map image did not load");
    });
    document.getElementById("map-note").innerHTML =
      'Powered by <a href="https://www.geoapify.com/" target="_blank" rel="noopener noreferrer">Geoapify</a> · ' +
      '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
  }

  // ---- page ----
  function render() {
    const p = trip.profile;
    const listLink = `experiences.html?trip=${encodeURIComponent(tripId)}`;
    document.getElementById("edit-trip").href = listLink;
    document.getElementById("title").textContent = p.destination;

    if (trip.status !== "done" || !trip.brochure) {
      document.getElementById("subtitle").textContent = shortDateRange(p.start_date, p.end_date);
      pdfReady(false);
      showEmpty("Your brochure isn't built yet",
        `Keep the experiences you want, then use "Build my trip". <a href="${esc(listLink)}">Go back to your experiences</a>.`);
      return;
    }
    if (trip.brochure.prices_note === undefined) {
      pdfReady(false);
      showEmpty("This brochure was built by an older version",
        `Change something in your list (keep or remove an experience), then use "Build my trip" again. ` +
        `<a href="${esc(listLink)}">Go back to your experiences</a>.`);
      return;
    }

    const b = trip.brochure;
    const stops = trip.brochure.stops;
    const days = [...new Set(stops.map((s) => s.day))];
    pdfReady(true);

    document.getElementById("subtitle").textContent =
      `${shortDateRange(p.start_date, p.end_date)} · ${groupLabel(p)} · ` +
      `${stops.length} ${stops.length === 1 ? "experience" : "experiences"}` +
      (trip.mode === "demo" ? " · Demo data, not verified" : "");

    // ---- day by day ----
    document.getElementById("days").innerHTML = days.map((day) => {
      const mine = stops.filter((s) => s.day === day);
      return `
      <section class="day" aria-labelledby="day-${day}">
        <h2 class="day-title" id="day-${day}"><span class="day-dot day-${colour(day)}" aria-hidden="true"></span>Day ${day} · ${esc(dayDate(mine[0].date))}</h2>
        <ol class="plain stops">
          ${mine.map((s) => `
            <li class="card stop">
              <span class="pin day-${colour(s.day)}"><span class="visually-hidden">Stop </span>${s.stop}</span>
              <div class="stop-body">
                <p class="stop-time">${esc(s.start)} – ${esc(s.end)}</p>
                <h3>${esc(s.name)}</h3>
                <p class="stop-reason">${esc(s.time_why.text)}</p>
                <p class="stop-price">${priceLine(s)}</p>
                <p class="stop-status">${statusLine(s)}</p>
              </div>
              <a class="btn btn-primary" href="${esc(s.booking_url)}" target="_blank" rel="noopener noreferrer" aria-label="Book ${esc(s.name)} (opens a new tab)">Book</a>
            </li>`).join("")}
        </ol>
      </section>`;
    }).join("");

    // ---- map and legend ----
    drawMap(stops, b.map);
    document.getElementById("legend").innerHTML = days.map((day) =>
      `<li><span class="day-dot day-${colour(day)}" aria-hidden="true"></span>Day ${day}</li>`
    ).join("");

    // ---- total, not counted and the price-check note (all from backend/brochure.py and budget.py) ----
    const t = b.totals;
    document.getElementById("total").textContent = money(t.used);
    document.getElementById("total-of").textContent =
      `of ${money(t.budget)} ${t.per === "total" ? `total for ${t.group_size}` : "per person"}`;
    const notCounted = document.getElementById("not-counted");
    notCounted.textContent = b.not_counted.length
      ? `Not counted: ${b.not_counted.map((n) => n.name).join(", ")} (no price from a source).` : "";
    notCounted.hidden = b.not_counted.length === 0;
    document.getElementById("checked-note").textContent = b.prices_note;
  }

  async function load() {
    if (!tripId) {
      pdfReady(false);
      showEmpty("No trip yet", 'Plan one first: <a href="plan.html">answer seven quick questions</a>.');
      return;
    }
    try {
      trip = await TP.api.get(TP.tripPath(tripId));
    } catch (error) {
      pdfReady(false);
      showEmpty("We couldn't load your trip", `${esc(error.message)} <a href="plan.html">Plan a new trip</a>.`);
      return;
    }
    render();
  }

  load();
})();
