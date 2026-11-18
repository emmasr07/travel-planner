# Small builders for test data: a questionnaire profile and one experience in the shape the researcher delivers
# (valid against schemas/experiences.schema.json). Prices are fixed test examples, never real quotes.
import copy

VIATOR = {"provider": "viator", "url": "https://www.viator.com/tours/Lisbon/x", "retrieved_at": "2026-11-17T14:42:00+01:00",
          "quote": None}
GEO = {"provider": "geoapify", "url": "https://api.geoapify.com/v2/places?x", "retrieved_at": "2026-11-17T14:42:05+01:00",
       "quote": None}

PROFILE = {
    "destination": "Lisbon", "start_date": "2026-12-04", "end_date": "2026-12-06", "timezone": "Europe/Lisbon",
    "group_type": "friends", "group_size": 4, "age_range": "25-34", "youngest_age": None,
    "interests": ["food", "culture"], "budget": {"amount": "250", "currency": "EUR", "per": "person"},
    "pace": "balanced", "notes": "",
}

EXPERIENCE = {
    "id": "alfama-food-walk", "name": "Alfama food walk", "description": "Taste pastries in the old town.",
    "category": "food", "tags": ["food tour"],
    "location": {"city": "Lisbon", "address": "Largo do Chafariz de Dentro, Lisbon", "lat": 38.7115, "lng": -9.1295,
                 "timezone": "Europe/Lisbon", "source": GEO},
    "duration_min": 120,
    "price": {"amount": 35.0, "currency": "EUR", "per": "person", "amount_eur": None, "fx": None, "source": VIATOR},
    "opening_hours": {"text": "Mo-Su 09:00-18:00", "slots": [], "source": GEO},
    "months": [], "min_age": None, "rating": None, "indoor_outdoor": "outdoor",
    "accessibility": {"wheelchair": "unknown", "notes": None, "source": None},
    "suitable_for": {"values": [], "kind": "fact"},
    "booking_url": "https://www.viator.com/tours/Lisbon/x", "photo_url": None,
    "certainty": "high", "doubts": None,
    "best_time": {"slot": "morning", "start": "10:00", "reason": "A test suggestion", "kind": "suggestion"},
    "why_fits": {"text": "You picked food", "kind": "suggestion"},
    "schedule": {"day": 1, "start": "10:00", "end": "12:00"},
}


def _merge(base, over):
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict) and key not in ("opening_hours",):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def profile(**over):
    return _merge(copy.deepcopy(PROFILE), over)


def experience(id="alfama-food-walk", **over):
    """As delivered by the researcher: amount_eur and fx are null."""
    return _merge(copy.deepcopy(EXPERIENCE), {"id": id, **over})


def checked(id="alfama-food-walk", kept=True, **over):
    """After the code's conversion step: amount_eur filled (EUR), a user block, no checks yet."""
    e = experience(id, **over)
    e["price"]["amount_eur"] = e["price"]["amount"] if e["price"]["currency"] == "EUR" else e["price"]["amount_eur"]
    e["user"] = {"status": "kept" if kept else "removed", "position": None}
    e["checks"] = []
    e["verdict"] = None
    return e
