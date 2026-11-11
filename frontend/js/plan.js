// Questionnaire: shows one step at a time, keeps answers in sessionStorage, and only enables Next when the step is answered.

(function () {
  const STORAGE_KEY = "tp.answers";
  const GROUP_LABELS = { solo: "Solo", couple: "Couple", friends: "Friends", family: "Family" };
  const INTEREST_LABELS = {
    culture: "Culture", food: "Food", nature: "Nature", nightlife: "Nightlife",
    relax: "Relax", adventure: "Adventure", shopping: "Shopping"
  };
  const PACE_LABELS = { 1: "Very chill", 2: "Chill", 3: "Balanced", 4: "Busy", 5: "Packed" };
  const NUMBER_FIELDS = ["groupSize", "budgetAmount", "pace"];

  const DEFAULTS = {
    destination: "", startDate: "", endDate: "",
    groupType: "", groupSize: null, ageRange: "",
    interests: [], budgetAmount: null, budgetPer: "person",
    pace: 3, notes: ""
  };

  const form = document.getElementById("questionnaire");
  const steps = [...form.querySelectorAll(".step")];
  const backBtn = document.getElementById("back");
  const nextBtn = document.getElementById("next");
  const stepLabel = document.getElementById("step-label");
  const progressFill = document.getElementById("progress-fill");
  const summary = document.getElementById("summary");
  const summaryText = document.getElementById("summary-text");
  const dateError = document.getElementById("date-error");

  let answers = load();
  let current = 1;

  function load() {
    try {
      return { ...DEFAULTS, ...JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}") };
    } catch {
      return { ...DEFAULTS };
    }
  }

  function save() {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(answers)); } catch { /* storage blocked: answers live for this page only */ }
  }

  function datesInOrder() {
    return answers.startDate && answers.endDate && answers.endDate >= answers.startDate;
  }

  // Required checks per step (step 7 is optional).
  const VALID = {
    1: () => answers.destination.trim().length > 0,
    2: () => Boolean(datesInOrder()),
    3: () => Boolean(answers.groupType) && Number.isInteger(answers.groupSize) && answers.groupSize >= 1,
    4: () => Boolean(answers.ageRange),
    5: () => answers.interests.length > 0,
    6: () => Number(answers.budgetAmount) > 0 && Boolean(answers.budgetPer),
    7: () => true
  };

  function shortDateRange(start, end) {
    const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
    const a = parse(start), b = parse(end);
    const fmt = (d, opts) => new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" }).format(d);
    if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
      return `${fmt(a, { day: "numeric" })}–${fmt(b, { day: "numeric", month: "short" })}`;
    }
    return `${fmt(a, { day: "numeric", month: "short" })} – ${fmt(b, { day: "numeric", month: "short" })}`;
  }

  // "Your trip so far": answers from the steps before the current one.
  function summaryParts(beforeStep) {
    const parts = [];
    if (beforeStep > 1 && answers.destination.trim()) parts.push(answers.destination.trim());
    if (beforeStep > 2 && datesInOrder()) parts.push(shortDateRange(answers.startDate, answers.endDate));
    if (beforeStep > 3 && answers.groupType) {
      parts.push(answers.groupType === "solo" ? "Solo" : `${GROUP_LABELS[answers.groupType]} (${answers.groupSize})`);
    }
    if (beforeStep > 4 && answers.ageRange) parts.push(answers.ageRange);
    if (beforeStep > 5 && answers.interests.length) {
      parts.push(Object.keys(INTEREST_LABELS).filter((i) => answers.interests.includes(i)).map((i) => INTEREST_LABELS[i]).join(", "));
    }
    if (beforeStep > 6 && answers.budgetAmount) {
      parts.push(`€${answers.budgetAmount} ${answers.budgetPer === "total" ? "total" : "per person"}`);
    }
    return parts;
  }

  function stepName(n) {
    return steps[n - 1].dataset.name;
  }

  function refresh() {
    const valid = VALID[current]();
    nextBtn.disabled = !valid;
    dateError.hidden = !(current === 2 && answers.startDate && answers.endDate && !datesInOrder());

    const parts = summaryParts(current);
    summary.hidden = parts.length === 0;
    summaryText.textContent = parts.join(" · ");
  }

  function showStep(n, moveFocus) {
    current = n;
    steps.forEach((s) => { s.hidden = Number(s.dataset.step) !== n; });
    stepLabel.textContent = `Step ${n} of ${steps.length} · ${stepName(n)}`;
    progressFill.style.width = `${(n / steps.length) * 100}%`;
    nextBtn.textContent = n === steps.length ? "Find experiences" : `Next: ${stepName(n + 1).toLowerCase()}`;
    refresh();
    if (moveFocus) steps[n - 1].querySelector("h1").focus();
  }

  // Put stored answers back into the inputs and chips.
  function fillInputs() {
    form.querySelectorAll("[data-field]").forEach((el) => {
      const field = el.dataset.field;
      const value = answers[field];
      if (el.classList.contains("chips")) {
        el.querySelectorAll(".chip").forEach((chip) => {
          const on = Array.isArray(value) ? value.includes(chip.dataset.value) : value === chip.dataset.value;
          chip.classList.toggle("is-on", on);
          chip.setAttribute("aria-pressed", String(on));
        });
      } else if (value !== null && value !== undefined) {
        el.value = value;
      }
    });
    syncPaceLabel();
    syncDateMin();
  }

  function syncPaceLabel() {
    const pace = form.querySelector('[data-field="pace"]');
    pace.setAttribute("aria-valuetext", PACE_LABELS[pace.value] || "");
  }

  function syncDateMin() {
    form.querySelector('[data-field="endDate"]').min = answers.startDate || "";
  }

  // Chips: "single" groups hold one value, "multi" groups toggle each chip on and off.
  form.querySelectorAll(".chips").forEach((group) => {
    group.addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      const field = group.dataset.field;
      const value = chip.dataset.value;

      if (group.dataset.mode === "multi") {
        const set = new Set(answers[field]);
        set.has(value) ? set.delete(value) : set.add(value);
        answers[field] = [...set];
      } else {
        answers[field] = value;
        if (field === "groupType" && (value === "solo" || value === "couple")) {
          answers.groupSize = value === "solo" ? 1 : 2;
        }
      }
      save();
      fillInputs();
      refresh();
    });
  });

  // Text, date, number, range and textarea inputs.
  form.addEventListener("input", (event) => {
    const el = event.target;
    const field = el.dataset && el.dataset.field;
    if (!field || el.classList.contains("chips")) return;
    if (NUMBER_FIELDS.includes(field)) {
      answers[field] = el.value === "" ? null : Number(el.value);
    } else {
      answers[field] = el.value;
    }
    if (field === "pace") syncPaceLabel();
    if (field === "startDate") syncDateMin();
    save();
    refresh();
  });

  // Next (button or Enter key).
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!VALID[current]()) return;
    if (current === steps.length) {
      save();
      window.location.href = "experiences.html";
    } else {
      showStep(current + 1, true);
    }
  });

  backBtn.addEventListener("click", () => {
    if (current === 1) {
      window.location.href = "index.html";
    } else {
      showStep(current - 1, true);
    }
  });

  fillInputs();
  showStep(1, false);
})();
