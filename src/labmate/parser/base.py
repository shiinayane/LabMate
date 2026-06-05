"""Parser interface (docs/02).

A parser maps a typed natural-language instruction to an ``InstructionSchema``. Two implementations:
``RuleParser`` (no LLM, used by the ``rule`` baseline + as a deterministic fallback) and
``LLMParser`` (constrained JSON via the Anthropic client, W1.c).
"""

from __future__ import annotations

from typing import Protocol

from ..schema.instruction import InstructionSchema


class Parser(Protocol):
    def parse(self, instruction: str) -> InstructionSchema: ...
