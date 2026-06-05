"""LLM parser — NL → InstructionSchema via constrained JSON (docs/02, 04).

Emits ONLY the InstructionSchema. We hand the client a tool schema whose ``intent`` and
``object_category`` are **enum-constrained to the canonical vocabulary**, so Claude must pick valid
values (a free-text "pick up" / "bottle" would break candidate enumeration downstream). The result
is still validated with pydantic. Used by the ``llm_only`` baseline; ``rule`` needs no key.
"""

from __future__ import annotations

from ..llm.client import LLMClient
from ..schema.instruction import INTENTS, OBJECT_CATEGORIES, InstructionSchema

_INTENTS = sorted(INTENTS)
_CATEGORIES = sorted(OBJECT_CATEGORIES)

_SYSTEM = (
    "Convert ONE natural-language lab instruction into the InstructionSchema JSON via the tool. "
    "Rules:\n"
    f"- intent MUST be one of: {', '.join(_INTENTS)}. (e.g. 'pick up'/'grab' -> pick; 'fetch' -> bring)\n"
    f"- object_category MUST be one of: {', '.join(_CATEGORIES)}, or null. "
    "Map synonyms: a 'conical bottle'/'erlenmeyer' -> conical_flask; 'test tube' -> test_tube.\n"
    "- quantity: integer (default 1). destination: a category/location or null.\n"
    "- missing_slots: names of slots you cannot determine (drives clarification).\n"
    "Never output free text or robot actions — only the schema."
)

# Tool schema: canonical fields, enum-constrained where the vocabulary is fixed.
_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": _INTENTS},
        "object_category": {"enum": _CATEGORIES + [None]},
        "object_ref": {"type": ["string", "null"]},
        "quantity": {"type": "integer"},
        "destination": {"type": ["string", "null"]},
        "missing_slots": {"type": "array", "items": {"type": "string"}},
        "safety_flag": {"type": "boolean"},
    },
    "required": ["intent"],
}


class LLMParser:
    def __init__(self, client: LLMClient):
        self.client = client

    def parse(self, instruction: str) -> InstructionSchema:
        raw = self.client.complete_json(_SYSTEM, instruction, _TOOL_SCHEMA)
        return InstructionSchema.model_validate(raw)
