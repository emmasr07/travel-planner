// The page logic: sends the profile, polls the trip JSON while the agents work, draws the list, sends the five picks.
// It only draws what the server returns; the sum in the bottom bar is for display, the server checks the picks again.

const INTERESTS = ["nature", "sea", "culture", "food", "adventure", "relax", "sport", "event"];
const STATES = { verified: "Verified", to_check: "To check", rejected: "Rejected" };
const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
const PICKS = 5;
const $ = (id) => document.getElementById(id);
let trip = null;
let chosen = new Set();

// el("p", {class: "x"}, "text", child) — text goes in as text, never as HTML: the data comes from the web.
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) n.append(k);
  return n;
}

function person(name = "", age = "") {
  const row = el("div", { class: "person" },
    el("input", { placeholder: "Name or role", value: name, required: true }),
    el("input", { type: "number", min: 0, max: 110, placeholder: "Age", value: age, required: true }),
    el("button", { type: "button", "aria-label": "Remove", onclick: () => row.remove() }, "×"));
  $("people").append(row);
}

function setup() {
  [["Parent 1", 50], ["Parent 2", 48], ["Teen", 15]].forEach(([n, a]) => person(n, a));
  $("add").onclick = () => person();
  for (const i of INTERESTS) {
    const on = ["nature", "sea", "food"].includes(i);
    $("interests").append(el("button", { type: "button", class: "chip", "aria-pressed": String(on),
      onclick: (e) => e.target.setAttribute("aria-pressed", String(e.target.getAttribute("aria-pressed") !== "true")) }, i));
  }
  $("profile").onsubmit = start;
  $("make").onclick = makePdf;
  fetch("/api/config").then((r) => r.json()).then((h) => {
    if (h.mode === "demo") { $("mode").hidden = false; $("mode").textContent = "Demo mode · invented data"; }
  });
  const id = new URLSearchParams(location.hash.slice(1)).get("trip");
  if (id) poll(id);
}

