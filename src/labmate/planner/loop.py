"""The unified episode loop (docs/01, 04).

All four baselines are this one loop with different switches (``PlannerConfig``). The
clarification + safety + affordance **gate** is the deterministic arbiter over the LLM's proposals
(invariant in docs/01). W1 wires the ``rule`` and ``llm_only`` configs; clarification/safety are
no-op stubs (W3) but the gate already branches on them so nothing changes when they fill in.

A ``Backend`` abstracts execution: ``SymbolicBackend`` (here, no sim) applies skill effects for
tests/dry-runs; the Isaac-backed executor (``labmate.skills.executor`` + ``labmate.labutopia``)
implements the same protocol in W1.b.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

import yaml

from .. import affordance, monitor
from ..clarification import router
from ..evaluation.metrics import grounding_accuracy
from ..safety import shield
from ..schema.episode import Episode
from ..schema.instruction import InstructionSchema
from ..scene import grounding
from ..scene.scene_graph import SceneGraph
from ..skills.registry import Candidate
from . import baselines, scoring


# ---- config -------------------------------------------------------------
@dataclass
class PlannerConfig:
    name: str
    propose: str = "rule"            # rule | llm_only | scene_grounded | saycan
    alpha: float = 1.0
    beta: float = 1.0
    affordance: bool = True          # gate uses the affordance filter
    clarification: bool = True       # gate consults the clarification router
    safety: bool = True              # gate consults the safety shield
    monitor: bool = True             # closed-loop goal check / stop condition
    max_steps: int = 8
    llm: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "PlannerConfig":
        known = {f for f in cls.__dataclass_fields__}            # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path: str | Path) -> "PlannerConfig":
        return cls.from_dict(yaml.safe_load(Path(path).read_text()))


# ---- decision -----------------------------------------------------------
@dataclass
class Decision:
    kind: str                         # ACT | ASK | REFUSE
    skill: Optional[Candidate] = None
    question: Optional[str] = None
    reason: Optional[str] = None


# ---- execution backend --------------------------------------------------
class Backend(Protocol):
    def scene_graph(self) -> SceneGraph: ...
    def execute(self, candidate: Candidate) -> bool: ...


class SymbolicBackend:
    """No-sim backend: applies a candidate's symbolic effects (a 'perfect executor').

    Used for unit tests and dry runs of the loop logic. Execution always 'succeeds' and mutates a
    private copy of the scene graph via ``skill.effects``.
    """

    def __init__(self, sg0: SceneGraph):
        self._sg = sg0.model_copy(deep=True)

    def scene_graph(self) -> SceneGraph:
        return self._sg

    def execute(self, candidate: Candidate) -> bool:
        for eff in candidate.skill.effects:
            eff(candidate.args, self._sg)
        return True


# ---- the gate (docs/04) -------------------------------------------------
def gate(cands: list[Candidate], schema: InstructionSchema, sg: SceneGraph,
         cfg: PlannerConfig) -> Decision:
    """Joint clarification + safety + affordance arbiter. Deterministic."""
    if cfg.clarification and router.should_ask(schema, sg):
        return Decision("ASK", question=router.question(schema, sg))
    if not cands:
        return Decision("REFUSE", reason="no_candidate")

    def key(c: Candidate) -> float:
        a = affordance.s_aff(c, sg) if cfg.affordance else 1.0
        return scoring.combine(c.s_llm, a, cfg.alpha, cfg.beta)

    best = scoring.argmax(cands, key)

    if cfg.safety:
        v = shield.check(best, schema, sg)
        if v.kind in ("REFUSE", "STOP"):
            return Decision("REFUSE", reason=v.reason or v.kind.lower())
        if v.kind == "CONFIRM":
            return Decision("ASK", question=v.question)

    if cfg.affordance and affordance.s_aff(best, sg) == 0.0:
        feasible = [c for c in cands if affordance.feasible(c, sg)]
        if not feasible:
            return Decision("REFUSE", reason="no_feasible_skill")
        best = scoring.argmax(feasible, key)

    return Decision("ACT", skill=best)


def _propose(schema, sg, history, cfg: PlannerConfig, client) -> list[Candidate]:
    if cfg.propose == "rule":
        return baselines.propose_rule(schema, sg, history)
    if cfg.propose == "llm_only":
        return baselines.propose_llm_only(schema, sg, history, client)
    if cfg.propose == "scene_grounded":
        return baselines.propose_scene_grounded(schema, sg, history, client)
    raise NotImplementedError(f"propose={cfg.propose!r} arrives in W3 (saycan)")


# ---- result -------------------------------------------------------------
@dataclass
class EpisodeResult:
    episode_id: str
    planner: str
    schema: InstructionSchema
    decisions: list[Decision] = field(default_factory=list)
    history: list[tuple] = field(default_factory=list)
    pc: float = 0.0
    success: bool = False
    refused: bool = False
    asked: bool = False
    reason: Optional[str] = None
    steps: int = 0
    resolved_target: Optional[str] = None       # what grounding resolved the ref to
    gold_target: Optional[str] = None
    grounding_correct: Optional[bool] = None     # None when the episode has no grounding target

    def to_log(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "planner": self.planner,
            "schema": self.schema.model_dump(),
            "decisions": [
                {"kind": d.kind, "skill": d.skill.as_text() if d.skill else None,
                 "question": d.question, "reason": d.reason}
                for d in self.decisions
            ],
            "history": self.history,
            "pc": self.pc,
            "success": self.success,
            "refused": self.refused,
            "asked": self.asked,
            "reason": self.reason,
            "steps": self.steps,
            "resolved_target": self.resolved_target,
            "gold_target": self.gold_target,
            "grounding_correct": self.grounding_correct,
        }


def run_episode(episode: Episode, cfg: PlannerConfig, backend: Backend, parser,
                client=None) -> EpisodeResult:
    """NL → schema → propose → gate → execute → monitor (docs/01)."""
    schema = parser.parse(episode.instruction)
    result = EpisodeResult(episode_id=episode.episode_id, planner=cfg.name, schema=schema)

    trace: list[SceneGraph] = [backend.scene_graph().model_copy(deep=True)]
    history: list[tuple] = []

    # grounding metric: resolve the referring expression against the initial scene (07)
    result.resolved_target = grounding.resolve(schema, trace[0]).target
    result.gold_target = episode.gold_target
    result.grounding_correct = grounding_accuracy(result.resolved_target, episode.gold_target)

    for step in range(cfg.max_steps):
        result.steps = step + 1
        sg = backend.scene_graph()
        cands = _propose(schema, sg, history, cfg, client)
        decision = gate(cands, schema, sg, cfg)
        result.decisions.append(decision)

        if decision.kind == "ASK":
            result.asked = True
            result.reason = decision.question
            break
        if decision.kind == "REFUSE":
            result.refused = True
            result.reason = decision.reason
            break

        cand = decision.skill
        ok = backend.execute(cand)
        history.append(("act", cand.as_text(), ok))
        if not ok:
            history.append(("fail", cand.as_text()))
        trace.append(backend.scene_graph().model_copy(deep=True))

        if cfg.monitor and monitor.satisfies(episode.eval_function, trace):
            break

    pcres = monitor.evaluate(episode.eval_function, trace)
    result.pc = pcres.pc
    result.success = pcres.success
    result.history = history
    return result
