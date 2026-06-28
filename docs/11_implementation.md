# 11 · Implementation status & code map

> **Living doc — update it as each week lands.** Docs 01–10 are the (mostly frozen) *design*; this
> file tracks what is *actually built*, how the code maps to that design, and how to run it. When you
> finish a milestone, flip its row below and adjust the code map / "simplifications" list.

## Status

| Milestone (09_roadmap)                                     | State  | Notes                                                                                                                                                                                                     |
| ---------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Environment bring-up                                       | ✅ done | mise(runtime)+uv(packages), Isaac Sim 5.1 on aarch64/GB10. See docs/08.                                                                                                                                   |
| **W1 — schema + loop (`rule`, `llm_only`)**                | ✅ done | end-to-end `pick` runs in sim; live `llm_only` verified.                                                                                                                                                  |
| **W2 — scene graph + grounding + `scene_grounded`**        | ✅ done | relations + deterministic referring-expression resolver; `scene_grounded` picks "the left bottle" end-to-end, grounding_accuracy=1.                                                                       |
| **W3 — clarification + safety + sequence exec + `saycan`** | ✅ done | real shield (5-tier/8 rules), deterministic router, goal-directed `saycan` w/ retry, sequence executor (fresh controller/skill). Sim: unsafe→REFUSE (executed=0), recovery→retry→success; 25 tests green. |
| W4 — metric aggregation + Figure 1/2                       | ⬜ next | aggregate URR/FRR/Ask/recovery/grounding over 50–100 episodes; baseline-vs-framework + ablations.                                                                                                         |
| W4 — metric suite + the two figures                        | ⬜      | full metrics over logs; 50–100 episodes; Figure 1 + Figure 2.                                                                                                                                             |

## The pipeline → code map

One instruction flows `NL → schema → propose → gate → execute → monitor → log`. Each stage is one
place in the code (design-doc reference in parentheses):

| Stage                | What it does                                                                                                | Code                                                        | Design |
| -------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------ |
| ① parse              | NL → structured `InstructionSchema`                                                                         | `parser/rule_parser.py`, `parser/llm_parser.py`             | 02     |
| — schema             | the data structures + predicate library                                                                     | `schema/{instruction,episode,predicates}.py`                | 02     |
| — scene              | objects + flags + relations (`is_in/is_on/near` + left/right); `from_specs` derives relations from poses    | `scene/scene_graph.py`                                      | 02, 08 |
| — grounding          | deterministic referring-expression resolver ("the left/empty/nearest X") + quantity                         | `scene/grounding.py`                                        | 02     |
| ② propose            | candidate `(skill, args)` — category (`llm_only`), grounded (`scene_grounded`), or goal-directed (`saycan`) | `planner/baselines.py`, `skills/registry.py`                | 04, 03 |
| — skills             | the 8 skills + preconditions/effects/success                                                                | `skills/definitions.py`                                     | 03     |
| — affordance / goals | feasibility `S_aff∈{0,1}`; goal lookahead (planner belief, decoupled from eval)                             | `affordance.py`, `planner/{scoring,goals}.py`               | 04     |
| ③ gate               | joint **ASK / REFUSE / ACT** arbiter (router → shield → clutter → affordance), per-stage attribution        | `planner/loop.py::gate_traced`                              | 04     |
| — clarify            | deterministic ACT/ASK/REFUSE router; ASK→oracle→resolve loop in `run_episode`                               | `clarification/router.py`                                   | 06     |
| — safety             | RoboGuard-style shield: 5-tier verdict + 8 rules over object/scene flags                                    | `safety/shield.py`, `safety/rules.py`                       | 05     |
| — clutter (B1a)      | path-aware geometric feasibility: ASK if an object is in the robot→target corridor (`corridor_radius`) or the grasp column is crowded (`clearance`); `clutter_check` switch, framework rows only | `planner/loop.py::gate_traced`, `scene_graph.approach_blockers` | 04, 12 |
| ④ execute            | drive a LabUtopia controller; **fresh controller per skill** (sequence/retry)                               | `skills/executor.py` (`SimBackend`), `labutopia/adapter.py` | 03, 08 |
| — runtime stop (B1b) | watch non-target object displacement per frame; **stop on disturbance** + escalate to human                 | `safety/runtime.py`, `labutopia/adapter.py::_run_skill_impl` | 12     |
| ⑤ monitor            | stop on goal lookahead; retry on failure (recovery/replan)                                                  | `monitor.py`, `planner/loop.py`                             | 01, 07 |
| — metrics            | PC + grounding-acc + URR/FRR/Ask-PR/recovery + attribution                                                  | `evaluation/metrics.py`                                     | 07     |
| — trace              | per-step candidates + `s_llm`/`s_aff`/score, grounding rule, gate-stage verdicts, exec/scene/goal; JSON + narrative + live `--verbose` | `trace.py`, `planner/loop.py::gate_traced`       | 07     |
| — log                | per-episode JSON/JSONL (+ `<id>.trace.txt` narrative)                                                       | `episode_logger.py`                                         | 01, 07 |
| loop                 | ties it all together, 4 baselines = configs                                                                 | `planner/loop.py::run_episode`                              | 01, 04 |
| LLM seam             | provider-agnostic client (Anthropic)                                                                        | `llm/client.py`                                             | 04     |

