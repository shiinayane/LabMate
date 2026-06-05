"""Safety shield (docs/05).

W1 STUB with the final interface. The real RoboGuard-style deterministic gate (4-tier
REFUSE/STOP/CONFIRM/ALLOW over sim object flags) lands in W3. The gate (docs/04) calls
``check`` and branches on ``Verdict.kind`` — stable now so W3 only fills in the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema
from ..skills.registry import Candidate

VerdictKind = Literal["ALLOW", "REFUSE", "STOP", "CONFIRM"]


@dataclass
class Verdict:
    kind: VerdictKind = "ALLOW"
    reason: Optional[str] = None
    question: Optional[str] = None


def check(candidate: Candidate, schema: InstructionSchema, sg: SceneGraph) -> Verdict:
    """Adjudicate a candidate skill. W1: always ALLOW (no-op shield)."""
    return Verdict(kind="ALLOW")
