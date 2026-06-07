"""Executable safety rules over sim object/scene flags (docs/05).

Each rule is ``(candidate, schema, sg) -> Verdict | None`` and reads a boolean sim flag (never real
toxicity/chemistry). ``shield.check`` evaluates them in order and returns the first hit. Order = most
severe / environment-overriding first, so a spill STOPs regardless of instruction and a hazardous
target REFUSEs before softer SAFE_SLOW care flags apply.
"""

from __future__ import annotations

from typing import Optional

from ..scene.scene_graph import CapState, LiquidId, SceneGraph
from ..schema.instruction import InstructionSchema
from ..skills.registry import Candidate
from .shield import Verdict, verdict

_ENV_HAZARDS = {"spill", "broken_glass", "obstruction"}
_OBJECT_ARG_KEYS = ("target", "src", "container")


def _objs(candidate: Candidate, sg: SceneGraph):
    """Scene objects referenced by the candidate's args (target/src/container)."""
    for k in _OBJECT_ARG_KEYS:
        name = candidate.args.get(k)
        if name is not None and sg.get(name) is not None:
            yield sg.get(name)


# rule 8 — environment unsafe (broken glass / spill / clutter) STOPs regardless of instruction (S2)
def env_hazard(candidate, schema, sg) -> Optional[Verdict]:
    hit = _ENV_HAZARDS & set(sg.scene_flags)
    if hit:
        return verdict("STOP", reason=f"environment_hazard:{','.join(sorted(hit))}")
    return None


# rule 3 — hazardous target with no safe path -> REFUSE (S3, instruction unsafe)
def hazardous_target(candidate, schema, sg) -> Optional[Verdict]:
    if candidate.skill.name in ("pick", "mobile_pick", "pour"):
        for o in _objs(candidate, sg):
            if o.flags.is_hazardous:
                return verdict("REFUSE", reason=f"hazardous:{o.name}")
    return None


# rule 1 — unknown liquid being poured/aspirated/mixed -> CONFIRM
def unknown_liquid(candidate, schema, sg) -> Optional[Verdict]:
    if candidate.skill.name in ("pour",):
        for o in _objs(candidate, sg):
            if o.flags.liquid_id == LiquidId.unknown:
                return verdict("CONFIRM", question=f"{o.name} holds an unknown liquid — pour it anyway?")
    return None


# rule 6 — discarding a sample -> CONFIRM (no `discard` skill in the MVP registry; guarded for later)
def discard_sample(candidate, schema, sg) -> Optional[Verdict]:
    if candidate.skill.name == "discard":
        for o in _objs(candidate, sg):
            if o.flags.is_sample:
                return verdict("CONFIRM", question=f"{o.name} is a sample — discard it?")
    return None


# rule 2 — hot target picked bare-handed -> SAFE_SLOW (use a tool / go careful) (S1)
def hot_target(candidate, schema, sg) -> Optional[Verdict]:
    if candidate.skill.name in ("pick", "mobile_pick"):
        for o in _objs(candidate, sg):
            if o.flags.is_hot:
                return verdict("SAFE_SLOW", reason=f"hot:{o.name}")
    return None


# rule 7 — moving an uncapped hazardous-ish container -> SAFE_SLOW (stabilize first) (S1)
def open_cap_move(candidate, schema, sg) -> Optional[Verdict]:
    if candidate.skill.name in ("pick", "mobile_pick", "pour"):
        for o in _objs(candidate, sg):
            if o.flags.cap_state == CapState.open and o.is_filled:
                return verdict("SAFE_SLOW", reason=f"open_container:{o.name}")
    return None


# rule 4 — fragile target -> SAFE_SLOW (never default-speed) (S1)
def fragile_target(candidate, schema, sg) -> Optional[Verdict]:
    for o in _objs(candidate, sg):
        if o.flags.is_fragile:
            return verdict("SAFE_SLOW", reason=f"fragile:{o.name}")
    return None


# Ordered, most-severe / environment-overriding first.
RULES = [
    env_hazard,        # 8  S2
    hazardous_target,  # 3  S3
    unknown_liquid,    # 1  CONFIRM
    discard_sample,    # 6  CONFIRM
    hot_target,        # 2  S1
    open_cap_move,     # 7  S1
    fragile_target,    # 4  S1
]
