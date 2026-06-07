"""Scene graph: objects + flags + relations, from LabUtopia sim GT (08) or a plain dict (tests).

This is the W1 minimal shape — enough for the predicates the MVP needs (notably the `pick` path).
Full grounding / richer relations land in W2. The sim-backed builder lives in
``labmate.labutopia.adapter`` (the only module that imports Isaac Sim); here we keep a pure,
sim-free data model so the schema/planner/affordance layers stay unit-testable on any machine.

See docs/02_schema.md (object vocabulary, state flags) and docs/08_labutopia_integration.md.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Geometry thresholds (metres) for deriving relations from poses. Mirrored from LabUtopia's own
# containment/proximity checks (controllers/LiquidMixing_controller.py, utils/task_utils.py pour).
R_NEAR = 0.15        # near(a,b): xy distance below this
R_ON = 0.08          # is_on(a,b): a's centre within this xy radius of b's footprint
DZ_ON = 0.12         # is_on(a,b): a's centre this far above b's top, at most
R_IN = 0.06          # is_in(a,b): a's centre within this xy radius of b


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


class Frame(BaseModel):
    """Viewpoint for resolving egocentric relations like left/right (docs/02 qualifiers).

    ``robot_xy`` is the robot base [x, y]; ``left_sign`` says which way along ``left_axis`` is the
    robot's LEFT (+1 means larger y = left, the assumed Franka convention — VERIFY on the first sim
    run and flip if needed).
    """

    robot_xy: list[float] = [0.0, 0.0]
    left_axis: str = "y"
    left_sign: int = 1


def _xy(o: Optional["SceneObject"]) -> Optional[tuple[float, float]]:
    if o is None or not o.pose:
        return None
    return float(o.pose[0]), float(o.pose[1])


def _z(o: Optional["SceneObject"]) -> Optional[float]:
    if o is None or not o.pose or len(o.pose) < 3:
        return None
    return float(o.pose[2])


def _z_top(o: Optional["SceneObject"]) -> Optional[float]:
    z = _z(o)
    if z is None:
        return None
    h = float(o.size[2]) if o and o.size and len(o.size) >= 3 else 0.0
    return z + h / 2.0


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
    frame: Optional[Frame] = None
    scene_flags: set[str] = Field(default_factory=set)   # env hazards: spill / broken_glass / obstruction

    model_config = {"arbitrary_types_allowed": True}

    # ---- construction ---------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict) -> "SceneGraph":
        """Build from a plain dict with EXPLICIT relations (tests / W1 adapter).

        ``data`` shape::

            {
              "objects": [ {"name": .., "category": .., "flags": {..}, ...}, ... ],
              "relations": {"is_in": [["a","b"], ...], "is_on": [...], "near": [...]},
              "held": "obj_or_null",
              "frame": {"robot_xy": [-0.4, 0.0], "left_sign": 1},
            }
        """
        objects = {o["name"]: SceneObject(**o) for o in data.get("objects", [])}
        relations = {r: set() for r in _RELATIONS}
        for rel, edges in (data.get("relations") or {}).items():
            relations.setdefault(rel, set()).update(tuple(e) for e in edges)
        frame = Frame(**data["frame"]) if data.get("frame") else None
        return cls(objects=objects, relations=relations, held=data.get("held"), frame=frame,
                   scene_flags=set(data.get("scene_flags") or []))

    @classmethod
    def from_specs(cls, objects: list[dict], frame: Optional[dict] = None,
                   held: Optional[str] = None, scene_flags: Optional[list[str]] = None) -> "SceneGraph":
        """Build from object specs and COMPUTE relations from poses+sizes (W2; sim adapter).

        Each spec is the ``SceneObject`` dict (name/category/pose/size/flags/...). Relations
        is_in/is_on/near are derived geometrically; left/right is computed on demand via ``side_of``.
        """
        objs = {o["name"]: SceneObject(**o) for o in objects}
        rels = {r: set() for r in _RELATIONS}
        names = list(objs)
        for a in names:
            for b in names:
                if a == b:
                    continue
                oa, ob = objs[a], objs[b]
                xa, xb = _xy(oa), _xy(ob)
                if xa is None or xb is None:
                    continue
                d = math.hypot(xa[0] - xb[0], xa[1] - xb[1])
                if d < R_NEAR:
                    rels["near"].add((a, b))
                za, btop = _z(oa), _z_top(ob)
                if za is not None and btop is not None:
                    if d < R_ON and 0.0 <= (za - btop) < DZ_ON:
                        rels["is_on"].add((a, b))
                    bz = _z(ob)
                    if d < R_IN and bz is not None and bz <= za < btop:
                        rels["is_in"].add((a, b))
        f = Frame(**frame) if frame else None
        return cls(objects=objs, relations=rels, held=held, frame=f,
                   scene_flags=set(scene_flags or []))

    # ---- queries --------------------------------------------------------
    def get(self, name: str) -> Optional[SceneObject]:
        return self.objects.get(name)

    def by_category(self, category: str) -> list[SceneObject]:
        return [o for o in self.objects.values() if o.category == category]

    def names_of_category(self, category: str) -> list[str]:
        return [o.name for o in self.by_category(category)]

    def side_of(self, name: str) -> Optional[str]:
        """'left' | 'right' relative to the robot frame, or None if no frame/pose."""
        o, xy = self.get(name), _xy(self.get(name))
        if self.frame is None or xy is None:
            return None
        axis = 1 if self.frame.left_axis == "y" else 0
        delta = (o.pose[axis] - self.frame.robot_xy[axis]) * self.frame.left_sign
        if abs(delta) < 1e-6:
            return None
        return "left" if delta > 0 else "right"

    def distance_to_robot(self, name: str) -> Optional[float]:
        xy = _xy(self.get(name))
        if self.frame is None or xy is None:
            return None
        rx, ry = self.frame.robot_xy[0], self.frame.robot_xy[1]
        return math.hypot(xy[0] - rx, xy[1] - ry)

    def has_relation(self, rel: str, a: str, b: str) -> bool:
        edges = self.relations.get(rel, set())
        if (a, b) in edges:
            return True
        if rel == "near" and (b, a) in edges:   # near is symmetric
            return True
        return False

    def gripper_empty(self) -> bool:
        return self.held is None
