"""Interactive demo turn logic (sim-free over SymbolicBackend). Robot motion = pick only."""

from __future__ import annotations

from labmate.interactive import run_turn
from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend
from labmate.scene.scene_graph import SceneGraph

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}
CFG = PlannerConfig(name="scene_grounded", propose="scene_grounded")


def _two_bottles(flags=None):
    f = flags or {"is_graspable": True}
    return SceneGraph.from_specs([
        {"name": "conical_bottle02", "category": "conical_flask", "pose": [0.28, 0.12, 0.82], "flags": f},
        {"name": "conical_bottle03", "category": "conical_flask", "pose": [0.28, -0.12, 0.82], "flags": f},
    ], frame=FRAME)


def _never_ask(_q):
    raise AssertionError("ask_fn should not be called")


# ---- ACT: pick the left -> robot executes ------------------------------
def test_turn_act_pick_left():
    res = run_turn("pick the left conical bottle", CFG, SymbolicBackend(_two_bottles()),
                   RuleParser(), _never_ask)
    assert res.decisions[-1].kind == "ACT"
    assert res.executed == 1 and res.held == "conical_bottle02"
    assert res.resolved_target == "conical_bottle02"


# ---- ASK -> human answers -> ACT ---------------------------------------
def test_turn_ask_then_resolve():
    answers = iter(["conical_bottle02"])
    res = run_turn("pick a conical bottle", CFG, SymbolicBackend(_two_bottles()),
                   RuleParser(), lambda q: next(answers))
    assert res.asked and res.ask_turns == 1
    assert res.decisions[0].kind == "ASK" and res.decisions[-1].kind == "ACT"
    assert res.executed == 1 and res.held == "conical_bottle02"


# ---- ASK abandoned (empty answer) -> no execution ----------------------
def test_turn_ask_abandoned():
    res = run_turn("pick a conical bottle", CFG, SymbolicBackend(_two_bottles()),
                   RuleParser(), lambda q: "")
    assert res.asked and res.executed == 0 and res.held is None


# ---- REFUSE: hazardous target -> nothing runs --------------------------
def test_turn_refuse_hazardous():
    sg = SceneGraph.from_specs(
        [{"name": "conical_bottle02", "category": "conical_flask", "pose": [0.28, 0.0, 0.82],
          "flags": {"is_graspable": True, "is_hazardous": True}}], frame=FRAME)
    res = run_turn("pick the conical bottle", CFG, SymbolicBackend(sg), RuleParser(), _never_ask)
    assert res.refused and res.executed == 0
    assert res.steps_trace[0].gate["shield"]["tier"] == "S3"
