"""Path A — human edits the scene (move/remove) to clear an obstacle, then the robot ACTs (sim-free)."""

from __future__ import annotations

from labmate.interactive import parse_edit, run_turn
from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend
from labmate.scene.scene_graph import SceneGraph

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}


# ---- command parsing ---------------------------------------------------
def test_parse_edit():
    known = {"a", "b"}
    assert parse_edit("move a 0.2 -0.3", known) == ("move", "a", 0.2, -0.3)
    assert parse_edit("move a aside", known) == ("move_aside", "a")
    assert parse_edit("remove b", known) == ("remove", "b")
    assert parse_edit("pick the a", known) is None              # not an edit command
    assert parse_edit("move c 1 2", known)[0] == "error"        # unknown object
    assert parse_edit("move a", known)[0] == "error"            # missing coords
    assert parse_edit("move a 0.2", known)[0] == "error"        # 3 tokens, not 'aside'
    assert parse_edit("move a -0.3 0.01", known) == ("move", "a", -0.3, 0.01)  # negative/float ok


# ---- the HRC loop: ASK -> human clears the path -> ACT -----------------
def test_move_obstacle_then_acts():
    sg = SceneGraph.from_specs([
        {"name": "beaker_x", "category": "beaker", "pose": [0.36, 0.22, 0.85], "flags": {"is_graspable": True}},
        {"name": "bottle_y", "category": "conical_flask", "pose": [0.28, 0.12, 0.85], "flags": {"is_graspable": True}},
    ], frame=FRAME)
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True)
    backend = SymbolicBackend(sg)

    r1 = run_turn("pick the beaker", cfg, backend, RuleParser(), lambda q: "")
    assert r1.asked and r1.decisions[-1].attribution == "feasibility" and r1.executed == 0

    # human moves the obstacle aside — mimics session.move_object updating the declared pose
    backend.scene_graph().objects["bottle_y"].pose = [0.0, 0.45, 0.85]

    r2 = run_turn("pick the beaker", cfg, backend, RuleParser(), lambda q: "")
    assert r2.decisions[-1].kind == "ACT" and r2.executed == 1 and r2.held == "beaker_x"


# ---- RETRY: inline edit at the ASK prompt re-gates the same turn -------
def test_run_turn_retry_after_inline_edit():
    from labmate.interactive import RETRY
    sg = SceneGraph.from_specs([
        {"name": "beaker_x", "category": "beaker", "pose": [0.36, 0.22, 0.85], "flags": {"is_graspable": True}},
        {"name": "bottle_y", "category": "conical_flask", "pose": [0.28, 0.12, 0.85], "flags": {"is_graspable": True}},
    ], frame=FRAME)
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True)
    backend = SymbolicBackend(sg)
    calls = {"n": 0}

    def ask(_q):                                   # the human clears the path inline, then RETRY
        calls["n"] += 1
        backend.scene_graph().objects["bottle_y"].pose = [0.0, 0.45, 0.85]
        return RETRY

    res = run_turn("pick the beaker", cfg, backend, RuleParser(), ask)
    assert calls["n"] == 1                          # asked once, edited inline
    assert res.decisions[-1].kind == "ACT" and res.executed == 1 and res.held == "beaker_x"
    assert res.ask_turns == 0                       # RETRY must NOT consume a clarification turn


# ---- the `open` skill grounds, gates, and executes (symbolic) ----------
def test_open_drawer_grounds_and_acts():
    sg = SceneGraph.from_specs(
        [{"name": "Cabinet_01", "category": "drawer", "pose": [0.73, 0.0, 1.15]}], frame=FRAME)
    cfg = PlannerConfig(name="sg", propose="scene_grounded")
    backend = SymbolicBackend(sg)
    res = run_turn("open the drawer", cfg, backend, RuleParser(), lambda q: "")
    assert res.decisions[-1].kind == "ACT" and res.executed == 1
    assert backend.scene_graph().get("Cabinet_01").is_open is True   # the open effect fired


# ---- reset restores the initial layout (undo move/remove) --------------
def test_reset_restores_initial_layout():
    from labmate.labutopia.adapter import SimSession            # sim-free: __init__ imports no Isaac
    objs = [
        {"name": "a", "usd_path": "/World/a", "category": "beaker", "pose": [0.30, 0.10, 0.85], "flags": {}},
        {"name": "b", "usd_path": "/World/b", "category": "beaker", "pose": [0.30, -0.10, 0.85], "flags": {}},
    ]
    s = SimSession({}, run_dir="/tmp/lm_reset_test", objects=objs)
    # simulate a move (mutated pose) + a remove (dropped from objects + index)
    s.objects[0]["pose"] = [0.0, 0.45, 0.85]
    s.objects = [o for o in s.objects if o["name"] != "b"]
    s._index_by_name = {"a": 0}

    s._restore_objects()
    assert {o["name"] for o in s.objects} == {"a", "b"}          # removed object came back
    assert next(o["pose"] for o in s.objects if o["name"] == "a") == [0.30, 0.10, 0.85]  # move undone
    assert s._index_by_name == {"a": 0, "b": 1}
