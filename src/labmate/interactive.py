"""Interactive turn logic for the live demo (docs/11).

One *turn* = one typed instruction driven through the same NL → schema → propose → gate → execute loop
as the benchmark (`planner.loop`), but against a **persistent** backend and with a **human** answering
clarifications (`ask_fn`) instead of the gold oracle. No gold fields, no eval_function — this is the
live demo, not scoring. Reuses the loop internals wholesale; no new decision logic lives here.

Robot motion is wired for ``pick`` only (LabUtopia's `place`/`pour`/`clean` are composite controllers
that need their own task — see docs/11). Other intents still parse → ground → gate and show the
decision + trace, but do not drive the robot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .planner import goals, loop
from .scene import grounding
from .trace import GroundingTrace, StepTrace

# skills whose LabUtopia controller runs standalone via SimSession.run_skill (audit/Explore finding)
SIM_DRIVABLE = {"pick"}

# ask_fn may return this to mean "I edited the scene (moved/removed an obstacle) — re-gate the SAME
# instruction against the new layout" (HRC: clear the path, then proceed). Distinct from a re-target
# answer (an object name) and from abandon (empty).
RETRY = "\x00retry"


def parse_edit(line: str, known_names):
    """Parse a human scene-edit command (HRC: clear an obstacle, then re-run).

    ``move <obj> <x> <y>`` | ``move <obj> aside`` | ``remove <obj>`` →
    ``("move",name,x,y)`` / ``("move_aside",name)`` / ``("remove",name)``; bad input → ``("error",msg)``;
    a non-edit line → ``None`` (the REPL then treats it as an instruction).
    """
    tok = line.split()
    if not tok or tok[0] not in ("move", "remove"):
        return None
    if len(tok) < 2:
        return ("error", f"usage: {tok[0]} <object> ...")
    name = tok[1]
    if name not in known_names:
        return ("error", f"unknown object {name!r}")
    if tok[0] == "remove":
        return ("remove", name)
    if len(tok) == 3 and tok[2] == "aside":
        return ("move_aside", name)
    if len(tok) >= 4:
        try:
            return ("move", name, float(tok[2]), float(tok[3]))
        except ValueError:
            pass
    return ("error", "usage: move <object> <x> <y> | move <object> aside")


@dataclass
class TurnResult:
    instruction: str
    decisions: list = field(default_factory=list)
    steps_trace: list = field(default_factory=list)
    executed: int = 0
    refused: bool = False
    asked: bool = False
    stopped: bool = False                # B1b: execution was halted by the runtime safety monitor
    ask_turns: int = 0
    reason: Optional[str] = None
    resolved_target: Optional[str] = None
    held: Optional[str] = None


def run_turn(instruction: str, cfg, backend, parser,
             ask_fn: Callable[[str], Optional[str]], on_step=None) -> TurnResult:
    """Drive one instruction to a decision (and, for ``pick``, real execution).

    ``ask_fn(question) -> answer | None`` is consulted on ASK; an empty/None answer abandons the turn.
    ``on_step(StepTrace)`` streams each step (live ``--verbose``-style trace).
    """
    schema = parser.parse(instruction)
    res = TurnResult(instruction=instruction)
    res.held = backend.scene_graph().held
    history: list = []

    def emit(st: StepTrace) -> None:
        res.steps_trace.append(st)
        if on_step is not None:
            on_step(st)

    for step in range(cfg.max_steps):
        sg = backend.scene_graph()
        cands = loop._propose(schema, sg, history, cfg, None)            # key-free (rule/grounded/saycan)
        decision, cand_scores, gate_info = loop.gate_traced(cands, schema, sg, cfg)
        res.decisions.append(decision)

        gres = grounding.resolve(schema, sg)
        res.resolved_target = gres.target
        st = StepTrace(
            step=step + 1,
            grounding=GroundingTrace(ref=schema.object_ref, rules_fired=gres.rules_fired,
                                     ranked=gres.candidates, resolved=gres.target,
                                     ambiguous=gres.ambiguous),
            candidates=cand_scores, gate=gate_info, decision=loop._decision_dict(decision),
        )

        if decision.kind == "ASK":
            res.asked = True
            emit(st)
            answer = ask_fn(decision.question)
            if answer == RETRY:                         # human cleared the scene -> re-gate, same schema
                continue
            if answer and res.ask_turns < 2:
                schema = loop.resolve_with_answer(schema, answer)
                res.ask_turns += 1
                history.append(("ask", answer))
                continue
            res.reason = decision.question
            break

        if decision.kind == "REFUSE":
            res.refused = True
            res.reason = decision.reason
            if decision.reason == "no_feasible_skill" and st.candidates:
                fails = sorted({f for c in st.candidates for f in c.aff_failed})
                if fails:                              # human-readable: name the unmet preconditions
                    res.reason = f"can't do that — unmet precondition(s): {', '.join(fails)}"
            emit(st)
            break

        # ACT
        cand = decision.skill
        controller = cand.skill.controller
        if controller not in SIM_DRIVABLE:
            st.execution = {"ran": False, "ok": None, "target": cand.args.get("target"),
                            "note": f"live sim wired for pick only; '{controller}' shown symbolically"}
            emit(st)
            break

        before_rel = loop._rel_set(sg)
        ok = backend.execute(cand)                                       # robot moves
        res.executed += 1
        history.append(("act", cand.as_text(), ok))
        after_sg = backend.scene_graph()
        res.held = after_sg.held
        outcome = getattr(backend, "last_outcome", None) or {}
        st.execution = {"ran": True, "ok": ok, "target": cand.args.get("target"),
                        "stopped": outcome.get("stopped"), "disturbed": outcome.get("disturbed")}
        st.scene_delta = {"held": after_sg.held,
                          "relations_added": sorted(list(r) for r in loop._rel_set(after_sg) - before_rel)}
        if outcome.get("stopped"):                  # B1b: halted on disturbance -> hand to the human
            res.stopped = True
            res.reason = f"stopped — bumped {outcome.get('disturbed')}"
            emit(st)
            break
        g = goals.predict_goals(schema, after_sg)
        sat = goals.satisfied(g, after_sg)
        st.goal_check = {"predicted": [f"{p}({', '.join(a)})" for p, a in g], "satisfied": sat}
        emit(st)
        if sat or not ok:                          # demo: one attempt per turn (no auto-retry loop)
            break
    return res
