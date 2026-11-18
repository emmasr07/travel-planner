# The itinerary JSON format the model must return; every item needs source, price and quoted_at.
# Also the experiences schema (schemas/experiences.schema.json), its variant for the sample datasets, and the checks
# of a researcher or verifier delivery.
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
EXPERIENCES_SCHEMA = ROOT / "schemas" / "experiences.schema.json"

# Filled by the agent later, so never in a sample.
SUGGESTION_FIELDS = ("best_time", "why_fits", "schedule")
# A sample may hold more than one delivery's worth (a delivery has at most 15): up to 25, so every interest
# can have a few.
SAMPLE_MAX_ITEMS = 25

FX_BLOCK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rate", "from", "to", "date", "source"],
    "properties": {
        "rate": {"type": "number", "exclusiveMinimum": 0},
        "from": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "to": {"const": "EUR"},
        "date": {"type": "string"},
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["provider", "url", "retrieved_at", "quote"],
            "properties": {
                "provider": {"const": "frankfurter"},
                "url": {"type": "string", "pattern": "^https?://"},
                "retrieved_at": {"type": "string"},
                "quote": {"type": "null"},
            },
        },
    },
}


def experiences_schema():
    return json.loads(EXPERIENCES_SCHEMA.read_text(encoding="utf-8"))


def sample_schema():
    """The experiences schema for code-built samples: no suggestion fields (they are rejected if present),
    no minimum count (never padded), at most SAMPLE_MAX_ITEMS, and amount_eur/fx as filled by the code."""
    schema = copy.deepcopy(experiences_schema())
    schema["properties"]["experiences"].pop("minItems", None)
    schema["properties"]["experiences"]["maxItems"] = SAMPLE_MAX_ITEMS
    experience = schema["$defs"]["experience"]
    for field in SUGGESTION_FIELDS:
        experience["required"].remove(field)
        experience["properties"].pop(field)
    price = experience["properties"]["price"]["properties"]
    price["amount_eur"] = {"type": ["number", "null"], "minimum": 0}
    price["fx"] = {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/fx"}]}
    schema["$defs"]["fx"] = FX_BLOCK
    return schema


def validate_sample(data):
    """Error messages (path: message) for a sample file's JSON; [] when valid."""
    validator = Draft202012Validator(sample_schema())
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))]


VERDICTS_SCHEMA = ROOT / "schemas" / "verdicts.schema.json"


def _errors(schema, data):
    validator = Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))]


QUICK_MAX_ITEMS = 3


def delivery_schema(min_items=True, quick=False):
    """What the researcher delivers. min_items=False for demo deliveries built from a sample, which is never padded.
    quick=True for a quick search or a swap (prompts/quick-search.md): 0 to 3 experiences."""
    schema = experiences_schema()
    if not min_items or quick:
        schema["properties"]["experiences"].pop("minItems", None)
    if quick:
        schema["properties"]["experiences"]["maxItems"] = QUICK_MAX_ITEMS
    return schema


def validate_delivery(data, min_items=True, quick=False):
    """Error messages (path: message) for a researcher delivery; [] when valid."""
    return _errors(delivery_schema(min_items, quick), data)


def validate_verdicts(data):
    """Error messages (path: message) for a verifier delivery; [] when valid."""
    return _errors(json.loads(VERDICTS_SCHEMA.read_text(encoding="utf-8")), data)