**Invariant (do not break):** the LLM only *proposes*; the deterministic `gate()` decides. Raw LLM
text never drives the robot (docs/01).

**The only module that imports Isaac Sim is `labutopia/adapter.py`** (lazy imports inside methods).
Everything else is unit-testable on a plain machine — that is why `uv run pytest` needs no GPU/key.

## Data / configs (not code)

- `benchmark/episodes/<split>/*.json` — one task each (instruction + `gold_schema` + `eval_function`).
  W1 ships `direct/pick_conical_bottle.json` (the runnable proof).
- `benchmark/scenes/<scene>.json` — maps LabUtopia USD prim paths → `{category, flags}` (grounding map).
- `benchmark/schema/episode.schema.json` — **exported** from `Episode.model_json_schema()`; validates
  every episode. Regenerate with `from labmate.schema.episode import export_schema_file`.
- `configs/planners/{rule,llm_only}.yaml` — a baseline = a set of loop switches.

## How to run

```bash
# fast logic tests — no GPU, no key
uv run pytest

# one episode end-to-end in the sim (rule baseline; no LLM key needed)
uv run python scripts/run_episode.py \
  --episode benchmark/episodes/direct/pick_conical_bottle.json \
  --planner configs/planners/rule.yaml --headless
# → outputs/labmate/<episode_id>/<episode_id>.json  (schema, decisions, success, pc, steps_trace)
#   + <episode_id>.trace.txt  (human-readable per-step narrative)

# --verbose streams the per-step reasoning (candidates, scores, gate verdicts) live;
# --debug-llm folds the raw LLM prompt/response into the trace (llm baselines).
uv run python scripts/run_episode.py --episode ... --planner configs/planners/scene_grounded.yaml \
  --headless --verbose

# llm_only (live): set ANTHROPIC_API_KEY, then
uv sync --extra llm
uv run python scripts/run_episode.py --episode ... --planner configs/planners/llm_only.yaml --headless
```

Env injection (`LD_PRELOAD`, EULA) is automatic under the user's zsh `uv run` — see docs/08.

### Interactive demo (chat → live sim)

```bash
# all demo objects co-present + visible; type instructions, the robot picks the grounded one.
# Drop --headless to watch on a VNC desktop (set DISPLAY=:42 from an SSH shell).
./scripts/labrun python scripts/interactive.py --objects benchmark/demo/chemistry_demo.json [--headless]
#   > pick the left conical bottle     -> ACT, robot picks conical_bottle02
#   > pick a conical bottle            -> ASK "which?"  (answer at the prompt) -> ACT
#   > pick the hazardous beaker        -> REFUSE [S3], nothing runs
#   > pick the left conical bottle     -> ASK (B1a) "beaker1 is on the path …"
#       ↳ remove beaker1               -> scene re-read, path clear -> ACT grasp  (HRC: clear → proceed)
#   commands: move <obj> <x> <y> | move <obj> aside | remove <obj> | reset | quit
#   flags: --no-clutter (off B1a) | --no-runtime-stop (off B1b)
```

**Multiple skills (approach B).** The adapter builds the LabUtopia task **matching each skill** on the
same live session (`_SKILL_TASK` registry + `_ensure_task`, cached): `pick` uses the scene's default
task; `open`/`close` build an `openclose` task from `level1_open_drawer` on demand (verified: a second
task on the same world/stage/robot works). `fixed: true` scene objects (furniture, e.g. the drawer
`Cabinet_01`) are excluded from the pick rebind + `show_all_objects` (kept at their USD pose, referenced
by their own skill task). LabMate's parser/grounding/goals already supported `open` end-to-end, so
`"open the drawer"` grounds + gates with no planner changes. **Caveat:** the drawer-*open* itself is not
yet clean in `lab_001` (the Cabinet asset gets yanked rather than sliding tidily → `is_success` is
borderline) — the architecture/skill-switch is proven; reliable drawer/door actuation is asset tuning
(docs/12).

