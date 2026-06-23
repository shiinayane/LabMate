"""Referring-expression resolution — deterministic grounding (docs/02, 04).

Maps an ``InstructionSchema`` (category + raw ``object_ref``) onto a specific scene object using the
scene graph: spatial qualifiers (left/right/nearest/farthest) from the robot frame, attribute
qualifiers (empty/full/hot/capped/dirty/clean) from flags/state, and relational ones (near/in X) from
the computed relations. No LLM — this determinism *is* the scene-grounded contribution; the LLM only
scores the candidates this returns. A genuinely ambiguous reference is flagged (W3 will ASK).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schema.instruction import OBJECT_CATEGORIES, InstructionSchema
from .scene_graph import CapState, SceneGraph


@dataclass
class GroundingResult:
    candidates: list[str] = field(default_factory=list)   # ranked object names that match
    target: str | None = None                             # best/chosen object
    ambiguous: bool = False                               # >1 equally-valid survivor
    rules_fired: list[str] = field(default_factory=list)  # which filters applied (for trace/logs)

    @property
    def resolved(self) -> bool:
        return self.target is not None and not self.ambiguous


_SIDES = ("left", "right")
_ATTR_TESTS = {
    "empty": lambda o: o.is_empty,
    "full": lambda o: o.is_filled,
    "filled": lambda o: o.is_filled,
    "hot": lambda o: o.flags.is_hot,
    "capped": lambda o: o.flags.cap_state == CapState.closed,
    "open": lambda o: o.is_open,
    "dirty": lambda o: (not o.is_clean) or o.flags.contaminated,
    "contaminated": lambda o: o.flags.contaminated,
    "clean": lambda o: o.is_clean,
    "hazardous": lambda o: o.flags.is_hazardous,
}


def _anchor_after(text: str, keyword: str, sg: SceneGraph) -> list[str]:
    """Objects named/categorised by the words following `keyword` (e.g. 'near the heater')."""
    idx = text.find(keyword)
    if idx < 0:
        return []
    tail = text[idx + len(keyword):]
    anchors: list[str] = []
    for cat in OBJECT_CATEGORIES:
        if cat.replace("_", " ") in tail or cat in tail:
            anchors += sg.names_of_category(cat)
    for name in sg.objects:                       # also allow explicit object names
        if name.lower() in tail:
            anchors.append(name)
    return anchors


def resolve(schema: InstructionSchema, sg: SceneGraph) -> GroundingResult:
    """Resolve the schema's referred object against the scene graph."""
    fired: list[str] = []
    if schema.object_category:
        cands = sg.names_of_category(schema.object_category)
        fired.append(f"category:{schema.object_category}")
    else:
        cands = list(sg.objects)
    if not cands:
        return GroundingResult(candidates=[], target=None, ambiguous=False, rules_fired=fired)

    text = (schema.object_ref or "").lower()

    # direct name match wins (e.g. a clarification oracle answer that names the object)
    for name in cands:
        if name.lower() in text:
            return GroundingResult(candidates=[name], target=name, ambiguous=False,
                                   rules_fired=fired + [f"name-match:{name}"])

    # spatial: side
    for side in _SIDES:
        if side in text:
            filt = [n for n in cands if sg.side_of(n) == side]
            if filt:
                cands = filt
                fired.append(f"side:{side}")

    # relational: near / in <anchor>
    for kw, rel in (("near", "near"), ("inside", "is_in"), (" in ", "is_in")):
        if kw in text:
            anchors = _anchor_after(text, kw, sg)
            if anchors:
                filt = [n for n in cands if any(sg.has_relation(rel, n, a) for a in anchors)]
                if filt:
                    cands = filt
                    fired.append(f"{rel}:{'+'.join(anchors)}")

    # attribute filters
    for word, test in _ATTR_TESTS.items():
        if word in text:
            filt = [n for n in cands if test(sg.objects[n])]
            if filt:
                cands = filt
                fired.append(f"attr:{word}")

    # ranking: nearest / farthest pick a single best deterministically
    if any(w in text for w in ("nearest", "closest")):
        cands = sorted(cands, key=lambda n: sg.distance_to_robot(n) or float("inf"))
        return GroundingResult(candidates=cands, target=cands[0], ambiguous=False,
                               rules_fired=fired + ["nearest"])
    if any(w in text for w in ("farthest", "furthest")):
        cands = sorted(cands, key=lambda n: sg.distance_to_robot(n) or float("-inf"), reverse=True)
        return GroundingResult(candidates=cands, target=cands[0], ambiguous=False,
                               rules_fired=fired + ["farthest"])

    target = cands[0] if cands else None
    return GroundingResult(candidates=cands, target=target, ambiguous=len(cands) > 1,
                           rules_fired=fired)


def resolve_quantity(schema: InstructionSchema, sg: SceneGraph) -> list[str]:
    """The first `quantity` objects matching the (optionally qualified) reference (docs/07 count)."""
    res = resolve(schema, sg)
    pool = res.candidates or (sg.names_of_category(schema.object_category)
                              if schema.object_category else list(sg.objects))
    n = max(1, int(schema.quantity or 1))
    return pool[:n]
