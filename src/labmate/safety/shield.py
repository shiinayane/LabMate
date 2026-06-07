"""Safety shield (docs/05) — RoboGuard-style deterministic gate over sim flags.

The shield runs BEFORE every action in the gate (docs/04) and is the source of truth; the LLM's
``safety_flag`` guess is advisory only. 4 decision tiers map to 5 verdict kinds:

    S0 harmless        -> EXECUTE
    S1 low-risk        -> SAFE_SLOW   (execute with a care flag)
    S2 environment bad -> STOP        (broken glass / spill / clutter)
    S3 instruction bad -> REFUSE      (hazardous / unsupported)
    (clarify)          -> CONFIRM     (unknown liquid / discard a sample -> ASK)

Rules live in ``rules.py``; ``check`` returns the first matching verdict, else EXECUTE (S0).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema
from ..skills.registry import Candidate

VerdictKind = Literal["EXECUTE", "SAFE_SLOW", "STOP", "REFUSE", "CONFIRM"]

# verdict kind -> safety tier
TIER = {"EXECUTE": "S0", "SAFE_SLOW": "S1", "STOP": "S2", "REFUSE": "S3", "CONFIRM": "S1"}


@dataclass
class Verdict:
    kind: VerdictKind = "EXECUTE"
    tier: str = "S0"
    reason: Optional[str] = None
    question: Optional[str] = None

    @property
    def blocks(self) -> bool:
        """True if the action must NOT execute (REFUSE/STOP)."""
        return self.kind in ("REFUSE", "STOP")


def verdict(kind: VerdictKind, reason: Optional[str] = None, question: Optional[str] = None) -> Verdict:
    return Verdict(kind=kind, tier=TIER[kind], reason=reason, question=question)


def check(candidate: Candidate, schema: InstructionSchema, sg: SceneGraph) -> Verdict:
    """Adjudicate a candidate skill against the ordered rule set (docs/05)."""
    from .rules import RULES                     # lazy: avoids rules<->shield import cycle
    for rule in RULES:
        v = rule(candidate, schema, sg)
        if v is not None:
            return v
    return verdict("EXECUTE")
