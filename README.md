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

Early development. `docs/` is the canonical design reference; code is added under `src/`.
See **[docs/README.md](docs/README.md)** for the architecture, schema, planner baselines,
safety/clarification design, evaluation metrics, and milestones.

## Note for contributors / coding agents

- The design lives in `docs/` — read it before writing code.
- This project builds on the LabUtopia codebase (cloned separately); reuse its controllers,
  `ObjectUtils`, and task/controller factories rather than reimplementing manipulation.
- Paper PDFs are **not** in this repo (copyright + size); `docs/references.md` lists arXiv links.
