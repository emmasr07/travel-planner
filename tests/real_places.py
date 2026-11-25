# Real places where the same place turned up twice, copied as their sources gave them: name, category, coordinates,
# description, tags and price label. Rome: trip rome-20261122-231553-9b61, in the researcher's order, with the day,
# time and duration it proposed. Matera and Lisbon: data/samples/. Prices stay the factories' fixed test examples.
from tests.factories import checked

ROME = [
    {"id": "colosseum-forum-palatine-guided-tour", "name": "Colosseum Roman Forum and Palatine Hill Guided Tour",
     "category": "culture", "lat": 41.8902572, "lng": 12.4923841, "label": "Adult (13–99)", "duration_min": 150,
     "description": "Explore the Colosseum, Roman Forum, and Palatine Hill with an expert guide on a skip-the-line "
                    "semi-private tour. Discover gladiator history, ancient ruins, and panoramic views while enjoying "
                    "a more personal and immersive Ancient Rome experience beyond standard entry tickets.",
     "tags": ["Attractions & Museums", "Historical Tours", "Monuments and Memorials", "Skip the line Tickets"],
     "schedule": {"day": 1, "start": "10:15", "end": "12:45"}},
    {"id": "pasta-ravioli-tiramisu-class-piazza-mattei",
     "name": "Rome Pasta, Ravioli & Tiramisu Cooking Class with Premium Wine", "category": "food",
     "lat": 41.8937779, "lng": 12.4774741, "label": "Adult (18–99)", "duration_min": 180,
     "description": "Enjoy a private, memorable culinary experience near the charming Piazza Mattei. Soak in the rich "
                    "history and vibrant culture of this iconic square, home to the enchanting Turtle Fountain "
                    "(Fontana delle Tartarughe), just steps from our workshop.",
     "tags": ["Cooking Classes", "Pasta Making Classes", "Wine Tastings", "Small Group", "Food & Drink"],
     "schedule": {"day": 1, "start": "18:30", "end": "21:30"}},
    {"id": "testaccio-market", "name": "Testaccio Market (Nuovo Mercato di Testaccio)", "category": "food",
     "lat": 41.8776017, "lng": 12.4735798, "label": None, "duration_min": 120,
     "description": "Covered local market with 100-plus stalls where many food stands serve Roman street food, from "
                    "pasta frittata to meatball sandwiches. Wander the stalls and eat lunch among the locals.",
     "tags": ["Market", "Street food", "Local", "Free to enter"],
     "schedule": {"day": 1, "start": "13:15", "end": "15:15"}},
    {"id": "capitoline-museums", "name": "Capitoline Museums (Musei Capitolini)", "category": "culture",
     "lat": 41.8926663, "lng": 12.482201, "label": "Full price for non-residents", "duration_min": 120,
     "description": "Rome's civic museums on Piazza del Campidoglio, with ancient sculpture and paintings, including "
                    "the Capitoline She-wolf and the Marcus Aurelius statue.",
     "tags": ["Museum", "Ancient Rome", "Sculpture", "Art"],
     "schedule": {"day": 2, "start": "10:00", "end": "12:00"}},
    {"id": "trevi-fountain", "name": "Trevi Fountain", "category": "culture",
     "lat": 41.9009778, "lng": 12.4832848, "label": None, "duration_min": 30,
     "description": "The most famous of Rome's fountains, a Baroque monument by Nicola Salvi. Since February 2026 "
                    "visitors who are not residents pay a ticket to enter the basin area closest to the monument.",
     "tags": ["Fountain", "Landmark", "Baroque", "Photo spot"],
     "schedule": {"day": 2, "start": "18:00", "end": "18:30"}},
    {"id": "piazza-navona", "name": "Piazza Navona", "category": "culture",
     "lat": 41.8989282, "lng": 12.4731178, "label": None, "duration_min": 60,
     "description": "Elongated Baroque square built over the ancient Stadium of Domitian, with Bernini's Fountain of "
                    "the Four Rivers, Borromini's Sant'Agnese in Agone, cafes and street artists. In December it "
                    "hosts a Christmas market.",
     "tags": ["Square", "Baroque", "Fountains", "Free", "Christmas market"],
     "schedule": {"day": 2, "start": "13:00", "end": "14:00"}},
    {"id": "pizza-gelato-suppli-class-colosseum", "name": "Pizza, Gelato & Suppli Cooking Class by Colosseum",
     "category": "food", "lat": 41.8902572, "lng": 12.4923841, "label": "Adult (18–100)", "duration_min": 180,
     "description": "Indulge in an unforgettable adventure with our Pizza & Gelato Masterclass, where you'll immerse "
                    "yourself in the art of Italian cuisine.",
     "tags": ["Cooking Classes", "Pizza Making Classes", "Small Group", "Food & Drink"],
     "schedule": {"day": 3, "start": "14:00", "end": "17:00"}},
    {"id": "colosseum-roman-forum-palatine-self-guided",
     "name": "Colosseum, Roman Forum and Palatine (official ticket)", "category": "culture",
     "lat": 41.8916414, "lng": 12.4867296, "label": "Full entry", "duration_min": 180,
     "description": "Self-guided visit with the park's own ticket: the Colosseum with its second level and museum, the "
                    "Roman Forum, the Palatine Hill and ongoing exhibitions, with entry slots you book for the "
                    "Colosseum.",
     "tags": ["Archaeology", "Ancient Rome", "Self-guided", "Landmark"],
     "schedule": {"day": 3, "start": "09:30", "end": "12:30"}},
    {"id": "private-colosseum-photoshoot-eidos", "name": "Rome: Private Colosseum Photoshoot with Local Photographer",
     "category": "culture", "lat": 41.8902572, "lng": 12.4923841, "label": "Adult (13–99), when 2 book together",
     "duration_min": 90,
     "description": "Enjoy a private photoshoot with Eidos Photography at the Colosseum and its most photogenic "
                    "viewpoints, led by a local photographer focused on natural posing and a smooth, relaxed flow.",
     "tags": ["Photo Shoots", "Photography Tours", "Excellent Quality", "Weather Dependent - Weather-Proof"],
     "schedule": {"day": 3, "start": "07:30", "end": "09:00"}},
    {"id": "colosseum-hidden-gems-photoshoot", "name": "Rome: Colosseum Photoshoot, Private & Custom Experience",
     "category": "culture", "lat": 41.8902572, "lng": 12.4923841, "label": "Adult (16–64), when 2 book together",
     "duration_min": 40,
     "description": "Experience the charm of Rome with a photo shoot at the Colosseum and Hidden Gems. Your local "
                    "photographer will lead you to the best spots and guide your poses for stunning photos.",
     "tags": ["Photo Shoots", "Photography Tours", "Excellent Quality", "Weather Dependent - Moderate"],
     "schedule": {"day": 3, "start": "17:00", "end": "17:40"}},
]
TOUR, PASTA, TESTACCIO, CAPITOLINE, TREVI, NAVONA, PIZZA, TICKET, PHOTO, PHOTO_2 = ROME

