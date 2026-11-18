"""The verifier agent: reopens the first source of every experience and answers confirmed, contradicted or not_sure.

It did not write the list it checks, and it can only read the URLs it is given: no web search, no repairs.
"""
from agents.shared import MODEL, toolset

VERDICT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "verdict", "url_read", "passage", "contested_fields", "note"],
    "properties": {
        "id": {"type": "string", "description": "id of the experience"},
        "verdict": {"type": "string", "enum": ["confirmed", "contradicted", "not_sure"]},
        "url_read": {"type": "string"},
        "passage": {"type": "string", "description": "what the page says, copied word for word; empty if it did not load"},
        "contested_fields": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
}

DELIVER_VERDICTS = {
    "type": "custom",
    "name": "deliver_verdicts",
    "description": "Deliver one verdict per experience, all in one call.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdicts"],
        "properties": {"verdicts": {"type": "array", "items": VERDICT}},
    },
}

VERIFIER = {
    "name": "Trip experiences - verifier",
    "model": MODEL,
    "system": """You check a list of travel experiences that another agent wrote; you did not write it. The first message
is the trip profile and the list as JSON.

For each experience open its first source URL with web_fetch and compare the page with the record: name, place,
months, price, minimum age and the quote. The verdict is "confirmed" only if the page supports the record and contains
the quote or a sentence with the same meaning; "contradicted" if the page says something different, with the fields
in contested_fields; "not_sure" if the page does not load, sits behind a login, or does not say. Copy the passage you
read word for word.

You do not search for other sources and you do not repair records: you judge what is written. Deliver every verdict
in one call to deliver_verdicts.""",
    "tools": [toolset(search=False), DELIVER_VERDICTS],
}
