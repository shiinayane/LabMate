"""Episode + EvalFunction — one benchmark item (docs/02).

Merges the PARTNR triple (instruction, init state, programmatic eval) with AmbiK clarification
fields. ``Episode.model_json_schema()`` is the source for the exported JSON Schema under
``benchmark/schema/`` — code and schema never drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

from .instruction import InstructionSchema

TaskType = Literal["direct", "reference", "quantity", "composite", "ambiguous", "unsafe", "recovery"]
AmbiguityType = Literal["none", "preferences", "common_sense", "safety"]
Decision = Literal["ACT", "ASK", "REFUSE"]
SafetyTier = Literal["S0", "S1", "S2", "S3"]


class Proposition(BaseModel):
    pred: str
    args: list[Union[str, int]] = Field(default_factory=list)


class Dependency(BaseModel):
    prop: int
    depends_on: list[int] = Field(default_factory=list)


class Constraint(BaseModel):
    type: Literal["temporal", "same_arg", "terminal"]
    order: Optional[list[list[int]]] = None      # temporal: [[i, j], ...] = i before j
    props: Optional[list[int]] = None            # same_arg / terminal: prop indices
    arg: Optional[int] = None                    # same_arg: which positional arg must match


class EvalFunction(BaseModel):
    """PARTNR-style programmatic eval, evaluated over the sim-state trace (docs/02, 07)."""

    propositions: list[Proposition] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)


class Episode(BaseModel):
    episode_id: str
    scene: str                                   # LabUtopia usd / config id
    init_overrides: dict = Field(default_factory=dict)

    instruction: str
    unambiguous_counterpart: Optional[str] = None       # AmbiK paired control (AmbDif metric)

    task_type: TaskType
    ambiguity_type: AmbiguityType = "none"
    ambiguity_shortlist: list[str] = Field(default_factory=list)
    clarifying_question: Optional[str] = None
    answer: Optional[str] = None
    user_intent: Optional[str] = None            # keyword set: | synonyms, - forbidden

    gold_schema: Optional[InstructionSchema] = None
    gold_target: Optional[str] = None            # object the referring expression should resolve to
    required_decision: Decision = "ACT"          # correct first gate output
    safety_tier: SafetyTier = "S0"
    induce_failure: bool = False                  # recovery split: fail the first execute, then retry

    eval_function: EvalFunction = Field(default_factory=EvalFunction)

    model_config = {"extra": "forbid"}

    # ---- io -------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Episode":
        return cls.model_validate_json(Path(path).read_text())

    @classmethod
    def export_json_schema(cls) -> dict:
        return cls.model_json_schema()


def export_schema_file(path: str | Path) -> Path:
    """Write the Episode JSON Schema to ``path`` (used to generate benchmark/schema/)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(Episode.export_json_schema(), indent=2) + "\n")
    return p
