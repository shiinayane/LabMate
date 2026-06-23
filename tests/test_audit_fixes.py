"""Regression tests for the audit-fix batch (P1 logic/eval). P0 sim fixes are verified in sim."""

from __future__ import annotations

from types import SimpleNamespace as NS

from labmate import affordance
from labmate.evaluation.metrics import recovery_rate
from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend, run_episode
from labmate.schema import predicates
from labmate.schema.episode import Constraint, Episode, EvalFunction, Proposition
from labmate.schema.instruction import InstructionSchema
from labmate.scene.scene_graph import SceneGraph
from labmate.skills.registry import ground_skill

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}


def _tubes(n):
    return SceneGraph.from_specs(
        [{"name": f"t{i}", "category": "test_tube", "pose": [0.30, 0.05 * i, 0.85]} for i in range(n)],
        frame=FRAME,
    )


# ---- #5: count_ge enforces a real threshold (count alone collapses to >=1) ----
def test_count_ge_threshold():
    assert predicates.evaluate("count_ge", _tubes(1), ["test_tube", None, 2]) is False
    assert predicates.evaluate("count_ge", _tubes(2), ["test_tube", None, 2]) is True
    # the bug we route around: bare count with one object is already truthy
    assert predicates.evaluate("count", _tubes(1), ["test_tube"]) is True


# ---- #6: recovery_rate credits only genuine recoveries -----------------
def test_recovery_rate_no_credit_for_plain_success():
    pairs = [
        (NS(recovered=True, success=True), NS(induce_failure=True, task_type="recovery")),
        (NS(recovered=False, success=True), NS(induce_failure=False, task_type="recovery")),
    ]
    assert recovery_rate(pairs) == 0.5    # only the truly-recovered one, not the plain success


# ---- #7: pour binds `dest` and is feasible (was permanently s_aff=0) ----
def test_pour_binds_dest_and_is_feasible():
    sg = SceneGraph.from_specs([
        {"name": "src_beaker", "category": "beaker", "pose": [0.30, 0.0, 0.85]},
        {"name": "dst_beaker", "category": "beaker", "pose": [0.30, 0.20, 0.85]},
    ], frame=FRAME)
    sg.held = "src_beaker"
    sg.get("src_beaker").is_filled = True
    schema = InstructionSchema(intent="pour", object_category="beaker", destination="dst_beaker")
    cands = ground_skill("pour", schema, sg, object_names=["src_beaker"])
    assert cands and cands[0].args.get("dest") == "dst_beaker"
    assert affordance.failed_preconditions(cands[0].skill, cands[0].args, sg) == []   # no KeyError('dst')
    assert affordance.s_aff(cands[0], sg) == 1.0


# ---- #8: max_retries bounds retries (no infinite loop) -----------------
class _AlwaysFail(SymbolicBackend):
    def execute(self, candidate):
        return False                      # never applies effects


def _fail_episode():
    return Episode(
        episode_id="af", scene="mock", instruction="pick the left beaker", task_type="recovery",
        gold_target="beaker_left",
        eval_function=EvalFunction(propositions=[Proposition(pred="is_held", args=["beaker_left"])],
                                   constraints=[Constraint(type="terminal", props=[0])]),
    )


def _graspable_beaker():
    return SceneGraph.from_specs(
        [{"name": "beaker_left", "category": "beaker", "pose": [0.30, 0.20, 0.85],
          "flags": {"is_graspable": True}}], frame=FRAME)


def test_max_retries_one_tries_twice_then_gives_up():
    cfg = PlannerConfig(name="saycan", propose="saycan", max_retries=1)
    res = run_episode(_fail_episode(), cfg, _AlwaysFail(_graspable_beaker()), RuleParser())
    acts = [h for h in res.history if h and h[0] == "act"]
    assert len(acts) == 2                 # initial + exactly one retry
    assert res.attribution == "execution" and not res.success and not res.recovered


def test_max_retries_zero_no_retry():
    cfg = PlannerConfig(name="saycan", propose="saycan", max_retries=0)
    res = run_episode(_fail_episode(), cfg, _AlwaysFail(_graspable_beaker()), RuleParser())
    acts = [h for h in res.history if h and h[0] == "act"]
    assert len(acts) == 1                 # no retry
    assert res.attribution == "execution"
