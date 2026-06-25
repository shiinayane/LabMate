"""Per-step decision trace (docs/07) — *why* the gate chose / asked / refused at each step.

The episode log used to keep only the final ``Decision`` per step; everything the gate reasoned over
(the candidate set, each candidate's ``s_llm`` / ``s_aff`` / combined score, which grounding rule
fired, the router/shield/affordance stage verdicts, why a candidate was rejected) was discarded.
These dataclasses capture that, and ``render_trace`` turns it into a human-readable narrative.

Plain dataclasses (not pydantic) — internal, cheap, with ``to_dict`` for JSON logging. Nothing here
imports the sim; it is built from values the loop already computes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class CandidateScore:
    action: str                              # Candidate.as_text(), e.g. "pick(target=conical_bottle02)"
    s_llm: float
    s_aff: float
    score: float                             # scoring.combine(s_llm, s_aff, alpha, beta)
    chosen: bool = False
    aff_failed: list[str] = field(default_factory=list)   # failed preconditions when s_aff == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroundingTrace:
    ref: Optional[str] = None                # the raw referring expression
    rules_fired: list[str] = field(default_factory=list)
    ranked: list[str] = field(default_factory=list)
    resolved: Optional[str] = None
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepTrace:
    step: int
    grounding: Optional[GroundingTrace] = None
    candidates: list[CandidateScore] = field(default_factory=list)
    gate: dict[str, Any] = field(default_factory=dict)     # {router, shield, affordance}
    decision: dict[str, Any] = field(default_factory=dict)  # kind/skill/question/reason/attribution/tier/care
    execution: Optional[dict[str, Any]] = None             # {ran, ok, target}
    scene_delta: Optional[dict[str, Any]] = None           # {held, relations_added}
    goal_check: Optional[dict[str, Any]] = None            # {predicted, satisfied}
    llm: Optional[dict[str, Any]] = None                   # {system, user, tool, response} (flagged)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["grounding"] = self.grounding.to_dict() if self.grounding else None
        d["candidates"] = [c.to_dict() for c in self.candidates]
        return d


# ---- human-readable narrative ------------------------------------------
def _fmt_candidates(cands: list[CandidateScore]) -> list[str]:
    lines = []
    for c in cands:
        mark = " <- chosen" if c.chosen else ""
        why = f"  [fails: {', '.join(c.aff_failed)}]" if c.aff_failed else ""
        lines.append(f"      {c.action:<34} s_llm={c.s_llm:.2f} s_aff={c.s_aff:.2f} "
                     f"score={c.score:.2f}{mark}{why}")
    return lines


def render_step(st: StepTrace) -> str:
    """One step's narrative block."""
    out: list[str] = [f"STEP {st.step}"]

    g = st.grounding
    if g is not None:
        rules = " ".join(g.rules_fired) if g.rules_fired else "(none)"
        amb = " AMBIGUOUS" if g.ambiguous else ""
        out.append(f"  grounding: ref={g.ref!r} rules=[{rules}] "
                   f"ranked={g.ranked} -> {g.resolved}{amb}")

    if st.candidates:
        out.append("  candidates:")
        out += _fmt_candidates(st.candidates)
    else:
        out.append("  candidates: (none)")

    gate = st.gate or {}
    r, s, fz, a = gate.get("router"), gate.get("shield"), gate.get("feasibility"), gate.get("affordance")
    if r:
        out.append(f"  gate.router    : {r.get('token')} ({r.get('reason')})")
    if s:
        rule = f" rule={s.get('rule')}" if s.get("rule") else ""
        reason = f" reason={s.get('reason')}" if s.get("reason") else ""
        out.append(f"  gate.shield    : {s.get('kind')} [{s.get('tier')}]{rule}{reason}")
    if fz:
        clr = fz.get("clearance")
        clr_s = f"{clr * 100:.0f}cm" if isinstance(clr, (int, float)) else "n/a"
        pb = fz.get("path_blockers") or []
        out.append(f"  gate.feasibility: target={fz.get('target')} clearance={clr_s} "
                   f"path_blockers={pb} cluttered={fz.get('cluttered')}")
    if a:
        out.append(f"  gate.affordance: applied={a.get('applied')} refiltered={a.get('refiltered')}")

    d = st.decision or {}
    extra = ""
    if d.get("kind") == "ACT" and d.get("skill"):
        extra = f" {d['skill']}"
    elif d.get("kind") == "ASK":
        extra = f" {d.get('question')}"
    elif d.get("kind") == "REFUSE":
        extra = f" reason={d.get('reason')} tier={d.get('tier')}"
    out.append(f"  -> {d.get('kind')}{extra}  [attribution={d.get('attribution')}]")

    if st.execution is not None:
        e = st.execution
        out.append(f"  exec: target={e.get('target')} ran={e.get('ran')} ok={e.get('ok')}")
    if st.scene_delta is not None:
        sd = st.scene_delta
        out.append(f"  scene: held={sd.get('held')} +relations={sd.get('relations_added')}")
    if st.goal_check is not None:
        gc = st.goal_check
        out.append(f"  goal: predicted={gc.get('predicted')} satisfied={gc.get('satisfied')}")
    if st.llm is not None:
        out.append(f"  llm: tool={st.llm.get('tool')} response={st.llm.get('response')}")
    return "\n".join(out)


def render_trace(result) -> str:
    """Full per-episode narrative from an ``EpisodeResult`` with ``steps_trace``."""
    head = [
        f"=== episode {result.episode_id}  planner={result.planner} ===",
        f"instruction: {getattr(result, 'instruction', '') or ''}".rstrip(),
        f"schema: intent={result.schema.intent} category={result.schema.object_category} "
        f"ref={result.schema.object_ref!r} missing={result.schema.missing_slots}",
        "",
    ]
    body = [render_step(st) for st in getattr(result, "steps_trace", [])]
    tail = [
        "",
        f"OUTCOME: success={result.success} pc={result.pc} "
        f"refused={result.refused} asked={result.asked} ask_turns={result.ask_turns} "
        f"executed={result.executed} recovered={result.recovered}",
        f"grounding_correct={result.grounding_correct} "
        f"(resolved={result.resolved_target} gold={result.gold_target})",
    ]
    return "\n".join(head + ["\n".join(body)] + tail) + "\n"
