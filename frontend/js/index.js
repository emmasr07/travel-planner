// Home page: fills the example-trip preview card (map pins and the Day 1 list) with a static illustration.
// It shows names, days and times only: costs, sources and check times appear only for real trips, from the API.

(function () {
  const EXAMPLE = {
    destination: "Lisbon",
    days: 3,
    group: "4 friends",
    stops: [
      { name: "Alfama food walk", interest: "Food", day: 1, when: "Morning 10:00", map: { x: 68, y: 52 } },
      { name: "Tram 28 and viewpoints", interest: "Culture", day: 1, when: "Sunset 18:30", map: { x: 80, y: 37 } },
      { name: "Sintra palaces day trip", interest: "Culture", day: 2, when: "Early 09:00", map: { x: 17, y: 18 } },
      { name: "Fado dinner in Bairro Alto", interest: "Culture", day: 2, when: "Evening 20:00", map: { x: 58, y: 46 } },
      { name: "Surf lesson at Caparica", interest: "Adventure", day: 3, when: "Morning 10:00", map: { x: 50, y: 86 } }
    ]
  };

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  document.getElementById("preview-city").textContent = EXAMPLE.destination;
  document.getElementById("preview-meta").textContent = `${EXAMPLE.days} days · ${EXAMPLE.group} · example`;

  document.getElementById("preview-map").innerHTML = EXAMPLE.stops.map((e, i) =>
    `<span class="pin day-${e.day}" style="left: ${e.map.x}%; top: ${e.map.y}%">${i + 1}</span>`
  ).join("");

  document.getElementById("preview-list").innerHTML = EXAMPLE.stops.filter((e) => e.day === 1).map((e) => `
    <li>
      <div>
        <p class="name">${esc(e.name)}</p>
        <p class="caption">${esc(e.interest)} · Day ${e.day}</p>
      </div>
      <span class="badge">${esc(e.when)}</span>
    </li>`).join("");
})();
