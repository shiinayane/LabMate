"""Deterministic affordance = precondition checker (docs/04).

``S_aff(c | scene_graph) ∈ {0, 1}`` — 1 iff every precondition of the candidate's skill holds in
the scene graph. NO learned value functions. This is the key feasibility decision and doubles as the
OOD / infeasibility filter (Text2Motion geometric-feasibility term).
"""

from __future__ import annotations

from .scene.scene_graph import SceneGraph
from .skills.definitions import Skill
from .skills.registry import Candidate


def precondition(skill: Skill, args: dict, sg: SceneGraph) -> float:
    """1.0 if all preconditions hold, else 0.0."""
    try:
        return 1.0 if all(cond(args, sg) for cond in skill.preconditions) else 0.0
    except (KeyError, AttributeError):
        # a missing arg / object means the precondition cannot be satisfied
        return 0.0


def s_aff(candidate: Candidate, sg: SceneGraph) -> float:
    return precondition(candidate.skill, candidate.args, sg)


def feasible(candidate: Candidate, sg: SceneGraph) -> bool:
    return s_aff(candidate, sg) == 1.0


def failed_preconditions(skill: Skill, args: dict, sg: SceneGraph) -> list[str]:
    """Labels of the preconditions that do NOT hold (for trace/logs). Empty == feasible."""
    failed: list[str] = []
    for cond in skill.preconditions:
        label = getattr(cond, "label", getattr(cond, "__name__", "precondition"))
        try:
            if not cond(args, sg):
                failed.append(label)
        except (KeyError, AttributeError):
            failed.append(label)
    return failed
