"""Execute a skill via a LabUtopia controller (docs/03, 08).

``SimBackend`` implements the loop's ``Backend`` protocol on top of a ``SimSession``: it drives the
scripted controller, then reports the post-state. Object **poses** come from sim GT each call;
**held / relations** are tracked symbolically (updated by the skill's ``effects`` on success),
because LabUtopia exposes no gripper-held flag — a W1 simplification (geometric held-check is W2).
"""

from __future__ import annotations

from ..scene.scene_graph import SceneGraph
from .registry import Candidate


class SimBackend:
    """Backend protocol over a live SimSession (Isaac Sim is reached only via the adapter)."""

    _REL_KEYS = ("is_in", "is_on", "near")

    def __init__(self, session, induce_failure: bool = False):
        self.session = session
        self.induce_failure = induce_failure          # recovery split: fail the first execute
        self._attempts = 0
        self._held = None
        self._relations: dict[str, set[tuple[str, str]]] = {k: set() for k in self._REL_KEYS}
        self.last_outcome: dict = {"ok": None, "stopped": False, "disturbed": None}

    def scene_graph(self) -> SceneGraph:
        sg = self.session.build_scene_graph(held=self._held)
        for rel, edges in self._relations.items():
            sg.relations.setdefault(rel, set()).update(edges)
        return sg

    def execute(self, candidate: Candidate) -> bool:
        self._attempts += 1
        if self.induce_failure and self._attempts == 1:
            return False                              # induced first-attempt failure (no sim) -> retry
        self.session.select(candidate.args.get("target"))   # W2: pick the grounded object
        raw_ok = self.session.run_skill(candidate.skill.controller)
        stop = getattr(self.session, "_last_stop", None)     # B1b runtime disturbance stop
        self.last_outcome = {"ok": raw_ok, "stopped": stop is not None,
                             "disturbed": (stop["object"] if stop else None)}
        if raw_ok:
            # fold the skill's symbolic effects into the tracked state (held / relations)
            tmp = self.scene_graph()
            for eff in candidate.skill.effects:
                eff(candidate.args, tmp)
            self._held = tmp.held
            for rel in self._relations:
                self._relations[rel] = set(tmp.relations.get(rel, set()))
        sg = self.scene_graph()
        return raw_ok and bool(candidate.skill.success(candidate.args, sg))
