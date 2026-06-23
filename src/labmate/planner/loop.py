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
from ..trace import CandidateScore, GroundingTrace, StepTrace
from . import baselines, goals, scoring


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
    max_retries: int = 1             # closed-loop retries on execution failure (recovery/replan)
    trace_llm: bool = False          # capture raw LLM prompt/response into the step trace
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
    attribution: Optional[str] = None  # parse|grounding|clarification|safety|planning|execution
    tier: Optional[str] = None        # safety tier (S0..S3) when the shield decided
    care: bool = False                # SAFE_SLOW: execute with a care flag (S1)


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
    """Joint clarification + safety + affordance arbiter (docs/04). Deterministic.

    Order: clarification router (ASK / REFUSE-absent) → safety shield (REFUSE/STOP/CONFIRM/SAFE_SLOW)
    → affordance filter. Every non-ACT decision carries a per-stage ``attribution`` (07). See
    ``gate_traced`` for the same logic plus a structured per-step trace.
    """
    return gate_traced(cands, schema, sg, cfg)[0]


def gate_traced(cands: list[Candidate], schema: InstructionSchema, sg: SceneGraph,
                cfg: PlannerConfig) -> tuple[Decision, list[CandidateScore], dict]:
    """``gate`` + the candidate scores and per-stage gate verdicts it reasoned over (07 trace)."""
    gate_info: dict = {"router": None, "shield": None, "affordance": None}

    def key(c: Candidate) -> float:
        a = affordance.s_aff(c, sg) if cfg.affordance else 1.0
        return scoring.combine(c.s_llm, a, cfg.alpha, cfg.beta)

    best = scoring.argmax(cands, key) if cands else None

    # score every admissible candidate for the trace (cheap, deterministic)
    cand_scores: list[CandidateScore] = []
    for c in cands:
        a = affordance.s_aff(c, sg) if cfg.affordance else 1.0
        cand_scores.append(CandidateScore(
            action=c.as_text(), s_llm=c.s_llm, s_aff=a,
            score=scoring.combine(c.s_llm, a, cfg.alpha, cfg.beta),
            chosen=(c is best),
            aff_failed=affordance.failed_preconditions(c.skill, c.args, sg) if a == 0.0 else [],
        ))

    if cfg.clarification:
        tok, reason = router.route_explain(schema, sg)
        gate_info["router"] = {"token": tok, "reason": reason}
        if tok == "REFUSE":
            return Decision("REFUSE", reason="target_absent", attribution="grounding"), cand_scores, gate_info
        if tok == "ASK":
            return (Decision("ASK", question=router.question(schema, sg), attribution="clarification"),
                    cand_scores, gate_info)
    if not cands:
        return Decision("REFUSE", reason="no_candidate", attribution="grounding"), cand_scores, gate_info

    care = False
    if cfg.safety:
        v = shield.check(best, schema, sg)
        gate_info["shield"] = {"kind": v.kind, "tier": v.tier, "rule": v.rule, "reason": v.reason}
        if v.kind in ("REFUSE", "STOP"):
            return (Decision("REFUSE", reason=v.reason or v.kind.lower(), attribution="safety", tier=v.tier),
                    cand_scores, gate_info)
        if v.kind == "CONFIRM":
            return Decision("ASK", question=v.question, attribution="safety"), cand_scores, gate_info
        care = (v.kind == "SAFE_SLOW")

    refiltered = False
    if cfg.affordance and affordance.s_aff(best, sg) == 0.0:
        feasible = [c for c in cands if affordance.feasible(c, sg)]
        if not feasible:
            gate_info["affordance"] = {"applied": True, "refiltered": False}
            return Decision("REFUSE", reason="no_feasible_skill", attribution="planning"), cand_scores, gate_info
        best = scoring.argmax(feasible, key)
        refiltered = True
        for cs in cand_scores:
            cs.chosen = (cs.action == best.as_text())
    gate_info["affordance"] = {"applied": cfg.affordance, "refiltered": refiltered}

    return Decision("ACT", skill=best, care=care), cand_scores, gate_info


def _propose(schema, sg, history, cfg: PlannerConfig, client) -> list[Candidate]:
    if cfg.propose == "rule":
        return baselines.propose_rule(schema, sg, history)
    if cfg.propose == "llm_only":
        return baselines.propose_llm_only(schema, sg, history, client)
    if cfg.propose == "scene_grounded":
        return baselines.propose_scene_grounded(schema, sg, history, client)
    if cfg.propose == "saycan":
        return baselines.propose_saycan(schema, sg, history, client)
    raise NotImplementedError(f"unknown propose={cfg.propose!r}")


def resolve_with_answer(schema: InstructionSchema, answer: str) -> InstructionSchema:
    """Apply the clarification oracle's answer: disambiguate the referent + clear missing slots."""
    return schema.model_copy(update={"object_ref": answer, "missing_slots": []})


