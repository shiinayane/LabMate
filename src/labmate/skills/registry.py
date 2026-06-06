"""Skill registry access + candidate enumeration (docs/03, 04).

``enumerate_candidates`` grounds an InstructionSchema against the scene graph into a list of
concrete ``(skill, grounded_args)`` candidates. This is the admissible set the LLM ranks
(``llm_only``) and the affordance checker filters (``scene_grounded``) — generating candidates from
the registry + scene graph (rather than free-generating) is what guarantees plan validity (docs/04).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..scene import grounding
from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema
from .definitions import SKILLS, Skill


@dataclass
class Candidate:
    skill: Skill
    args: dict = field(default_factory=dict)
    s_llm: float = 1.0           # LLM usefulness score (uniform for rule; set by llm proposers)

    def as_text(self) -> str:
        """Canonical string form the LLM scores (never free-generated)."""
        inner = ", ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.skill.name}({inner})"


def get(name: str) -> Skill:
    if name not in SKILLS:
        raise KeyError(f"unknown skill {name!r}; known: {sorted(SKILLS)}")
    return SKILLS[name]


def all_skills() -> dict[str, Skill]:
    return dict(SKILLS)


# arg keys that bind to a scene object of the schema's object_category
_OBJECT_ARGS = {"target", "src", "container"}


def _matching_objects(schema: InstructionSchema, sg: SceneGraph) -> list[str]:
    """Scene objects that match the schema's object_category (W1 grounding; refined in W2)."""
    if schema.object_category:
        named = [o.name for o in sg.by_category(schema.object_category)]
        if named:
            return named
    # fallback: every object (lets affordance / ranking decide)
    return list(sg.objects.keys())


def ground_skill(skill_name: str, schema: InstructionSchema, sg: SceneGraph,
                 object_names: Optional[list[str]] = None) -> list[Candidate]:
    """Ground one named skill against the schema + scene graph into concrete candidate(s).

    One candidate per object in ``object_names`` (W2 grounded path) or, if omitted, per scene object
    matching the schema's ``object_category`` (W1 category-only path). Skills with no object arg
    yield a single candidate.
    """
    if skill_name not in SKILLS:
        return []
    skill = SKILLS[skill_name]
    objs = object_names if object_names is not None else _matching_objects(schema, sg)
    obj_key = next((k for k in skill.args_spec if k in _OBJECT_ARGS), None)

    cands: list[Candidate] = []
    for name in objs:
        args: dict = {}
        if obj_key is not None:
            args[obj_key] = name
        if "dest" in skill.args_spec and schema.destination:
            args["dest"] = schema.destination
        if "location" in skill.args_spec and schema.destination:
            args["location"] = schema.destination
        cands.append(Candidate(skill=skill, args=args))
        if obj_key is None:                  # skill takes no object arg → single candidate
            break
    return cands


def enumerate_candidates(schema: InstructionSchema, sg: SceneGraph) -> list[Candidate]:
    """Admissible grounded candidates for the schema's intent over the scene graph.

    W1 supports the primitive intents directly. ``bring``/``composite`` are decomposed by the
    planner (docs/03), not here; for those we fall back to the leading primitive (``pick``).
    """
    skill_name = _intent_to_skill(schema.intent)
    if skill_name is None:
        return []
    return ground_skill(skill_name, schema, sg)


def _intent_to_skill(intent: str) -> Optional[str]:
    if intent in SKILLS:
        return intent
    if intent in {"bring", "composite"}:
        return "pick"
    return None


def enumerate_grounded(schema: InstructionSchema, sg: SceneGraph) -> list[Candidate]:
    """Grounded candidates: bind the skill's object to the referring-expression resolution (W2).

    Uses the deterministic resolver (``scene.grounding``) to choose which scene object(s) the
    instruction refers to, instead of every object of the category. The resolver's ranked candidate
    list is preserved so the gate's score/affordance can still pick among an ambiguous set.
    """
    skill_name = _intent_to_skill(schema.intent)
    if skill_name is None:
        return []
    names = grounding.resolve(schema, sg).candidates
    if not names:
        return []
    return ground_skill(skill_name, schema, sg, object_names=names)
