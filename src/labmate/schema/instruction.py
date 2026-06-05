"""InstructionSchema — the parser's output (docs/02).

The parser (rule or LLM) maps a typed instruction to this record. The LLM must emit ONLY this
schema (constrained / JSON mode), never free text or raw actions (invariant in docs/01).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Canonical object vocabulary shared by parser + grounding (docs/02). Kept as a frozenset for
# soft validation: unknown categories are allowed (LabUtopia assets evolve) but can be checked.
OBJECT_CATEGORIES: frozenset[str] = frozenset({
    "beaker", "conical_flask", "test_tube", "petri_dish", "bottle", "pipette", "glass_rod",
    "drawer", "door", "beaker_rack", "tray", "wash_station", "heater", "centrifuge",
    "drying_oven", "balance",
})

# Skill-level intents (docs/03) plus the composite escape hatch (decomposed by the planner).
INTENTS: frozenset[str] = frozenset({
    "pick", "place", "open", "close", "pour", "clean", "navigate", "mobile_pick",
    "bring", "composite",
})


class SkillCall(BaseModel):
    """One step of an optional plan hint. Validated against the registry, never trusted."""

    skill: str
    args: dict = Field(default_factory=dict)


class InstructionSchema(BaseModel):
    """Structured form of a natural-language instruction. Field names are normative (docs/02)."""

    intent: str
    object_category: Optional[str] = None
    object_ref: Optional[str] = None                 # raw referring expression, for grounding
    quantity: int = 1
    destination: Optional[str] = None                # category or named location, nullable
    missing_slots: list[str] = Field(default_factory=list)   # drives clarification (06)
    safety_flag: bool = False                        # parser prior; the shield (05) decides
    expected_skill_sequence: list[SkillCall] = Field(default_factory=list)  # plan hint, validated

    model_config = {"extra": "forbid"}

    def is_known_category(self) -> bool:
        return self.object_category in OBJECT_CATEGORIES
