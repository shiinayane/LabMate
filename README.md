# LabMate

**A clarification- and safety-aware benchmark + execution framework for natural-language
human-robot collaboration in scientific laboratories.**

A researcher gives a lab robot a natural instruction — *"clean the beaker on the left"*,
*"bring two test tubes"* — and the robot must decide which object is meant, whether to ask
for clarification, whether the action is safe (and refuse if not), execute via simulated lab
skills, and recover from failures. LabMate turns this full loop into a reproducible benchmark
**and** proposes a framework that outperforms LLM-only / end-to-end VLA baselines on it.
Built on [LabUtopia](https://arxiv.org/abs/2505.22634) (Isaac Sim).

## Repository layout

```
docs/        design & implementation reference (start at docs/README.md)
  references.md   pointers to prior work (arXiv links; no PDFs)
src/         framework + baselines + evaluator   (added during development)
configs/     task suite + annotation schema       (added during development)
```

## Status

Under active development. **Weeks 1–2 of the MVP are done**: the unified
`NL → schema → propose → gate → execute → monitor` loop runs end-to-end on LabUtopia with the
`rule`, `llm_only`, and `scene_grounded` baselines — including deterministic referring-expression
grounding ("pick the *left* conical bottle") and an object-grounding-accuracy metric. Next: W3
(clarification router + safety shield + sequence executor + SayCan-style planner).

`docs/` is the canonical design reference; **[docs/11_implementation.md](docs/11_implementation.md)**
is the living code-map / status doc (design → files, how to run, gotchas). Start at
**[docs/README.md](docs/README.md)** for the full architecture, schema, planner baselines,
safety/clarification design, evaluation metrics, and milestones.

Quick start (env per docs/08): `uv run pytest` (sim-free tests); run one episode with
`uv run python scripts/run_episode.py --episode benchmark/episodes/reference/pick_left_conical_bottle.json --planner configs/planners/scene_grounded.yaml --headless`.

## Note for contributors / coding agents

- The design lives in `docs/` — read it before writing code.
- This project builds on the LabUtopia codebase (cloned separately); reuse its controllers,
  `ObjectUtils`, and task/controller factories rather than reimplementing manipulation.
- Paper PDFs are **not** in this repo (copyright + size); `docs/references.md` lists arXiv links.
