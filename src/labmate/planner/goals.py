"""Goal lookahead (docs/04, Text2Motion F_sat).

`predict_goals` derives the planner's *belief* about the goal state from the (grounded) schema —
NOT from the gold `eval_function` (which stays for scoring only). The loop uses these to decide when
it's done / whether to replan; keeping them separate from the eval is what makes the experiment fair
(the planner never sees the gold success function).
"""

from __future__ import annotations

from ..scene import grounding
from ..scene.scene_graph import SceneGraph
from ..schema import predicates
from ..schema.instruction import InstructionSchema

Goal = tuple[str, list]


def predict_goals(schema: InstructionSchema, sg: SceneGraph) -> list[Goal]:
    """Symbolic goal props implied by the instruction, grounded against the scene."""
    target = grounding.resolve(schema, sg).target
    dest = schema.destination
    intent = schema.intent

    if intent == "navigate":
        return []                                  # success is reaching the location (no predicate)
    if target is None:
        return []
    if intent in ("pick", "mobile_pick"):
        return [("is_held", [target])]
    if intent == "clean":
        return [("is_clean", [target])]
    if intent == "open":
        return [("is_open", [target])]
    if intent == "close":
        return []                                  # negation; not modelled in W3
    if intent == "pour":
        return [("is_filled", [dest])] if dest else []
    if intent in ("place", "bring", "composite"):
        return [("is_on", [target, dest])] if dest else [("is_held", [target])]
    return []


def satisfied(goals: list[Goal], sg: SceneGraph) -> bool:
    """True iff every predicted goal holds in the scene. Empty goal list -> not satisfied."""
    if not goals:
        return False
    return all(predicates.evaluate(pred, sg, args) for pred, args in goals)
