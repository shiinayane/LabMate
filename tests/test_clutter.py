"""B1a — conservative clutter gate: ASK when a target is hemmed in (sim-free)."""

from __future__ import annotations

from labmate.interactive import run_turn
from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend, gate_traced
from labmate.scene.scene_graph import SceneGraph
from labmate.schema.instruction import InstructionSchema
from labmate.skills.registry import ground_skill

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}


def _scene(positions: dict):
    return SceneGraph.from_specs(
        [{"name": n, "category": "beaker", "pose": [p[0], p[1], 0.85], "flags": {"is_graspable": True}}
         for n, p in positions.items()], frame=FRAME)


def _left_beaker_cands(sg):
    schema = InstructionSchema(intent="pick", object_category="beaker", object_ref="the left beaker")
    return schema, ground_skill("pick", schema, sg, object_names=["beaker_a"])


# ---- scene-graph clearance ---------------------------------------------
def test_nearest_other_and_clearance():
    sg = _scene({"beaker_a": [0.30, 0.05], "beaker_b": [0.30, 0.00], "beaker_c": [0.60, -0.40]})
    assert sg.nearest_other("beaker_a")[0] == "beaker_b"
    assert abs(sg.clearance("beaker_a") - 0.05) < 1e-6
    assert sg.clearance("beaker_c") > 0.10


# ---- gate: cluttered target -> ASK (feasibility) -----------------------
def test_gate_clutter_asks():
    sg = _scene({"beaker_a": [0.30, 0.05], "beaker_b": [0.30, 0.00]})
    schema, cands = _left_beaker_cands(sg)
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True, clearance=0.10)
    decision, _, gi = gate_traced(cands, schema, sg, cfg)
    assert decision.kind == "ASK" and decision.attribution == "feasibility"
    assert gi["feasibility"]["cluttered"] is True and gi["feasibility"]["blocker"] == "beaker_b"


# ---- gate: isolated target -> ACT --------------------------------------
def test_gate_isolated_acts():
    sg = _scene({"beaker_a": [0.30, 0.05], "beaker_b": [0.30, -0.40]})
    schema, cands = _left_beaker_cands(sg)
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True, clearance=0.10)
    decision, _, gi = gate_traced(cands, schema, sg, cfg)
    assert decision.kind == "ACT" and gi["feasibility"]["cluttered"] is False


# ---- switch OFF by default -> no clutter gating ------------------------
def test_clutter_off_by_default():
    sg = _scene({"beaker_a": [0.30, 0.05], "beaker_b": [0.30, 0.00]})
    schema, cands = _left_beaker_cands(sg)
    cfg = PlannerConfig(name="sg", propose="scene_grounded")   # clutter_check defaults False
    decision, _, gi = gate_traced(cands, schema, sg, cfg)
    assert decision.kind == "ACT" and gi["feasibility"] is None


# ---- interactive: clutter ASK -> human re-targets isolated -> ACT ------
def test_run_turn_clutter_then_retarget():
    sg = _scene({"beaker_a": [0.30, 0.05], "beaker_b": [0.30, 0.00], "beaker_c": [0.60, -0.40]})
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True, clearance=0.10)
    answers = iter(["beaker_c"])                          # re-target to the isolated beaker
    res = run_turn("pick the left beaker", cfg, SymbolicBackend(sg), RuleParser(),
                   lambda q: next(answers))
    assert res.asked and res.decisions[0].attribution == "feasibility"
    assert res.decisions[-1].kind == "ACT" and res.held == "beaker_c"


# ---- no cascade: spread scene (~13cm pairs) must NOT trip the grasp column --
def test_no_grasp_column_cascade_at_default_clearance():
    # demo-like spacing: neighbours ~12.8cm apart (side by side), nothing on the path -> ACT
    sg = SceneGraph.from_specs([
        {"name": "b_far_left", "category": "beaker", "pose": [0.30, 0.064, 0.85], "flags": {"is_graspable": True}},
        {"name": "b_far_right", "category": "beaker", "pose": [0.30, -0.064, 0.85], "flags": {"is_graspable": True}},
    ], frame=FRAME)
    assert abs(sg.clearance("b_far_left") - 0.128) < 1e-3      # the spacing that cascaded at 0.15
    schema = InstructionSchema(intent="pick", object_category="beaker", object_ref="the left beaker")
    cands = ground_skill("pick", schema, sg, object_names=["b_far_left"])
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True)   # default clearance 0.06
    decision, _, gi = gate_traced(cands, schema, sg, cfg)
    assert decision.kind == "ACT" and gi["feasibility"]["cluttered"] is False


# ---- the ASK question names an isolated same-category alternative ------
def test_clutter_question_offers_isolated_alternative():
    sg = _scene({"beaker_a": [0.30, 0.05], "beaker_b": [0.30, 0.00], "beaker_c": [0.55, -0.35]})
    schema, cands = _left_beaker_cands(sg)            # grounds to beaker_a (left), crowded by beaker_b
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True, clearance=0.10)
    decision, _, _ = gate_traced(cands, schema, sg, cfg)
    assert decision.kind == "ASK" and "beaker_c" in decision.question   # the clear-path alternative


# ---- no_feasible_skill surfaces the unmet precondition (human reason) --
def test_run_turn_no_feasible_human_reason():
    sg = SceneGraph.from_specs(
        [{"name": "b", "category": "beaker", "pose": [0.30, 0.0, 0.85], "flags": {"is_graspable": False}}],
        frame=FRAME)
    cfg = PlannerConfig(name="sg", propose="scene_grounded")    # clutter off; not graspable -> no_feasible
    res = run_turn("pick the beaker", cfg, SymbolicBackend(sg), RuleParser(), lambda q: "")
    assert res.refused and "unmet precondition" in (res.reason or "")


# ---- approach-corridor: object on the robot->target line is a blocker ---
def test_approach_blockers_on_path_only():
    sg = SceneGraph.from_specs([
        {"name": "T", "category": "beaker", "pose": [0.40, 0.00, 0.85]},
        {"name": "P", "category": "beaker", "pose": [0.10, 0.03, 0.85]},   # on the line, mid-segment
        {"name": "Q", "category": "beaker", "pose": [0.10, 0.30, 0.85]},   # off to the side
        {"name": "Z", "category": "beaker", "pose": [0.50, 0.00, 0.85]},   # beyond the target
    ], frame=FRAME)
    names = [b[0] for b in sg.approach_blockers("T", 0.08)]
    assert "P" in names and "Q" not in names and "Z" not in names


# ---- the motivating case: grasp column OK (~13cm) but a 3rd object on the path -> ASK
def test_path_blocker_asks_even_when_grasp_column_clear():
    sg = SceneGraph.from_specs([
        {"name": "beaker_x", "category": "beaker", "pose": [0.36, 0.22, 0.85], "flags": {"is_graspable": True}},
        {"name": "bottle_y", "category": "conical_flask", "pose": [0.28, 0.12, 0.85], "flags": {"is_graspable": True}},
    ], frame=FRAME)
    assert sg.clearance("beaker_x") > 0.10                  # nearest-neighbour says "fine"
    schema = InstructionSchema(intent="pick", object_category="beaker")
    cands = ground_skill("pick", schema, sg, object_names=["beaker_x"])
    cfg = PlannerConfig(name="sg", propose="scene_grounded", clutter_check=True,
                        clearance=0.10, corridor_radius=0.08)
    decision, _, gi = gate_traced(cands, schema, sg, cfg)
    assert decision.kind == "ASK" and decision.attribution == "feasibility"
    assert gi["feasibility"]["path_blockers"] == ["bottle_y"]   # caught on the path, not as a neighbour