async function start(ev) {
  ev.preventDefault();
  const f = new FormData($("profile"));
  const profile = {
    destination: f.get("destination").trim(), start: f.get("start"), end: f.get("end"),
    budget: Number(f.get("budget")), currency: f.get("currency"), notes: f.get("notes").trim(),
    travellers: [...$("people").children].map((r) => ({ name: r.children[0].value.trim(), age: Number(r.children[1].value) })),
    interests: [...$("interests").children].filter((c) => c.getAttribute("aria-pressed") === "true").map((c) => c.textContent),
  };
  $("search").disabled = true;
  const r = await fetch("/api/trips", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
  const body = await r.json();
  $("search").disabled = false;
  if (!r.ok) return alert(typeof body.detail === "string" ? body.detail : "Check the form: " + JSON.stringify(body.detail));
  chosen = new Set();
  location.hash = "trip=" + body.id;
  poll(body.id);
}

async function poll(id) {
  const r = await fetch("/api/trips/" + id);
  if (!r.ok) return;
  trip = await r.json();
  draw();
  if (["researching", "checking", "verifying"].includes(trip.status)) setTimeout(() => poll(id), 1200);
}

function draw() {
  $("loop").hidden = false;
  const order = ["researching", "checking", "verifying"];
  const at = order.indexOf(trip.status);
  for (const li of $("phases").children) {
    const i = order.indexOf(li.dataset.phase);
    li.className = i === at ? "now" : (at === -1 || i < at ? "done" : "");
  }
  $("steps").replaceChildren(...trip.steps.map((s) => el("div", { class: "step" }, el("time", {}, s.at), el("b", {}, s.who), el("span", {}, s.text))),
    ...(trip.error ? [el("div", { class: "error" }, trip.error)] : []));
  $("steps").scrollTop = $("steps").scrollHeight;

  const ready = ["ready", "done"].includes(trip.status);
  $("list").hidden = !ready;
  $("bar").hidden = !ready || trip.status === "done";
  if (!ready) return;
  if (trip.picks) chosen = new Set(trip.picks);
  const p = trip.profile;
  $("summary").textContent = `${trip.experiences.length} experiences for ${p.travellers.length} people in ${p.destination}, ` +
    `${p.start} to ${p.end}. Verified ones passed the code checks and the verifier; the others say why.`;
  $("groups").replaceChildren(...Object.keys(STATES).map((s) => {
    const items = trip.experiences.filter((e) => e.status === s);
    return items.length ? el("div", { class: "group" }, el("h3", {}, `${STATES[s]} · ${items.length}`),
      el("div", { class: "block" }, items.map(row))) : null;
  }).filter(Boolean));
  bar();
  drawPlan();
}

function money(v, cur) { return v == null ? "price not counted" : v === 0 ? "free" : `${Math.round(v).toLocaleString("en")} ${cur}`; }

function row(e) {
  const cur = trip.profile.currency;
  const months = e.months.length ? e.months.map((m) => MONTHS[m - 1]).join(" ") : "all year";
  const box = el("input", { type: "checkbox", checked: chosen.has(e.id), disabled: e.status === "rejected" || trip.status === "done",
    "aria-label": "Pick " + e.name, onclick: (ev) => ev.stopPropagation(),
    onchange: (ev) => { ev.target.checked ? chosen.add(e.id) : chosen.delete(e.id); bar(); } });
  const v = e.verdict || {};
  const item = el("div", { class: "exp " + e.status },
    el("div", { class: "exp-head", onclick: () => item.classList.toggle("open") },
      box,
      el("div", {},
        el("div", { class: "exp-name" }, e.name),
        el("div", { class: "exp-meta" }, el("span", { class: "place" }, e.place), ` · ${e.category} · ${months}`),
        el("div", { class: "exp-why" }, e.why_you)),
      el("div", { class: "exp-cost" }, money(e.group_cost, cur), el("br"), el("span", { class: "state " + e.status }, STATES[e.status]))),
    el("div", { class: "exp-body" },
      el("p", {}, e.description),
      el("ul", { class: "checks" }, e.checks.map((c) => el("li", { class: c.result }, `${c.name}: ${c.detail}`)),
        el("li", { class: v.verdict === "confirmed" ? "ok" : v.verdict === "contradicted" ? "fail" : "warn" },
          `verifier: ${(v.verdict || "no verdict").replace("_", " ")}${v.note ? ". " + v.note : ""}`)),
      e.sources.map((s) => el("div", { class: "source" },
        el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title), el("p", { class: "quote" }, `“${s.quote}”`))),
      e.doubts ? el("p", {}, "Not sure: " + e.doubts) : null));
  return item;
}

function bar() {
  const picked = trip.experiences.filter((e) => chosen.has(e.id));
  const sum = picked.reduce((t, e) => t + (e.group_cost || 0), 0);
  const p = trip.profile;
  $("picked").textContent = `${picked.length} of ${PICKS}`;
  $("cost").textContent = `${Math.round(sum).toLocaleString("en")} of ${money(p.budget, p.currency)}`;
  $("cost").className = sum > p.budget ? "over" : "";
  $("make").disabled = picked.length !== PICKS || sum > p.budget;
}

async function makePdf() {
  $("make").disabled = true;
  const r = await fetch(`/api/trips/${trip.id}/picks`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: [...chosen] }) });
  const body = await r.json();
  if (!r.ok) { alert(body.detail); return bar(); }
  trip = body;
  draw();
  $("plan").scrollIntoView({ behavior: "smooth" });
}

function drawPlan() {
  $("plan").hidden = trip.status !== "done";
  if (trip.status !== "done") return;
  const t = trip.totals;
  $("delivery").replaceChildren(...[
    el("div", { class: "row" }, `Five experiences, ${money(t.picked_cost, t.currency)} of ${money(t.budget, t.currency)}: ${money(t.left, t.currency)} left.`),
    t.not_counted.length ? el("div", { class: "row" }, "Not counted: " + t.not_counted.join(", ")) : null,
    el("div", { class: "row" }, el("a", { href: `/api/trips/${trip.id}/pdf` }, "Download the PDF")),
    el("div", { class: "row" }, el("a", { href: `/api/trips/${trip.id}/json` }, `Download ${trip.id}.json`))].filter(Boolean));
}

setup();
