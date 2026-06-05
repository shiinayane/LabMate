"""Scene graph: objects + flags + relations, from LabUtopia sim GT (08) or a plain dict (tests).

This is the W1 minimal shape — enough for the predicates the MVP needs (notably the `pick` path).
Full grounding / richer relations land in W2. The sim-backed builder lives in
``labmate.labutopia.adapter`` (the only module that imports Isaac Sim); here we keep a pure,
sim-free data model so the schema/planner/affordance layers stay unit-testable on any machine.

See docs/02_schema.md (object vocabulary, state flags) and docs/08_labutopia_integration.md.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LiquidId(str, Enum):
    none = "none"
    water = "water"
    unknown = "unknown"
    hazardous = "hazardous"


class CapState(str, Enum):
    open = "open"
    closed = "closed"
    none = "none"


class ObjectFlags(BaseModel):
    """Safety/affordance-relevant object attributes (set in sim, read by grounding + shield)."""

    is_graspable: bool = True
    is_hot: bool = False
    liquid_id: LiquidId = LiquidId.none
    is_fragile: bool = False
    is_hazardous: bool = False
    cap_state: CapState = CapState.none
    device_state: Optional[str] = None
    is_sample: bool = False
    contaminated: bool = False


class SceneObject(BaseModel):
    """One object in the scene. `name` is the canonical handle; `usd_path` binds to LabUtopia."""

    name: str
    category: str
    usd_path: Optional[str] = None
    pose: Optional[list[float]] = None          # [x,y,z] or [x,y,z,qw,qx,qy,qz]
    size: Optional[list[float]] = None
    flags: ObjectFlags = Field(default_factory=ObjectFlags)

    # dynamic per-object state (mutated by execution / read by predicates)
    is_clean: bool = True
    is_empty: bool = True
    is_filled: bool = False
    is_open: bool = False                        # for containers (drawer/door)


# relation names that are stored as (a, b) edges
_RELATIONS = ("is_in", "is_on", "near")


class SceneGraph(BaseModel):
    """Objects keyed by name + binary relations + gripper state.

    Relations are stored as sets of ``(a, b)`` tuples. ``near`` is treated as symmetric.
    ``held`` is the name of the object currently in the gripper (None = empty gripper).
    """

    objects: dict[str, SceneObject] = Field(default_factory=dict)
    relations: dict[str, set[tuple[str, str]]] = Field(
        default_factory=lambda: {r: set() for r in _RELATIONS}
    )
    held: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}

    # ---- construction ---------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict) -> "SceneGraph":
        """Build from a plain dict (used by tests and by the sim adapter).

        ``data`` shape::

            {
              "objects": [ {"name": .., "category": .., "flags": {..}, ...}, ... ],
              "relations": {"is_in": [["a","b"], ...], "is_on": [...], "near": [...]},
              "held": "obj_or_null",
            }
        """
        objects = {o["name"]: SceneObject(**o) for o in data.get("objects", [])}
        relations = {r: set() for r in _RELATIONS}
        for rel, edges in (data.get("relations") or {}).items():
            relations.setdefault(rel, set()).update(tuple(e) for e in edges)
        return cls(objects=objects, relations=relations, held=data.get("held"))

    # ---- queries --------------------------------------------------------
    def get(self, name: str) -> Optional[SceneObject]:
        return self.objects.get(name)

    def by_category(self, category: str) -> list[SceneObject]:
        return [o for o in self.objects.values() if o.category == category]

    def has_relation(self, rel: str, a: str, b: str) -> bool:
        edges = self.relations.get(rel, set())
        if (a, b) in edges:
            return True
        if rel == "near" and (b, a) in edges:   # near is symmetric
            return True
        return False

    def gripper_empty(self) -> bool:
        return self.held is None
