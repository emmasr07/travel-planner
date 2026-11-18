"""The researcher agent: searches the web and delivers 10-15 experiences, each with a source URL and a copied quote.

create_agents.py sends this definition to Claude Managed Agents; backend/llm.py runs one session per trip.
backend/checks.py validates the delivery against DELIVER_EXPERIENCES, the same schema the agent is given.
"""
from agents.shared import MODEL, toolset

CATEGORIES = ["nature", "sea", "culture", "food", "adventure", "event", "relax", "sport", "other"]

EXPERIENCE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "name", "place", "category", "description", "why_you", "months", "duration_hours",
                 "price", "min_age", "sources", "certainty", "doubts"],
    "properties": {
        "id": {"type": "string", "description": "lowercase-with-dashes, unique in the list"},
        "name": {"type": "string"},
        "place": {"type": "string", "description": "town, island or area"},
        "category": {"type": "string", "enum": CATEGORIES},
        "description": {"type": "string", "description": "two sentences at most"},
        "why_you": {"type": "string", "description": "why it fits this group: ages, interests, budget"},
        "months": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 12},
                   "description": "months when it runs or is at its best, as a page states them; [] = all year"},
        "duration_hours": {"type": ["number", "null"]},
        "price": {
            "type": "object",
            "additionalProperties": False,
            "required": ["amount", "currency", "per"],
            "properties": {
                "amount": {"type": ["number", "null"], "description": "as the page states it; null if no page states it"},
                "currency": {"type": "string", "description": "ISO code as on the page: EUR, USD, SCR"},
                "per": {"type": "string", "enum": ["person", "group", "free"]},
            },
        },
        "min_age": {"type": ["integer", "null"]},
        "sources": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url", "title", "quote"],
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "quote": {"type": "string", "description": "one sentence copied word for word from the page"},
                },
            },
        },
        "certainty": {"type": "string", "enum": ["high", "medium", "low"]},
        "doubts": {"type": ["string", "null"], "description": "what you could not confirm"},
    },
}

DELIVER_EXPERIENCES = {
    "type": "custom",
    "name": "deliver_experiences",
    "description": "Deliver the ranked list of 10 to 15 experiences. Call it once; if it returns errors, fix them and call it again.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["experiences"],
        "properties": {"experiences": {"type": "array", "minItems": 10, "maxItems": 15, "items": EXPERIENCE}},
    },
}

RESEARCHER = {
    "name": "Trip experiences - researcher",
    "model": MODEL,
    "system": """You find travel experiences for one group of travellers. The first message is their profile as JSON:
destination, dates, budget and currency, who travels with their ages, interests, notes.

Search the web and read the page before you list an experience. An experience enters the list only if you read a
page that describes it, and you copy from that page, word for word, one sentence that supports it: the quote. Prefer
official pages (tourism boards, parks, museums, the operator itself) over blogs and aggregators.

Deliver 10 to 15 experiences, best fit first, with one call to deliver_experiences. Copy a price with its currency as
the page states it, per person or per group; if no page states a price, amount is null. Do not convert currencies and
do not add anything up: the app does the arithmetic. Months are the ones a page gives; [] only if it runs all year.

When you are not sure of a price, a season or a minimum age, say so in doubts and set certainty to low. "Not found"
is an allowed answer, a guessed number is not. If deliver_experiences returns errors, fix those and call it again.""",
    "tools": [toolset(search=True), DELIVER_EXPERIENCES],
}
