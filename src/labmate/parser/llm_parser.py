"""LLM parser — NL → InstructionSchema via constrained JSON (docs/02, 04).

Emits ONLY the InstructionSchema (the client's tool-use guarantees valid JSON, which we then
validate with pydantic). Used by the ``llm_only`` baseline; the ``rule`` baseline uses
``RuleParser`` and needs no key.
"""

from __future__ import annotations

from ..llm.client import LLMClient
from ..schema.instruction import InstructionSchema

_SYSTEM = (
    "You convert a single natural-language lab instruction into the InstructionSchema JSON. "
    "Use only the canonical object categories and skill intents. Fill missing_slots with the names "
    "of slots you cannot determine. Never output free text or robot actions — only the schema."
)


class LLMParser:
    def __init__(self, client: LLMClient):
        self.client = client
        self._schema = InstructionSchema.model_json_schema()

    def parse(self, instruction: str) -> InstructionSchema:
        raw = self.client.complete_json(_SYSTEM, instruction, self._schema)
        return InstructionSchema.model_validate(raw)
