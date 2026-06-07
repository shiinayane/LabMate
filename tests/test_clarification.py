"""W3 — clarification router, the ASK→oracle→ACT loop, saycan sequencing + recovery."""

from __future__ import annotations

from labmate.clarification import router
from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend, run_episode
from labmate.scene.scene_graph import SceneGraph
from labmate.schema.episode import Constraint, Episode, EvalFunction, Proposition
from labmate.schema.instruction import InstructionSchema

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}


def _two_beakers():
    return SceneGraph.from_specs([
        {"name": "beaker_left", "category": "beaker", "pose": [0.30, 0.20, 0.85]},
        {"name": "beaker_right", "category": "beaker", "pose": [0.30, -0.20, 0.85]},
    ], frame=FRAME)


def _s(ref=None):
    return InstructionSchema(intent="pick", object_category="beaker", object_ref=ref)


# ---- router ACT / ASK / REFUSE -----------------------------------------
def test_router_routes():
    sg = _two_beakers()
    assert router.route(_s(None), sg) == "ASK"               # 2 beakers, no qualifier -> ambiguous
    assert router.route(_s("the left beaker"), sg) == "ACT"  # qualifier resolves
    assert router.route(InstructionSchema(intent="pick", object_category="centrifuge"), sg) == "REFUSE"


# ---- ASK -> oracle answer -> resolve -> ACT ----------------------------
def test_clarification_loop_resolves_and_acts():
    ep = Episode(
        episode_id="amb", scene="mock", instruction="pick the beaker", task_type="ambiguous",
        ambiguity_type="preferences", answer="beaker_left", required_decision="ASK",
        gold_target="beaker_left",
        eval_function=EvalFunction(propositions=[Proposition(pred="is_held", args=["beaker_left"])],
                                   constraints=[Constraint(type="terminal", props=[0])]),
    )
    cfg = PlannerConfig(name="saycan", propose="saycan")
    res = run_episode(ep, cfg, SymbolicBackend(_two_beakers()), RuleParser())
    assert res.asked and res.ask_turns == 1
    assert res.decisions[0].kind == "ASK" and res.decisions[0].attribution == "clarification"
    assert res.success and res.resolved_target == "beaker_left" and res.grounding_correct is True


# ---- saycan bring = pick then place (sequence) -------------------------
def test_saycan_bring_sequence():
    sg = SceneGraph.from_specs([
        {"name": "beaker_left", "category": "beaker", "pose": [0.30, 0.20, 0.85]},
        {"name": "rack", "category": "beaker_rack", "pose": [0.30, -0.20, 0.85]},
    ], frame=FRAME)
    ep = Episode(
        episode_id="bring", scene="mock", instruction="bring the left beaker to the rack",
        task_type="composite",
        gold_schema=InstructionSchema(intent="bring", object_category="beaker",
                                      object_ref="the left beaker", destination="rack"),
        eval_function=EvalFunction(propositions=[Proposition(pred="is_on", args=["beaker_left", "rack"])],
                                   constraints=[Constraint(type="terminal", props=[0])]),
    )
    # parser would mis-handle "bring ... to the rack"; use the gold schema directly via a stub parser
    cfg = PlannerConfig(name="saycan", propose="saycan")
    res = run_episode(ep, cfg, SymbolicBackend(sg), _StubParser(ep.gold_schema))
    skills = [h[1] for h in res.history if h and h[0] == "act"]
    assert skills == ["pick(target=beaker_left)", "place(target=beaker_left, dest=rack)"]
    assert res.success


# ---- saycan recovery: fail first, retry, succeed -----------------------
def test_saycan_recovery():
    sg = SceneGraph.from_specs([
        {"name": "beaker_left", "category": "beaker", "pose": [0.30, 0.20, 0.85]},
    ], frame=FRAME)
    ep = Episode(
        episode_id="rec", scene="mock", instruction="pick the left beaker", task_type="recovery",
        induce_failure=True, gold_target="beaker_left",
        eval_function=EvalFunction(propositions=[Proposition(pred="is_held", args=["beaker_left"])],
                                   constraints=[Constraint(type="terminal", props=[0])]),
    )
    cfg = PlannerConfig(name="saycan", propose="saycan")
    res = run_episode(ep, cfg, _FailFirst(sg), RuleParser())
    assert res.success and res.recovered
    assert any(h and h[0] == "fail" for h in res.history)


class _StubParser:
    def __init__(self, schema):
        self._schema = schema

    def parse(self, instruction):
        return self._schema


class _FailFirst(SymbolicBackend):
    def __init__(self, sg0):
        super().__init__(sg0)
        self._n = 0

    def execute(self, candidate):
        self._n += 1
        if self._n == 1:
            return False                # induced first-attempt failure (no effect applied)
        return super().execute(candidate)
