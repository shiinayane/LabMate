"""Skill registry / DSL (docs/03).

Each skill is a thin wrapper over a LabUtopia controller plus a declarative-ish contract used by
the affordance checker (04) and the safety shield (05). Conditions are callables over
``(args, scene_graph)`` so they can read object flags / relations directly; this keeps W1 simple
while staying inspectable. ``effects`` give a cheap symbolic transition for goal lookahead (used
from W3 — declared now so the contract is stable).

Planners may emit ONLY these skills, never raw actions (invariant in docs/01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..scene.scene_graph import LiquidId, SceneGraph

# A precondition / success test over grounded args + the scene graph.
Cond = Callable[[dict, SceneGraph], bool]
# A symbolic effect: mutate a (copied) scene graph after a successful step.
Effect = Callable[[dict, SceneGraph], None]


@dataclass
class Skill:
    name: str
    args_spec: dict[str, str]                 # arg name -> category/type hint
    preconditions: list[Cond]                 # must all hold before run (affordance, 04)
    effects: list[Effect]                     # symbolic effects applied on success (goal lookahead)
    success: Cond                             # checked from sim GT after execution (03)
    controller: str                           # LabUtopia controller_factory name (08)
    failure_reasons: list[str]
    needs_confirmation: Callable[..., bool] = field(default=lambda schema, sg: False)


# ---- small condition helpers -------------------------------------------
def is_graspable(key: str = "target") -> Cond:
    def c(args, sg):
        o = sg.get(args[key])
        return bool(o and o.flags.is_graspable)
    return c


def gripper_empty() -> Cond:
    return lambda args, sg: sg.gripper_empty()


def holding(key: str = "target") -> Cond:
    return lambda args, sg: sg.held == args[key]


def present(key: str) -> Cond:
    return lambda args, sg: sg.get(args[key]) is not None


def container_open(key: str, want: bool) -> Cond:
    def c(args, sg):
        o = sg.get(args[key])
        return bool(o and o.is_open == want)
    return c


def filled(key: str) -> Cond:
    def c(args, sg):
        o = sg.get(args[key])
        return bool(o and o.is_filled)
    return c


# ---- symbolic effects ---------------------------------------------------
def _set_held(args, sg):
    sg.held = args.get("target")


def _clear_held(args, sg):
    sg.held = None


def _set_on(args, sg):
    """Symbolic place effect: target now rests on/in its destination."""
    dest = args.get("dest")
    if dest:
        sg.relations.setdefault("is_on", set()).add((args["target"], dest))


def _set_open(key: str, val: bool) -> Effect:
    def e(args, sg):
        o = sg.get(args[key])
        if o:
            o.is_open = val
    return e


def _set_filled(key: str, val: bool) -> Effect:
    def e(args, sg):
        o = sg.get(args[key])
        if o:
            o.is_filled = val
    return e


def _set_clean(key: str, val: bool) -> Effect:
    def e(args, sg):
        o = sg.get(args[key])
        if o:
            o.is_clean = val
    return e


def _pour_unknown_liquid(schema, sg: SceneGraph) -> bool:
    # confirmation required when pouring an unknown liquid (docs/03)
    return any(o.flags.liquid_id == LiquidId.unknown for o in sg.objects.values())


# ---- the 8 MVP skills ---------------------------------------------------
def _build() -> dict[str, Skill]:
    skills: list[Skill] = [
        Skill(
            name="pick",
            args_spec={"target": "object"},
            preconditions=[is_graspable("target"), gripper_empty()],
            effects=[_set_held],
            success=holding("target"),
            controller="pick",
            failure_reasons=["object_not_found", "grasp_failed", "gripper_occupied", "timeout"],
        ),
        Skill(
            name="place",
            args_spec={"target": "object", "dest": "location"},
            preconditions=[holding("target"), present("dest")],
            effects=[_set_on, _clear_held],
            success=lambda args, sg: sg.has_relation("is_on", args["target"], args["dest"])
            or sg.has_relation("is_in", args["target"], args["dest"]),
            controller="place",
            failure_reasons=["dest_unreachable", "release_failed", "timeout"],
        ),
        Skill(
            name="open",
            args_spec={"container": "container"},
            preconditions=[container_open("container", want=False)],
            effects=[_set_open("container", True)],
            success=lambda args, sg: bool(sg.get(args["container"]) and sg.get(args["container"]).is_open),
            controller="open",
            failure_reasons=["not_reachable", "handle_missed", "timeout"],
        ),
        Skill(
            name="close",
            args_spec={"container": "container"},
            preconditions=[container_open("container", want=True)],
            effects=[_set_open("container", False)],
            success=lambda args, sg: bool(sg.get(args["container"]) and not sg.get(args["container"]).is_open),
            controller="close",
            failure_reasons=["not_reachable", "handle_missed", "timeout"],
        ),
        Skill(
            name="pour",
            args_spec={"src": "object", "dst": "object"},
            preconditions=[holding("src"), filled("src"), present("dst")],
            effects=[_set_filled("dst", True), _set_filled("src", False)],
            success=lambda args, sg: bool(sg.get(args["dst"]) and sg.get(args["dst"]).is_filled),
            controller="pour",
            failure_reasons=["spill", "src_empty", "timeout"],
            needs_confirmation=_pour_unknown_liquid,
        ),
        Skill(
            name="clean",
            args_spec={"target": "object"},
            preconditions=[present("target")],
            effects=[_set_clean("target", True)],
            success=lambda args, sg: bool(sg.get(args["target"]) and sg.get(args["target"]).is_clean),
            controller="cleanbeaker",
            failure_reasons=["no_wash_station", "incomplete", "timeout"],
        ),
        Skill(
            name="navigate",
            args_spec={"location": "location"},
            preconditions=[present("location")],
            effects=[],
            success=lambda args, sg: True,
            controller="navigation",
            failure_reasons=["no_path", "timeout"],
        ),
        Skill(
            name="mobile_pick",
            args_spec={"target": "object"},
            preconditions=[is_graspable("target"), gripper_empty()],
            effects=[_set_held],
            success=holding("target"),
            controller="mobile_pick",
            failure_reasons=["object_not_found", "grasp_failed", "timeout"],
        ),
    ]
    return {s.name: s for s in skills}


SKILLS: dict[str, Skill] = _build()
