"""Lab predicate library — booleans over the scene graph (sim GT).

Each predicate is ``fn(sg: SceneGraph, *args) -> bool``. They are registered by name so the
episode ``eval_function`` (docs/02) and the planner's goal-check (docs/04) can evaluate
``{"pred": "is_in", "args": ["beaker_03", "rack"]}`` by string. MVP minimum set per docs/02.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..scene.scene_graph import CapState, SceneGraph

Predicate = Callable[..., bool]
_REGISTRY: dict[str, Predicate] = {}


def predicate(name: str) -> Callable[[Predicate], Predicate]:
    def deco(fn: Predicate) -> Predicate:
        _REGISTRY[name] = fn
        return fn
    return deco


def get(name: str) -> Predicate:
    if name not in _REGISTRY:
        raise KeyError(f"unknown predicate {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def evaluate(name: str, sg: SceneGraph, args: list) -> bool:
    """Evaluate a predicate by name against the scene graph (used by eval_function)."""
    return bool(get(name)(sg, *args))


def names() -> list[str]:
    return sorted(_REGISTRY)


# ---- relational ---------------------------------------------------------
@predicate("is_in")
def is_in(sg: SceneGraph, obj: str, container: str) -> bool:
    return sg.has_relation("is_in", obj, container)


@predicate("is_on")
def is_on(sg: SceneGraph, obj: str, surface: str) -> bool:
    return sg.has_relation("is_on", obj, surface)


@predicate("near")
def near(sg: SceneGraph, a: str, b: str) -> bool:
    return sg.has_relation("near", a, b)


# ---- object-state -------------------------------------------------------
@predicate("is_held")
def is_held(sg: SceneGraph, obj: str) -> bool:
    return sg.held == obj


@predicate("is_clean")
def is_clean(sg: SceneGraph, obj: str) -> bool:
    o = sg.get(obj)
    return bool(o and o.is_clean)


@predicate("is_empty")
def is_empty(sg: SceneGraph, obj: str) -> bool:
    o = sg.get(obj)
    return bool(o and o.is_empty)


@predicate("is_filled")
def is_filled(sg: SceneGraph, obj: str, level: Optional[str] = None) -> bool:
    o = sg.get(obj)
    return bool(o and o.is_filled)


@predicate("is_capped")
def is_capped(sg: SceneGraph, obj: str) -> bool:
    o = sg.get(obj)
    return bool(o and o.flags.cap_state == CapState.closed)


@predicate("is_open")
def is_open(sg: SceneGraph, container: str) -> bool:
    o = sg.get(container)
    return bool(o and o.is_open)


# ---- counting -----------------------------------------------------------
@predicate("count")
def count(sg: SceneGraph, category: str, region: Optional[str] = None) -> int:
    objs = sg.by_category(category)
    if region is not None:
        objs = [o for o in objs if sg.has_relation("is_in", o.name, region)
                or sg.has_relation("is_on", o.name, region)]
    return len(objs)


@predicate("count_ge")
def count_ge(sg: SceneGraph, category: str, region: Optional[str] = None, n: int = 1) -> bool:
    """At least ``n`` objects of ``category`` (optionally in ``region``).

    `count` returns an int that `evaluate` would `bool()`-collapse to "≥1"; use this to assert a real
    quantity threshold in an eval_function (e.g. "bring **two**").
    """
    return count(sg, category, region) >= int(n)