**Human-robot collaboration (Path A).** When the gate ASKs (B1a clutter) or stops (B1b disturbance), the
human edits the scene — `move`/`remove` an obstacle — and re-issues (or answers the ASK inline with a
`move`/`remove`, which re-gates the same turn). `SimSession.move_object` relocates the prim **and updates
its declared pose**, so `build_scene_graph` re-grounds against the new layout. (Mouse-drag manipulation in
the viewport is Path B — needs a background render thread + live-pose reading; deferred, docs/12.)

`scripts/interactive.py` (REPL) + `src/labmate/interactive.py` (`run_turn`, reuses the loop's
`gate_traced`/`_propose`/`resolve_with_answer` + the trace). The sim is brought up **once** and stays
persistent; `SimSession(multi_visible=True)` keeps **all** configured objects placed + visible
(`show_all_objects()` re-applied after each `task.reset()`, since LabUtopia hides every object but
`current_obj_idx`). **Robot motion is `pick`-only** — `place`/`pour`/`clean` are LabUtopia composite
controllers needing their own task (DualObjectTask/CleanBeakerTask); other intents show the decision +
trace but don't drive the robot. Blocking REPL (no live-render thread yet).

## Key implementation decisions

- **Schemas = pydantic v2** (not dataclasses); JSON Schema is exported from the models (docs/02 note).
- **`Skill` is a plain dataclass** — it holds callables (preconditions/effects/success), not data.
- **`rule` baseline drives the W1 end-to-end run** (no LLM key). `llm_only` is wired + mock-tested;
  the Anthropic SDK is an **optional, lazy-imported** dep (`uv sync --extra llm`).
- **Two backends** implement one `Backend` protocol: `SymbolicBackend` (no sim, for tests/dry-runs,
  applies skill effects) and `SimBackend` (real sim via the adapter).

## W1 simplifications to revisit

- **`is_held` is derived from the pick controller's success** (object lifted ≥0.1 m) because LabUtopia
  exposes no gripper-held flag → W2: a geometric held-check.
- **Grounding (W2 done):** deterministic resolver handles left/right/nearest/attribute/relational refs;
  the grounding scene graph is built from the episode's `init_overrides` (declared poses+flags = sim GT)
  and the executor rebinds `cfg.task.obj_paths` + `current_obj_idx` to pick the resolved object.
  Caveats: **left/right axis assumes robot +Y = left** (`adapter.LEFT_SIGN`) — self-consistent with
  declared poses; confirm against visual left/right if it matters. `quantity` is resolved + count-eval'd
  but multi-pick execution is deferred to the W3 sequence executor.
- **Clarification + safety (W3 done):** real deterministic router (ACT/ASK/REFUSE + oracle loop) and
  RoboGuard shield (5-tier, 8 rules). Both decide from schema+scene only (never gold fields).
- **Sequence executor (W3 done):** `run_skill` now creates a **fresh controller per skill** (mock
  collector, terminate on `done`), fixing the one-skill-per-process limit; multiple real skills /
  retries work in one process (recovery verified in sim).

## W3 simplifications to revisit (W4+)

- **Recovery uses an induced-failure flag** (episode marks the first execute to fail) — a deterministic
  stand-in for physical failure; the recover *loop* (saycan goal-directed retry) is the real thing.
- **Sim sequence depth:** **two real controllers in one process is now verified** (audit fix —
  LabUtopia's `eval` resolver was re-registered without `replace=True`, crashing the 2nd controller;
  the adapter now patches `OmegaConf.register_new_resolver` to be idempotent). `run_skill` also has a
  hard frame cap (never hangs) and no longer calls `on_task_complete` (which drifted `current_obj_idx`).
  A full *task-level* multi-skill sim sequence (e.g. pick→place via a place task / LabUtopia composites)
  is still a W4 item, but the per-process limit that blocked it is gone.
- **Baseline configs for Figure 1:** `rule`/`llm_only` should run with the framework components OFF to
  make the contrast fair (the framework = `scene_grounded`/`saycan` with router+shield ON). The
  config toggles + the aggregation runner + plots are W4.
- **`quantity`** is grounding + count-eval only; multi-object delivery execution is W4.

## Gotchas

- **`SimulationApp.close()` hard-exits the process** (fastShutdown). Do all logging/printing BEFORE
  closing the session, or it silently never runs (`scripts/run_episode.py`).
