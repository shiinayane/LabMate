# 10 · Repository layout

The repo has a **dual identity**: a *framework* (the code in `src/`) and a *benchmark* (the data
in `benchmark/`). They are deliberately separate. This file is the authoritative map; the full
skeleton already exists (empty modules carry a docstring pointing at the spec that defines them).

```
labmate/                          # repo root = github LabMate
├── README.md                     # project overview + doc index
├── pyproject.toml                # packaging (src-layout), deps, tool config
├── .gitignore
│
├── docs/                         # design specs (THIS folder) — read 00→10
│
├── src/labmate/                  # the importable Python package  → `import labmate`
│   ├── schema/                   #   02 · data structures
│   │   ├── instruction.py        #      InstructionSchema (parser output)
│   │   ├── episode.py            #      Episode, EvalFunction, propositions/constraints
│   │   └── predicates.py         #      lab predicate library
│   ├── parser/                   #   NL → schema
│   │   ├── base.py · rule_parser.py · llm_parser.py
│   ├── scene/                    #   08 · sim GT → scene graph
│   │   ├── scene_graph.py · grounding.py   # grounding.py = parse_obj / referring exprs
│   ├── skills/                   #   03 · skill registry / DSL
│   │   ├── registry.py · definitions.py · executor.py
│   ├── affordance.py             #   04 · deterministic precondition checker
│   ├── planner/                  #   04 · the unified loop + 4 baselines
│   │   ├── loop.py · baselines.py · scoring.py
│   ├── safety/                   #   05 · RoboGuard-style shield
│   │   ├── shield.py · rules.py
│   ├── clarification/            #   06 · 4-token router
│   │   └── router.py
│   ├── monitor.py                #   01 · closed-loop monitor
│   ├── llm/                      #   provider-agnostic LLM client (JSON/constrained)
│   │   └── client.py
│   ├── prompts/                  #   prompt templates (text; loaded at runtime)
│   ├── labutopia/                # ★ adapter — the ONLY place that imports LabUtopia/Isaac Sim
│   │   └── adapter.py
│   ├── episode_logger.py         #   structured logs (decisions + sim-state trace)
│   └── evaluation/               #   07 · metrics + report
│       ├── metrics.py · report.py
│
├── benchmark/                    # ★ the benchmark itself (DATA, tracked in git, NOT code)
│   ├── episodes/                 #   episode JSONs by split:
│   │   ├── direct/ reference/ quantity/ composite/ ambiguous/ unsafe/ recovery/
│   ├── scenes/                   #   per-scene init/flag overrides keyed to LabUtopia usd
│   └── schema/                   #   JSON Schema files validating episodes
│
├── configs/                      # Hydra configs (LabUtopia style)
│   ├── planners/                 #   rule / llm_only / scene_grounded / saycan .yaml
│   ├── experiment/               #   figure1 / ablations .yaml
│   └── llm/                      #   model / provider configs
│
├── scripts/                      # entrypoints
│   ├── run_episode.py  run_benchmark.py  evaluate.py  make_figures.py
│
├── tests/                        # unit tests (run without Isaac Sim)
└── outputs/                      # (gitignored) logs, results, figures
```

## Two "labmate" names — don't confuse them

| path | what it is | name source |
|------|-----------|-------------|
| repo root `labmate/` | the whole **project** (code + data + docs + configs) | = GitHub repo name |
| `src/labmate/` | the importable **Python package** | = `import labmate` |

`src/` is just a container so the package is separated from docs/benchmark/configs and must be
*installed* to be used (src-layout) — this catches "works only because of the current directory" bugs.
Example: `from labmate.planner.loop import run_episode`.

## Conventions

- **Code lives in `src/labmate/`; benchmark data lives in `benchmark/`.** Never mix them. Episodes
  are JSON validated against `benchmark/schema/`.
- **`benchmark/` is tracked** (it is the deliverable). Do NOT name it `data/` — that is gitignored.
- **The simulator dependency is isolated in `src/labmate/labutopia/`.** Everything else imports
  *that adapter*, never Isaac Sim directly, so the framework (schema, planner, shield, metrics) is
  unit-testable on a plain machine without a GPU/sim.
- **Add folders on demand.** The current skeleton covers the MVP architecture; likely future
  additions (only when there is real code): `data_gen/` (episode generation), `viz/`, `backends/`
  (extra execution backends), `cli/`. Do not pre-create empty speculative folders beyond this.
- Module shadowing avoided on purpose: `episode_logger.py` (not `logging/`), `evaluation/` (not `eval/`).

## What the MVP actually fills first (per `09_roadmap.md`)

W1 touches a small subset: `schema/`, `planner/loop.py`, `affordance.py`, `parser/rule_parser.py`,
`skills/{registry,definitions}.py`, plus a handful of `benchmark/episodes/direct/*.json` and one
`configs/planners/*.yaml`. The rest of the skeleton fills in W2–W4. The empty modules already
exist so the structure is stable and each file says (in its docstring) which spec defines it.
