"""B1b — runtime disturbance monitor logic + the run_turn escalation (sim-free)."""

from __future__ import annotations

import pytest

from labmate.interactive import run_turn
from labmate.parser.rule_parser import RuleParser
from labmate.planner.loop import PlannerConfig, SymbolicBackend
from labmate.safety.runtime import DisturbanceMonitor
from labmate.scene.scene_graph import SceneGraph

FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}


# ---- DisturbanceMonitor ------------------------------------------------
def test_monitor_trips_on_non_target_only():
    m = DisturbanceMonitor(target="t", threshold=0.03, deadband=0.01)
    assert not m.ready and m.update({"a": [9, 9, 9]}) is None       # no baseline yet -> never trips
    m.set_baseline({"t": [0, 0, 0], "a": [1, 0, 0], "b": [2, 0, 0]})

    assert m.update({"t": [0, 0, 0.3], "a": [1, 0, 0], "b": [2, 0, 0]}) is None   # target moved -> ignored
    assert m.update({"t": [0, 0, 0], "a": [1.005, 0, 0]}) is None                 # jitter < deadband
    assert m.update({"t": [0, 0, 0], "a": [1.02, 0, 0]}) is None                  # 2cm <= threshold

    hit = m.update({"t": [0, 0, 0], "a": [1.05, 0, 0], "b": [2, 0, 0]})           # 5cm > threshold
    assert hit is not None and hit[0] == "a" and hit[1] == pytest.approx(0.05, abs=1e-6)


def test_monitor_reports_worst_offender():
    m = DisturbanceMonitor(target="t", threshold=0.03)
    m.set_baseline({"t": [0, 0, 0], "a": [1, 0, 0], "b": [2, 0, 0]})
    hit = m.update({"a": [1.05, 0, 0], "b": [2.20, 0, 0]})          # b moved more
    assert hit[0] == "b"


# ---- run_turn escalates on a runtime stop (no silent ok=False) ---------
class _StoppedBackend(SymbolicBackend):
    """Reports a runtime disturbance stop on execute (the B1b sim path, faked)."""

    def __init__(self, sg):
        super().__init__(sg)
        self.last_outcome = {"ok": None, "stopped": False, "disturbed": None}

    def execute(self, candidate):
        self.last_outcome = {"ok": False, "stopped": True, "disturbed": "beaker_b"}
        return False                                   # halted; no effects applied


def test_run_turn_escalates_on_stop():
    sg = SceneGraph.from_specs(
        [{"name": "beaker_a", "category": "beaker", "pose": [0.30, 0.0, 0.85], "flags": {"is_graspable": True}}],
        frame=FRAME)
    cfg = PlannerConfig(name="sg", propose="scene_grounded")        # clutter off -> reaches execute
    res = run_turn("pick the beaker", cfg, _StoppedBackend(sg), RuleParser(), lambda q: "")
    assert res.stopped and res.executed == 1
    assert "beaker_b" in res.reason and res.held is None            # not pretended successful