MATERA = {
    "underground-mattress": {"id": "viator-170751p1", "name": "Underground mattress", "category": "culture",
                             "lat": 40.667736, "lng": 16.606938,
                             "description": "1200 m2 underground, to discover the history of the city of the Sassi "
                                            "and beyond, up to a depth of 12 meters."},
    "ipogeo-materasum": {"id": "osm-n6602521780", "name": "Ipogeo MateraSum", "category": "culture",
                         "lat": 40.6677505, "lng": 16.6068417, "description": ""},
    "casa-noha": {"id": "osm-n3103273454", "name": "Casa Noha", "category": "culture",
                  "lat": 40.6663417, "lng": 16.6121361, "description": ""},
    "musma": {"id": "osm-n2229592221", "name": "Musma", "category": "culture",
              "lat": 40.6661178, "lng": 16.6122514, "description": ""},
}

LISBON = {
    "ministerium-cantina": {"id": "osm-n2003731541", "name": "Ministerium Cantina", "category": "food",
                            "lat": 38.7081204, "lng": -9.1354935, "description": ""},
    "nosolo-italia": {"id": "osm-n2003731545", "name": "Nosolo Italia", "category": "food",
                      "lat": 38.7079633, "lng": -9.1354229, "description": ""},
    "jeronimos-entry-tickets": {"id": "viator-461245p242", "name": "Jeronimos Monastery Entry Tickets",
                                "category": "culture", "lat": 38.6977531, "lng": -9.2055912, "description": ""},
}


