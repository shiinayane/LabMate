"""Rich step-trace logging — candidates, per-candidate scores, gate-stage verdicts, narrative.

Sim-free: the trace is built from values the loop already computes, exercised on SymbolicBackend.
"""

from __future__ import annotations

from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend, run_episode
from labmate.scene.scene_graph import SceneGraph
from labmate.schema.episode import Constraint, Episode, EvalFunction, Proposition
from labmate.trace import render_trace

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}


def _two_bottles(flags=None):
    f = flags or {"is_graspable": True}
    return SceneGraph.from_specs([
        {"name": "conical_bottle02", "category": "conical_flask", "pose": [0.28, 0.06, 0.82], "flags": f},
        {"name": "conical_bottle03", "category": "conical_flask", "pose": [0.28, -0.06, 0.82], "flags": f},
    ], frame=FRAME)


def _eval_held(name):
    return EvalFunction(propositions=[Proposition(pred="is_held", args=[name])],
                        constraints=[Constraint(type="terminal", props=[0])])


def _ep(**kw):
    kw.setdefault("scene", "mock")
    kw.setdefault("eval_function", _eval_held("conical_bottle02"))
    return Episode(**kw)


# ---- ACT: candidates scored, chosen marked, grounding rule recorded ----
def test_trace_reference_act_records_scores_and_rule():
    ep = _ep(episode_id="ref", instruction="pick the left conical bottle", task_type="reference",
             gold_target="conical_bottle02")
    cfg = PlannerConfig(name="scene_grounded", propose="scene_grounded")
    res = run_episode(ep, cfg, SymbolicBackend(_two_bottles()), RuleParser())

    st = res.steps_trace[0]
    assert st.candidates, "candidate set must be captured"
    chosen = [c for c in st.candidates if c.chosen]
    assert len(chosen) == 1 and chosen[0].action == "pick(target=conical_bottle02)"
    # per-candidate scores present
    assert chosen[0].s_aff == 1.0 and chosen[0].score >= 0.0 and chosen[0].aff_failed == []
    # grounding rule + gate stages recorded
    assert "side:left" in st.grounding.rules_fired
    assert st.gate["router"]["token"] == "ACT"
    assert st.gate["shield"]["kind"] == "EXECUTE"
    assert st.execution and st.execution["ok"] and st.goal_check["satisfied"]


# ---- rejected candidate records WHY (failed precondition) --------------
def test_trace_records_affordance_failure():
    # not graspable -> s_aff 0, aff_failed names the precondition
    res = run_episode(
        _ep(episode_id="naff", instruction="pick the left conical bottle", task_type="reference",
            gold_target="conical_bottle02", eval_function=_eval_held("conical_bottle02")),
        PlannerConfig(name="scene_grounded", propose="scene_grounded"),
        SymbolicBackend(_two_bottles(flags={"is_graspable": False})), RuleParser(),
    )
    st = res.steps_trace[0]
    c = st.candidates[0]
    assert c.s_aff == 0.0 and "graspable(target)" in c.aff_failed


# ---- ASK: router reason is recorded ------------------------------------
def test_trace_ambiguous_records_router_reason():
    ep = _ep(episode_id="amb", instruction="pick the conical bottle", task_type="ambiguous",
             ambiguity_type="preferences", answer="conical_bottle02", required_decision="ASK",
             gold_target="conical_bottle02")
    cfg = PlannerConfig(name="scene_grounded", propose="scene_grounded")
    res = run_episode(ep, cfg, SymbolicBackend(_two_bottles()), RuleParser())

    st0 = res.steps_trace[0]
    assert st0.decision["kind"] == "ASK"
    assert st0.gate["router"]["reason"] == "ambiguous:2"
    assert st0.execution is None                      # nothing ran on an ASK step


# ---- REFUSE: shield rule + tier recorded -------------------------------
def test_trace_unsafe_records_shield_rule():
    sg = SceneGraph.from_specs(
        [{"name": "conical_bottle02", "category": "conical_flask", "pose": [0.28, 0.0, 0.82],
          "flags": {"is_hazardous": True, "is_graspable": True}}],
        frame={"robot_xy": [-0.4, 0.0]},
    )
    ep = _ep(episode_id="u", instruction="pick the conical bottle", task_type="unsafe",
             required_decision="REFUSE", safety_tier="S3")
    cfg = PlannerConfig(name="scene_grounded", propose="scene_grounded")
    res = run_episode(ep, cfg, SymbolicBackend(sg), RuleParser())

    st = res.steps_trace[0]
    assert st.decision["kind"] == "REFUSE" and st.decision["attribution"] == "safety"
    assert st.gate["shield"]["tier"] == "S3" and st.gate["shield"]["rule"]


# ---- narrative renders + round-trips through to_log ---------------------
def test_render_trace_and_to_log():
    ep = _ep(episode_id="ref", instruction="pick the left conical bottle", task_type="reference",
             gold_target="conical_bottle02")
    cfg = PlannerConfig(name="scene_grounded", propose="scene_grounded")
    res = run_episode(ep, cfg, SymbolicBackend(_two_bottles()), RuleParser())

    text = render_trace(res)
    assert "STEP 1" in text and "pick(target=conical_bottle02)" in text and "ACT" in text

    log = res.to_log()
    assert log["steps_trace"] and log["steps_trace"][0]["candidates"][0]["action"]
