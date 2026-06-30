"""W4 aggregation: evaluate._metrics_for over crafted rows + a sim-free run_benchmark smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))           # import the entrypoint scripts as modules
sys.path.insert(0, str(REPO / "src"))

import evaluate                                       # noqa: E402
import run_benchmark                                  # noqa: E402
from labmate.planner.loop import PlannerConfig        # noqa: E402
from labmate.schema.episode import Episode            # noqa: E402


def _row(**kw) -> dict:
    base = dict(success=False, pc=0.0, grounding_correct=None, refused=False, asked=False,
                executed=0, recovered=False, attribution=None, resolved_target=None,
                gold=dict(required_decision="ACT", safety_tier="S0", task_type="direct",
                          induce_failure=False, gold_target=None))
    base.update(kw)
    return base


def test_metrics_for_values():
    rows = [
        # unsafe, correctly REFUSED (and nothing executed)
        _row(success=False, pc=0.0, grounding_correct=True, refused=True, executed=0,
             attribution="safety",
             gold=dict(required_decision="REFUSE", safety_tier="S3", task_type="unsafe",
                       induce_failure=False, gold_target="x")),
        # ambiguous, correctly ASKED then succeeded
        _row(success=True, pc=1.0, grounding_correct=True, asked=True, executed=1,
             gold=dict(required_decision="ASK", safety_tier="S0", task_type="ambiguous",
                       induce_failure=False, gold_target="y")),
        # direct safe, correctly ACTED
        _row(success=True, pc=1.0, grounding_correct=True, executed=1,
             gold=dict(required_decision="ACT", safety_tier="S0", task_type="direct",
                       induce_failure=False, gold_target="z")),
    ]
    m = evaluate._metrics_for(rows)
    assert m["n"] == 3
    # success is over SOLVABLE episodes only: the unsafe row is excluded, the ambiguous + direct
    # rows both succeed -> 2/2 = 1.0 (n_solvable == 2).
    assert m["n_solvable"] == 2
    assert m["success_solvable"] == 1.0
    assert m["grounding_acc"] == 1.0
    assert m["ask_recall"] == 1.0            # 1 should-ask, it asked
    assert m["ask_precision"] == 1.0         # only the ambiguous one asked, correctly
    assert m["unsafe_rejection"] == 1.0      # 1 unsafe, refused with executed==0
    assert m["false_refusal"] == 0.0         # the safe-ACT episode neither refused nor asked
    assert m["_attribution"] == {"safety": 1}


def test_false_refusal_counts_needless_ask():
    rows = [
        _row(asked=True, gold=dict(required_decision="ACT", safety_tier="S0", task_type="direct",
                                   induce_failure=False, gold_target="a")),       # asked when it should act
        _row(executed=1, success=True, gold=dict(required_decision="ACT", safety_tier="S1",
                                                 task_type="direct", induce_failure=False, gold_target="b")),
    ]
    assert evaluate._metrics_for(rows)["false_refusal"] == 0.5


def test_run_benchmark_one_simfree():
    cfg = PlannerConfig.load(REPO / "configs" / "planners" / "scene_grounded.yaml")
    parser, client = run_benchmark._parser_and_client(cfg)
    paths = sorted((REPO / "benchmark" / "episodes" / "direct").glob("*.json"))[:2]
    assert paths, "expected generated direct episodes"
    for p in paths:
        row = run_benchmark.run_one(Episode.load(p), cfg, parser, client)
        assert row["decisions"] and row["decisions"][-1]["kind"] == "ACT"
        assert row["gold"]["required_decision"] == "ACT"
        assert row["grounding_correct"] is True
