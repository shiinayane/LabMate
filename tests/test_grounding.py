"""W2.a — scene-graph relations + deterministic grounding + scene_grounded (sim-free)."""

from __future__ import annotations

from labmate.evaluation.metrics import grounding_accuracy
from labmate.parser.rule_parser import RuleParser
from labmate.planner.baselines import propose_scene_grounded
from labmate.planner.loop import PlannerConfig, SymbolicBackend, run_episode
from labmate.scene import grounding
from labmate.scene.scene_graph import SceneGraph
from labmate.schema.episode import Constraint, Episode, EvalFunction, Proposition
from labmate.schema.instruction import InstructionSchema
from labmate.skills.registry import enumerate_grounded

FRAME = {"robot_xy": [-0.4, 0.0], "left_axis": "y", "left_sign": 1}


def _two_beakers(**over) -> SceneGraph:
    # left beaker at y=+0.2, right beaker at y=-0.2; both on the table
    objs = [
        {"name": "beaker_left", "category": "beaker", "pose": [0.30, 0.20, 0.85]},
        {"name": "beaker_right", "category": "beaker", "pose": [0.30, -0.20, 0.85]},
    ]
    for o in objs:
        o.update(over.get(o["name"], {}))
    return SceneGraph.from_specs(objs, frame=FRAME)


def _schema(ref=None, cat="beaker", intent="pick", qty=1):
    return InstructionSchema(intent=intent, object_category=cat, object_ref=ref, quantity=qty)


# ---- relations from geometry -------------------------------------------
def test_relations_and_sides():
    sg = SceneGraph.from_specs([
        {"name": "tray", "category": "tray", "pose": [0.30, 0.0, 0.80], "size": [0.4, 0.4, 0.02]},
        {"name": "tube", "category": "test_tube", "pose": [0.30, 0.05, 0.85]},
    ], frame=FRAME)
    assert sg.has_relation("is_on", "tube", "tray")
    assert sg.has_relation("near", "tube", "tray")

    sg2 = _two_beakers()
    assert sg2.side_of("beaker_left") == "left"
    assert sg2.side_of("beaker_right") == "right"


# ---- deterministic resolver --------------------------------------------
def test_resolve_left_right():
    sg = _two_beakers()
    assert grounding.resolve(_schema("the left beaker"), sg).target == "beaker_left"
    assert grounding.resolve(_schema("the right beaker"), sg).target == "beaker_right"


def test_resolve_ambiguous_and_attribute():
    sg = _two_beakers()
    r = grounding.resolve(_schema(None), sg)             # no qualifier, 2 candidates
    assert r.ambiguous and r.target == "beaker_left"     # first, but flagged ambiguous

    sg2 = _two_beakers(beaker_left={"is_empty": False}, beaker_right={"is_empty": True})
    assert grounding.resolve(_schema("the empty beaker"), sg2).target == "beaker_right"


def test_resolve_nearest():
    sg = SceneGraph.from_specs([
        {"name": "beaker_near", "category": "beaker", "pose": [0.20, 0.0, 0.85]},
        {"name": "beaker_far", "category": "beaker", "pose": [0.55, 0.0, 0.85]},
    ], frame=FRAME)
    assert grounding.resolve(_schema("the nearest beaker"), sg).target == "beaker_near"


def test_resolve_relational_near_anchor():
    sg = SceneGraph.from_specs([
        {"name": "heater", "category": "heater", "pose": [0.30, 0.30, 0.80]},
        {"name": "beaker_by_heater", "category": "beaker", "pose": [0.30, 0.25, 0.85]},
        {"name": "beaker_away", "category": "beaker", "pose": [0.30, -0.30, 0.85]},
    ], frame=FRAME)
    assert grounding.resolve(_schema("the beaker near the heater"), sg).target == "beaker_by_heater"


# ---- enumerate_grounded + metric + quantity ----------------------------
def test_enumerate_grounded_and_accuracy():
    sg = _two_beakers()
    cands = enumerate_grounded(_schema("the left beaker"), sg)
    assert [c.as_text() for c in cands] == ["pick(target=beaker_left)"]
    assert grounding_accuracy("beaker_left", "beaker_left") is True
    assert grounding_accuracy("beaker_right", "beaker_left") is False
    assert grounding_accuracy("x", None) is None


def test_resolve_quantity():
    sg = SceneGraph.from_specs([
        {"name": f"tube_{i}", "category": "test_tube", "pose": [0.3, 0.1 * i, 0.85]} for i in range(3)
    ], frame=FRAME)
    got = grounding.resolve_quantity(_schema(None, cat="test_tube", qty=2), sg)
    assert len(got) == 2 and got == ["tube_0", "tube_1"]


# ---- scene_grounded propose + full loop --------------------------------
def test_propose_scene_grounded_keyfree():
    sg = _two_beakers()
    cands = propose_scene_grounded(_schema("the left beaker"), sg, history=[], client=None)
    assert len(cands) == 1 and cands[0].args["target"] == "beaker_left"


def test_run_reference_episode_symbolic():
    ep = Episode(
        episode_id="ref_left_beaker_000",
        scene="mock",
        instruction="pick the left beaker",
        task_type="reference",
        gold_target="beaker_left",
        eval_function=EvalFunction(
            propositions=[Proposition(pred="is_held", args=["beaker_left"])],
            constraints=[Constraint(type="terminal", props=[0])],
        ),
    )
    cfg = PlannerConfig(name="scene_grounded", propose="scene_grounded")
    res = run_episode(ep, cfg, SymbolicBackend(_two_beakers()), RuleParser())
    assert res.success and res.pc == 1.0
    assert res.resolved_target == "beaker_left" and res.grounding_correct is True
    assert res.decisions[0].skill.as_text() == "pick(target=beaker_left)"
