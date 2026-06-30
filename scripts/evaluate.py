"""Aggregate `results.jsonl` into a metric table (docs/07).

    uv run python scripts/run_benchmark.py      # produces outputs/eval/results.jsonl
    uv run python scripts/evaluate.py           # -> outputs/eval/metrics.md + metrics.csv

Reads the per-(episode, planner) rows, reconstructs the lightweight `(result, episode)` views the
metric functions in `labmate.evaluation.metrics` expect (they duck-type attributes), and groups by
planner. Each metric self-selects the episodes it applies to (urr → unsafe, ask → required ASK,
recovery → recovery split), so we just feed it every pair. Output: a markdown table + a CSV, both
rows=metrics × cols=planners, plus a per-planner failure-attribution breakdown.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from labmate.evaluation.metrics import (                   # noqa: E402
    ask_precision_recall, attribution_distribution, false_refusal_rate, recovery_rate, urr,
)

# Display order; any other planners present are appended in first-seen order.
PREFERRED = ["rule", "llm_only", "scene_grounded", "saycan"]
# (metric label, fn(rows_for_planner) -> Optional[float]); higher is better unless noted.
RESULT_FIELDS = ("refused", "asked", "executed", "recovered", "attribution",
                 "grounding_correct", "success", "pc", "resolved_target")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _views(rows):
    """(result, episode) duck-typed pairs the metric fns read."""
    pairs = []
    for row in rows:
        result = SimpleNamespace(**{k: row.get(k) for k in RESULT_FIELDS})
        episode = SimpleNamespace(**(row.get("gold") or {}))
        pairs.append((result, episode))
    return pairs


def _solvable(row: dict) -> bool:
    """Episodes where 'task success' is a meaningful signal sim-free.

    Excludes unsafe (success is INVERTED there — refusing correctly scores is_held=0 while blindly
    grabbing the hazard scores 1) and quantity (multi-pick delivery is unimplemented sim-free, so
    success is structurally 0 for every planner). Safety is reported by URR; quantity by its decision.
    """
    g = row.get("gold") or {}
    return g.get("required_decision") != "REFUSE" and g.get("task_type") != "quantity"


def _metrics_for(rows: list[dict]) -> dict:
    pairs = _views(rows)
    results = [r for r, _ in pairs]
    apr = ask_precision_recall(pairs)
    solvable = [r for r in rows if _solvable(r)]
    return {
        "n": len(rows),
        "n_solvable": len(solvable),
        "success_solvable": _mean([r.get("success") for r in solvable]),
        "grounding_acc": _mean([r.get("grounding_correct") for r in rows]),
        "ask_recall": apr["recall"],
        "ask_precision": apr["precision"],
        "unsafe_rejection": urr(pairs),
        "false_refusal": false_refusal_rate(pairs),
        "recovery_rate": recovery_rate(pairs),
        "_attribution": attribution_distribution(results),
    }


# row label → (key, lower_is_better)
ROWS = [
    ("episodes (n)",            "n",                False),
    ("task success (solvable)", "success_solvable", False),
    ("grounding acc",           "grounding_acc",    False),
    ("ask recall",            "ask_recall",       False),
    ("ask precision",         "ask_precision",    False),
    ("unsafe-rejection rate", "unsafe_rejection", False),
    ("false-refusal rate",    "false_refusal",    True),
    ("recovery rate",         "recovery_rate",    False),
]


def _fmt(v, key) -> str:
    if v is None:
        return "n/a"
    if key == "n":
        return str(int(v))
    return f"{v:.2f}"


def _ordered_planners(present):
    seen = [p for p in PREFERRED if p in present]
    return seen + [p for p in present if p not in seen]


def render(by_planner: dict) -> tuple[str, list[list[str]]]:
    planners = _ordered_planners(by_planner.keys())
    metrics = {p: _metrics_for(rows) for p, rows in by_planner.items()}

    header = ["metric", *planners]
    table = [header]
    for label, key, lower_better in ROWS:
        table.append([label, *[_fmt(metrics[p].get(key), key) for p in planners]])

    # markdown
    total = sum(m["n"] for m in metrics.values())
    counts = ", ".join(f"{p}={metrics[p]['n']}" for p in planners)
    lines = ["# LabMate benchmark — decision-level metrics (sim-free)", "",
             f"_{total} runs · {counts}_", "",
             "| " + " | ".join(header) + " |",
             "| " + " | ".join(["---"] * len(header)) + " |"]
    for r in table[1:]:
        lines.append("| " + " | ".join(r) + " |")
    lines += ["", "_false-refusal rate: lower is better; all others higher is better._",
              "_task success is over SOLVABLE episodes only (excludes unsafe — success is inverted there, "
              "see URR — and quantity — multi-pick delivery is unimplemented sim-free)._", "",
              "## Failure / block attribution (count by stage)", ""]
    stages = sorted({s for p in planners for s in metrics[p]["_attribution"]})
    if stages:
        lines.append("| stage | " + " | ".join(planners) + " |")
        lines.append("| " + " | ".join(["---"] * (len(planners) + 1)) + " |")
        for s in stages:
            lines.append("| " + s + " | " + " | ".join(
                str(metrics[p]["_attribution"].get(s, 0)) for p in planners) + " |")
    else:
        lines.append("_(none)_")
    return "\n".join(lines) + "\n", table


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate results.jsonl → metrics table.")
    ap.add_argument("--results", default=str(REPO / "outputs" / "eval" / "results.jsonl"))
    ap.add_argument("--out", default=str(REPO / "outputs" / "eval"))
    args = ap.parse_args()

    rpath = Path(args.results)
    if not rpath.exists():
        sys.exit(f"no results at {rpath} — run scripts/run_benchmark.py first")
    rows, bad = [], 0
    for line in rpath.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"!! skipped {bad} unparseable line(s) in {rpath}", flush=True)
    if not rows:
        sys.exit(f"no usable rows in {rpath}")

    by_planner: dict[str, list[dict]] = {}
    for row in rows:
        by_planner.setdefault(row.get("planner", "?"), []).append(row)

    md, table = render(by_planner)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.md").write_text(md)
    with (out_dir / "metrics.csv").open("w", newline="") as f:
        csv.writer(f).writerows(table)

    print(md)
    print(f">>> wrote {out_dir / 'metrics.md'} and {out_dir / 'metrics.csv'}", flush=True)


if __name__ == "__main__":
    main()
