"""Run every episode × planner config **sim-free** and dump structured logs (docs/07).

    uv run python scripts/run_benchmark.py                 # rule + scene_grounded + saycan (key-free)
    uv run python scripts/run_benchmark.py --with-llm      # also run llm_only (needs ANTHROPIC_API_KEY)

W4 MVP: the paper's headline metrics are *decision-level* (grounding, ask, refusal, safety tier,
attribution) — they do NOT depend on whether the arm physically grasped. So we drive the same
`run_episode` pipeline over a deterministic `SymbolicBackend` (built from each episode's
`init_overrides`), with NO Isaac Sim. Fast, reproducible, one process for the whole suite.

Output: one JSON object per (episode, planner) line in `outputs/eval/results.jsonl`. Each row is the
episode's `to_log()` plus a `gold` block (the episode's reference fields) so `evaluate.py` is
self-contained. NOTE: each run OVERWRITES results.jsonl with only the planners it ran — pass every
planner you want compared in a single invocation. Physical-execution success-rate via real sim is
intentionally out of scope (docs/12).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from labmate.parser.rule_parser import RuleParser          # noqa: E402
from labmate.planner.loop import PlannerConfig, SymbolicBackend, run_episode  # noqa: E402
from labmate.scene.scene_graph import SceneGraph           # noqa: E402
from labmate.schema.episode import Episode                 # noqa: E402

# Robot frame for grounding (left/right, approach corridor). Matches the sim adapter (Franka base at
# [-0.4, 0]) and the scene-graph example; an episode may override via init_overrides.frame.
DEFAULT_FRAME = {"robot_xy": [-0.4, 0.0], "left_sign": 1}
GOLD_FIELDS = ("required_decision", "safety_tier", "task_type", "induce_failure", "gold_target")
KEY_FREE = ("rule", "scene_grounded", "saycan")


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency) so --with-llm picks up a gitignored ANTHROPIC_API_KEY."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parser_and_client(cfg: PlannerConfig):
    """Same logic as run_episode.py: deterministic baselines are key-free; only llm_only needs a client."""
    if cfg.propose in KEY_FREE:
        return RuleParser(), None
    from labmate.llm.client import default_client          # lazy (optional dep)
    from labmate.parser.llm_parser import LLMParser
    client = default_client(cfg.llm)
    return LLMParser(client), client


def _scene_graph(episode: Episode) -> SceneGraph:
    ov = episode.init_overrides or {}
    objs = ov.get("objects") or []
    return SceneGraph.from_specs(objs, frame=ov.get("frame") or DEFAULT_FRAME,
                                 held=ov.get("held"), scene_flags=ov.get("scene_flags"))


def run_one(episode: Episode, cfg: PlannerConfig, parser, client) -> dict:
    """One sim-free episode → a results row (its to_log() + the gold reference block)."""
    backend = SymbolicBackend(_scene_graph(episode), induce_failure=episode.induce_failure)
    res = run_episode(episode, cfg, backend, parser, client)
    row = res.to_log()
    row["gold"] = {f: getattr(episode, f) for f in GOLD_FIELDS}
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the LabMate benchmark sim-free → results.jsonl.")
    ap.add_argument("--episodes-dir", default=str(REPO / "benchmark" / "episodes"))
    ap.add_argument("--planners-dir", default=str(REPO / "configs" / "planners"))
    ap.add_argument("--planners", nargs="*", default=list(KEY_FREE),
                    help="planner config names (without .yaml). Default: the 3 key-free baselines.")
    ap.add_argument("--with-llm", action="store_true",
                    help="also run llm_only (needs ANTHROPIC_API_KEY; loaded from .env if present)")
    ap.add_argument("--out", default=str(REPO / "outputs" / "eval"))
    args = ap.parse_args()

    planners = list(args.planners)
    if args.with_llm and "llm_only" not in planners:
        planners.append("llm_only")
    if "llm_only" in planners:
        _load_dotenv(REPO / ".env")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("!! llm_only requested but ANTHROPIC_API_KEY not set — skipping it.", flush=True)
            planners = [p for p in planners if p != "llm_only"]

    episodes = sorted(Path(args.episodes_dir).glob("**/*.json"))
    if not episodes:
        sys.exit(f"no episodes under {args.episodes_dir}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    rows, n_err = [], 0
    for name in planners:
        cfg = PlannerConfig.load(Path(args.planners_dir) / f"{name}.yaml")
        parser, client = _parser_and_client(cfg)
        for ep_path in episodes:
            episode = Episode.load(ep_path)
            try:
                rows.append(run_one(episode, cfg, parser, client))
            except Exception as exc:                       # keep going; one bad episode ≠ whole run
                n_err += 1
                print(f"!! {name} / {episode.episode_id}: {type(exc).__name__}: {exc}", flush=True)
        print(f"== {name}: {len(episodes)} episodes", flush=True)

    results_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f">>> wrote {len(rows)} rows ({len(planners)} planners × {len(episodes)} episodes) "
          f"to {results_path} (overwrites prior results — pass ALL planners in one run)"
          + (f"  [{n_err} errors]" if n_err else ""), flush=True)


if __name__ == "__main__":
    main()
