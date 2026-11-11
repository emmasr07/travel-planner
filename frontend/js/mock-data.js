// Example trip used by every page until the backend exists; the same shape will later come from the API.
// MOCK DATA: these prices are fixed examples for the prototype only (by request). Real prices must come
// from a search API with their source and checked-at time; never add a price anywhere else in frontend/.

const MOCK_TRIP = {
  destination: "Lisbon",
  timeZone: "Europe/Lisbon",     // activity times below are local times in this zone
  startDate: "2026-05-14",       // calendar dates, local to the destination
  endDate: "2026-05-16",
  group: { type: "friends", size: 4 },
  ageRange: "18–24",
  interests: ["culture", "food", "adventure"],
  budget: { amount: 250, currency: "EUR", per: "person" },

  experiences: [
    {
      id: "alfama-food-walk",
      name: "Alfama food walk",
      description: "Taste pastries, cheese and ginjinha in the old town.",
      interest: "food",
      day: 1,
      timeOfDay: "Morning",
      start: "10:00",
      durationMin: 180,
      timeReason: "Markets are freshest in the morning",
      price: 35,
      currency: "EUR",
      source: "GetYourGuide",
      checkedAt: "2026-11-11T10:42:00+00:00",
      photo: null,
      map: { x: 68, y: 52 }
    },
    {
      id: "tram-28-viewpoints",
      name: "Tram 28 and viewpoints",
      description: "Ride the yellow tram up to Miradouro da Graça.",
      interest: "culture",
      day: 1,
      timeOfDay: "Sunset",
      start: "18:30",
      durationMin: 120,
      timeReason: "Best light over the river at sunset",
      price: 18,
      currency: "EUR",
      source: "Viator",
      checkedAt: "2026-11-11T10:42:00+00:00",
      photo: null,
      map: { x: 80, y: 37 }
    },
    {
      id: "sintra-palaces",
      name: "Sintra palaces day trip",
      description: "Pena Palace and Quinta da Regaleira with a guide.",
      interest: "culture",
      day: 2,
      timeOfDay: "Early",
      start: "09:00",
      durationMin: 360,
      timeReason: "Less crowded early morning",
      price: 62,
      currency: "EUR",
      source: "GetYourGuide",
      checkedAt: "2026-11-11T10:42:00+00:00",
      photo: null,
      map: { x: 17, y: 18 }
    },
    {
      id: "surf-caparica",
      name: "Surf lesson at Caparica",
      description: "Beginner group lesson, board and wetsuit included.",
      interest: "adventure",
      day: 3,
      timeOfDay: "Morning",
      start: "10:00",
      durationMin: 150,
      timeReason: "Calmer waves before the afternoon wind",
      price: 45,
      currency: "EUR",
      source: "Airbnb Experiences",
      checkedAt: "2026-11-11T10:42:00+00:00",
      photo: null,
      map: { x: 50, y: 86 }
    },
    {
      id: "fado-dinner",
      name: "Fado dinner in Bairro Alto",
      description: "Dinner with live fado in a small Bairro Alto tavern.",
      interest: "culture",
      day: 2,
      timeOfDay: "Evening",
      start: "20:00",
      durationMin: 150,
      timeReason: "Fado sets start after dinner",
      price: 40,
      currency: "EUR",
      source: "Viator",
      checkedAt: "2026-11-11T10:42:00+00:00",
      photo: null,
      map: { x: 58, y: 46 }
    }
  ]
};
