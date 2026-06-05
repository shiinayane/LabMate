"""W1.a sim-free / LLM-free smoke tests.

Covers: predicate library + compute_pc (with a dependency + terminal + temporal constraint),
candidate enumeration + affordance, the rule proposer, the gate (ACT vs justified REFUSE), and a
full run_episode against the SymbolicBackend. No Isaac Sim, no LLM key required.
"""

from __future__ import annotations

from labmate import affordance
from labmate.evaluation.metrics import compute_pc
from labmate.parser.rule_parser import RuleParser
from labmate.planner.baselines import propose_rule
from labmate.planner.loop import PlannerConfig, SymbolicBackend, gate, run_episode
from labmate.schema.episode import Constraint, Dependency, Episode, EvalFunction, Proposition
from labmate.schema.instruction import InstructionSchema
from labmate.scene.scene_graph import SceneGraph
from labmate.skills.registry import enumerate_candidates


def _scene(graspable: bool = True, held=None, on_table=False) -> SceneGraph:
    rels = {"is_on": [["conical_bottle02", "table"]] if on_table else []}
    return SceneGraph.from_dict({
        "objects": [
            {"name": "conical_bottle02", "category": "conical_flask",
             "flags": {"is_graspable": graspable}},
            {"name": "table", "category": "tray"},
        ],
        "relations": rels,
        "held": held,
    })


# ---- predicates + compute_pc -------------------------------------------
def test_predicates_and_pc_with_constraints():
    # trace: t0 nothing held; t1 holding bottle; t2 placed on table (gripper empty)
    t0 = _scene()
    t1 = _scene(held="conical_bottle02")
    t2 = _scene(held=None, on_table=True)
    ev = EvalFunction(
        propositions=[
            Proposition(pred="is_held", args=["conical_bottle02"]),
            Proposition(pred="is_on", args=["conical_bottle02", "table"]),
        ],
        dependencies=[Dependency(prop=1, depends_on=[0])],
        constraints=[
            Constraint(type="temporal", order=[[0, 1]]),
            Constraint(type="terminal", props=[1]),
        ],
    )
    res = compute_pc(ev, [t0, t1, t2])
    assert res.success and res.pc == 1.0

    # terminal prop never holds -> partial credit, not success
    res2 = compute_pc(ev, [t0, t1])
    assert not res2.success and res2.pc < 1.0 and res2.failure_explanation


# ---- enumeration + affordance ------------------------------------------
def test_enumerate_and_affordance():
    sg = _scene(graspable=True)
    schema = InstructionSchema(intent="pick", object_category="conical_flask")
    cands = enumerate_candidates(schema, sg)
    assert [c.as_text() for c in cands] == ["pick(target=conical_bottle02)"]
    assert affordance.feasible(cands[0], sg)

    sg_blocked = _scene(graspable=False)
    assert not affordance.feasible(cands[0], sg_blocked)


# ---- rule proposer ------------------------------------------------------
def test_rule_parser_and_proposer():
    schema = RuleParser().parse("pick up the conical bottle")
    assert schema.intent == "pick" and schema.object_category == "conical_flask"
    cands = propose_rule(schema, _scene(), history=[])
    assert cands and cands[0].skill.name == "pick"
    # once a pick has executed, the single-step template is exhausted
    assert propose_rule(schema, _scene(held="conical_bottle02"),
                        history=[("act", "pick(target=conical_bottle02)", True)]) == []


# ---- gate: ACT vs justified REFUSE -------------------------------------
def test_gate_act_and_refuse():
    cfg = PlannerConfig(name="rule", propose="rule")
    schema = InstructionSchema(intent="pick", object_category="conical_flask")

    sg_ok = _scene(graspable=True)
    d = gate(enumerate_candidates(schema, sg_ok), schema, sg_ok, cfg)
    assert d.kind == "ACT" and d.skill.as_text() == "pick(target=conical_bottle02)"

    sg_bad = _scene(graspable=False)
    d2 = gate(enumerate_candidates(schema, sg_bad), schema, sg_bad, cfg)
    assert d2.kind == "REFUSE" and d2.reason == "no_feasible_skill"


# ---- full loop on the symbolic backend ---------------------------------
def test_run_episode_symbolic():
    ep = Episode(
        episode_id="pick_smoke_000",
        scene="mock",
        instruction="pick up the conical bottle",
        task_type="direct",
        gold_schema=InstructionSchema(intent="pick", object_category="conical_flask",
                                      expected_skill_sequence=[]),
        eval_function=EvalFunction(
            propositions=[Proposition(pred="is_held", args=["conical_bottle02"])],
            constraints=[Constraint(type="terminal", props=[0])],
        ),
    )
    cfg = PlannerConfig(name="rule", propose="rule")
    backend = SymbolicBackend(_scene(graspable=True))
    res = run_episode(ep, cfg, backend, RuleParser())

    assert res.success and res.pc == 1.0
    assert res.decisions[0].kind == "ACT"
    log = res.to_log()
    assert log["success"] and log["episode_id"] == "pick_smoke_000"


def test_episode_json_schema_exports():
    schema = Episode.export_json_schema()
    assert schema["title"] == "Episode" and "properties" in schema