# ---- result -------------------------------------------------------------
@dataclass
class EpisodeResult:
    episode_id: str
    planner: str
    schema: InstructionSchema
    instruction: str = ""                         # the raw NL (schema may be mutated by clarify)
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
    attribution: Optional[str] = None            # stage that drove the outcome (07)
    ask_turns: int = 0                           # clarification rounds taken
    care: bool = False                           # any SAFE_SLOW care flag raised
    safety_tier: Optional[str] = None            # tier when the shield blocked
    executed: int = 0                            # # of skills actually run (URR "did-not-execute")
    recovered: bool = False                      # a failure occurred but the episode still succeeded
    steps_trace: list[StepTrace] = field(default_factory=list)   # per-step reasoning trace (07)

    def to_log(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "planner": self.planner,
            "instruction": self.instruction,
            "schema": self.schema.model_dump(),
            "decisions": [
                {"kind": d.kind, "skill": d.skill.as_text() if d.skill else None,
                 "question": d.question, "reason": d.reason, "attribution": d.attribution,
                 "tier": d.tier, "care": d.care}
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
            "attribution": self.attribution,
            "ask_turns": self.ask_turns,
            "care": self.care,
            "safety_tier": self.safety_tier,
            "executed": self.executed,
            "recovered": self.recovered,
            "steps_trace": [st.to_dict() for st in self.steps_trace],
        }


def _decision_dict(d: Decision) -> dict[str, Any]:
    return {"kind": d.kind, "skill": d.skill.as_text() if d.skill else None,
            "question": d.question, "reason": d.reason, "attribution": d.attribution,
            "tier": d.tier, "care": d.care}


def _rel_set(sg: SceneGraph) -> set:
    return {(rel, *edge) for rel, edges in sg.relations.items() for edge in edges}


def run_episode(episode: Episode, cfg: PlannerConfig, backend: Backend, parser,
                client=None, on_step=None) -> EpisodeResult:
    """NL → schema → propose → gate → execute → monitor (docs/01).

    ``on_step(StepTrace)`` is called once per step as it completes (live ``--verbose`` streaming /
    the future interactive demo); default no-op.
    """
    schema = parser.parse(episode.instruction)
    result = EpisodeResult(episode_id=episode.episode_id, planner=cfg.name, schema=schema,
                           instruction=episode.instruction)

    trace: list[SceneGraph] = [backend.scene_graph().model_copy(deep=True)]
    history: list[tuple] = []

    def emit(st: StepTrace) -> None:
        result.steps_trace.append(st)
        if on_step is not None:
            on_step(st)

    # grounding metric: resolve the referring expression against the initial scene (07)
    result.resolved_target = grounding.resolve(schema, trace[0]).target
    result.gold_target = episode.gold_target
    result.grounding_correct = grounding_accuracy(result.resolved_target, episode.gold_target)

    failed_once = False
    for step in range(cfg.max_steps):
        result.steps = step + 1
        sg = backend.scene_graph()
        cands = _propose(schema, sg, history, cfg, client)
        decision, cand_scores, gate_info = gate_traced(cands, schema, sg, cfg)
        result.decisions.append(decision)

        gres = grounding.resolve(schema, sg)
        st = StepTrace(
            step=step + 1,
            grounding=GroundingTrace(ref=schema.object_ref, rules_fired=gres.rules_fired,
                                     ranked=gres.candidates, resolved=gres.target,
                                     ambiguous=gres.ambiguous),
            candidates=cand_scores, gate=gate_info, decision=_decision_dict(decision),
        )
        if cfg.trace_llm and client is not None and getattr(client, "last_exchange", None):
            st.llm = client.last_exchange

        if decision.kind == "ASK":
            result.asked = True
            # clarification loop: consult the gold oracle answer, resolve, re-enter (<=2 turns)
            if result.ask_turns < 2 and episode.answer:
                schema = resolve_with_answer(schema, episode.answer)
                result.schema = schema
                result.ask_turns += 1
                history.append(("ask", episode.answer))
                result.resolved_target = grounding.resolve(schema, backend.scene_graph()).target
                result.grounding_correct = grounding_accuracy(result.resolved_target, episode.gold_target)
                emit(st)
                continue
            result.reason = decision.question
            result.attribution = decision.attribution or "clarification"
            emit(st)
            break

        if decision.kind == "REFUSE":
            result.refused = True
            result.reason = decision.reason
            result.attribution = decision.attribution or "safety"
            result.safety_tier = decision.tier
            emit(st)
            break

        cand = decision.skill
        result.care = result.care or decision.care
        before_rel = _rel_set(sg)
        ok = backend.execute(cand)
        result.executed += 1
        history.append(("act", cand.as_text(), ok))
        if not ok:
            failed_once = True
            history.append(("fail", cand.as_text()))
        after_sg = backend.scene_graph()
        trace.append(after_sg.model_copy(deep=True))

        st.execution = {"ran": True, "ok": ok, "target": cand.args.get("target")}
        st.scene_delta = {"held": after_sg.held,
                          "relations_added": sorted(list(r) for r in _rel_set(after_sg) - before_rel)}

        # closed-loop stop on the planner's predicted goals (decoupled from the gold eval_function)
        stop = False
        if cfg.monitor:
            g = goals.predict_goals(schema, after_sg)
            sat = goals.satisfied(g, after_sg)
            st.goal_check = {"predicted": [f"{p}({', '.join(a)})" for p, a in g], "satisfied": sat}
            stop = sat
        emit(st)
        if stop:
            break
        # a failed execute does not stop the loop: a goal-directed planner (saycan) re-proposes the
        # same skill next iteration → recovery/replan, bounded by max_steps.

    pcres = monitor.evaluate(episode.eval_function, trace)
    result.pc = pcres.pc
    result.success = pcres.success
    result.recovered = failed_once and result.success
    result.history = history
    if not result.refused and not result.asked and result.attribution is None and not result.success:
        result.attribution = "execution"
    return result
