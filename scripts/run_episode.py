"""Entrypoint: run a single episode with a planner config (docs/01, 09).

    uv run python scripts/run_episode.py \
        --episode benchmark/episodes/direct/pick_conical_bottle.json \
        --planner configs/planners/rule.yaml --headless

NL → schema (parser) → propose (baseline) → gate → execute (LabUtopia) → monitor → structured log.
The `rule` baseline needs no LLM key; `llm_only` uses the Anthropic client (set ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from labmate.episode_logger import EpisodeLogger          # noqa: E402
from labmate.parser.rule_parser import RuleParser          # noqa: E402
from labmate.planner.loop import PlannerConfig, run_episode  # noqa: E402
from labmate.schema.episode import Episode                 # noqa: E402


def _parser_and_client(cfg: PlannerConfig):
    # rule + scene_grounded run key-free (deterministic parsing + grounding). Only llm_only needs
    # the Anthropic client; scene_grounded can add LLM scoring later but defaults to key-free.
    if cfg.propose in ("rule", "scene_grounded"):
        return RuleParser(), None
    from labmate.llm.client import default_client          # lazy (optional dep)
    from labmate.parser.llm_parser import LLMParser
    client = default_client(cfg.llm)
    return LLMParser(client), client


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one LabMate episode.")
    ap.add_argument("--episode", required=True)
    ap.add_argument("--planner", required=True)
    ap.add_argument("--scenes-dir", default=str(REPO / "benchmark" / "scenes"))
    ap.add_argument("--out", default=str(REPO / "outputs" / "labmate"))
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    episode = Episode.load(args.episode)
    cfg = PlannerConfig.load(args.planner)
    scene_spec = json.loads((Path(args.scenes_dir) / f"{episode.scene}.json").read_text())
    parser, client = _parser_and_client(cfg)

    # Sim backend (the adapter lazy-imports Isaac Sim here, not at module load).
    from labmate.labutopia.adapter import SimSession
    from labmate.skills.executor import SimBackend

    # W2: per-episode placed objects (poses + flags) come from init_overrides; fall back to the
    # scene annotation map (W1). These drive grounding + dynamic target binding.
    episode_objects = episode.init_overrides.get("objects") if episode.init_overrides else None

    run_dir = Path(args.out) / episode.episode_id
    session = SimSession(scene_spec, run_dir=str(run_dir / "labutopia"),
                         headless=args.headless, objects=episode_objects).start()
    try:
        backend = SimBackend(session)
        result = run_episode(episode, cfg, backend, parser, client)
        # IMPORTANT: log + print BEFORE session.close() — SimulationApp.close() hard-exits the
        # process (fastShutdown), so anything after it never runs.
        log_path = EpisodeLogger(run_dir).write(result.to_log())
        # flush=True: SimulationApp.close() below hard-exits and can drop buffered stdout.
        print(f">>> episode={episode.episode_id} planner={cfg.name} "
              f"success={result.success} pc={result.pc} steps={result.steps} "
              f"decision={result.decisions[0].kind if result.decisions else None}", flush=True)
        print(f">>> log: {log_path}", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    main()