def fields(rec):
    """The record's facts (and the Rome schedule) as factory overrides."""
    out = {"name": rec["name"], "category": rec["category"], "location": {"lat": rec["lat"], "lng": rec["lng"]},
           "description": rec.get("description", ""), "tags": rec.get("tags", []),
           "price": {"label": rec.get("label")}}
    for key in ("duration_min", "schedule"):
        if key in rec:
            out[key] = rec[key]
    return out


def place(rec, kept=True, id=None, **over):
    """The record as the code sees it after the conversion step (tests.factories.checked); `id` for a copy."""
    return checked(id or rec["id"], kept=kept, **{**fields(rec), **over})

# Rome trip rome-20261122-231553-9b61: the questionnaire (Sat 5 - Mon 7 Dec 2026) and the facts the hours check reads.
ROME_PROFILE = {"destination": "rome", "start_date": "2026-12-05", "end_date": "2026-12-07", "timezone": "Europe/Rome",
                "group_type": "couple", "group_size": 2, "budget": {"amount": "300", "currency": "EUR", "per": "person"}}
TREVI_PAGE = {"provider": "web", "url": "https://www.turismoroma.it/en/places/trevi-fountain",
              "retrieved_at": "2026-11-22T23:17:54+01:00",
              "quote": "From February the 2nd 2026, to enter the basin of the Trevi Fountain (the part closest to the "
                       "monument), tourists and non-residents must pay a ticket costing two euros, valid every day "
                       "from 9 a.m. to 10 p.m. (including the first Sunday of the month)."}
TREVI_HOURS = {"text": "Ticket valid every day from 9 a.m. to 10 p.m.", "slots": [], "source": TREVI_PAGE}
# Piazza Navona has no opening hours anywhere. Geoapify's place details (asked again on 25 Nov 2026) give the OSM tags
# place=square, tourism=attraction, wheelchair=yes; the geocode search the trip stored, and the details it returned:
NAVONA_GEOCODE = ("https://api.geoapify.com/v1/geocode/search?text=Piazza+Navona%2C+Rome&format=json&limit=1"
                  "&filter=circle%3A12.4829321%2C41.8933203%2C30000&bias=proximity%3A12.4829321%2C41.8933203")
NAVONA_PLACE_ID = "519a4f0c7f3cf2284059e0394a1410f34440f00102f90162ce400000000000c0020192030d5069617a7a61204e61766f6e61"
NAVONA_RAW = {"lit": "yes", "name": "Piazza Navona", "place": "square", "osm_id": 4247138, "osm_type": "w",
              "tourism": "attraction", "heritage": 1, "old_name": "Stadio di Domiziano", "wheelchair": "yes"}
NAVONA_CATEGORIES = ["heritage", "heritage.unesco", "tourism", "tourism.attraction", "tourism.sights",
                     "tourism.sights.square", "wheelchair", "wheelchair.yes"]
NAVONA_PUBLIC_SPACE = {"osm_tag": "place=square", "name": "Piazza Navona",
                       "source": {"provider": "geoapify", "quote": None, "retrieved_at": "2026-11-25T09:12:50+01:00",
                                  "url": f"https://api.geoapify.com/v2/place-details?id={NAVONA_PLACE_ID}"}}
