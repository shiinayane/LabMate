"""Clarification router (docs/06) — deterministic ACT / ASK / REFUSE.

Decides, per step, whether to act, ask a clarifying question, or refuse — jointly with the safety
shield (the gate calls the router first, then the shield). Deterministic and key-free, sharing the
same grounding + flag view as the shield so they never contradict. It decides from the schema + scene
ONLY (never the gold `ambiguity_type` / `required_decision`, which are eval-only).

Routing:
- target absent (no grounding candidates)            -> REFUSE  (false-presupposition)
- missing slot OR genuinely ambiguous (>1 candidate) -> ASK
- otherwise                                           -> ACT
"""

from __future__ import annotations

from ..scene import grounding
from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema


def route(schema: InstructionSchema, sg: SceneGraph) -> str:
    """Return one of "ACT" | "ASK" | "REFUSE"."""
    res = grounding.resolve(schema, sg)
    if not res.candidates:
        return "REFUSE"
    if schema.missing_slots or res.ambiguous:
        return "ASK"
    return "ACT"


def should_ask(schema: InstructionSchema, sg: SceneGraph) -> bool:
    return route(schema, sg) == "ASK"


def should_refuse(schema: InstructionSchema, sg: SceneGraph) -> bool:
    return route(schema, sg) == "REFUSE"


def question(schema: InstructionSchema, sg: SceneGraph) -> str:
    res = grounding.resolve(schema, sg)
    opts = ", ".join(res.candidates[:4]) if res.candidates else "?"
    kind = schema.object_category or "object"
    if schema.missing_slots:
        return f"Which {kind} did you mean ({', '.join(schema.missing_slots)})? Options: {opts}."
    return f"Which {kind} did you mean: {opts}?"
