# 08 · LabUtopia integration

LabUtopia is the execution base (cloned into `src/labutopia/`, gitignored — not vendored).
Reuse it; do not reimplement manipulation. This doc lists concrete hooks and the build gaps.
Paths below are inside the LabUtopia repo (i.e. under `src/labutopia/`).

## What LabUtopia already provides (reuse)

| Need | Hook | Path |
|------|------|------|
| Instantiate task/controller | `TaskFactory.create_task(...)`, `ControllerFactory.create_controller(...)` | `factories/` |
| Skills (19 controllers) | `pick place open close pour press shake stir device_operate` + composites `pickpour pickplace cleanbeaker …` + `navigation mobile_pick` | `factories/controller_factory.py`, `controllers/` |
| Run a step | `state = task.step(); action, done, success = controller.step(state); robot.apply_action(action)` | `main.py` (~L79–161) |
| Object registry / grounding | `ObjectUtils.get_instance(stage)` → `get_geometry_center`, `get_object_size`, `get_pick_position`, `get_transform_quat`, `set_object_position` | `utils/object_utils.py` |
| Object metadata in state | `state['object_position'|'object_size'|'object_path'|'object_name'|'target_position'|...]` | `tasks/base_task.py` (~L286) |
| Language field | `BaseController.language_instruction` (exists, **unused** for skill selection) | `controllers/base_controller.py` |
| Remote policy hook | `RemoteInferenceEngine` sends obs+language → joint trajectory (OpenPI) | `controllers/inference_engines/remote_inference_engine.py` |
| Success checking | per-controller `_check_success()`; 2-second stability rule | `controllers/*`; LabUtopia paper Appx C |
| Episode logging | HDF5 + `episode.jsonl` (success/length/task_type) | `data_collectors/data_collector.py` |
| Config system | Hydra YAML: `task_type, controller_type, usd_path, max_episodes, task.obj_paths, robot` | `config/level{1-4}_*.yaml` |

## Build the scene graph from sim GT

LabMate's `scene_graph.py` wraps `ObjectUtils` + task state into the structure `02_schema.md`
expects: enumerate objects → `{name, category, usd_path, pose, size}` + the **object state flags**
(`is_hot, liquid_id, is_fragile, is_hazardous, cap_state, device_state, is_sample, …`) and simple
relations (`is_in, is_on, near`) computed from poses/containment. Flags are set via `init_overrides`
in the episode (02) and read back from sim — no perception needed.

## Gaps to build (LabMate's own code)

1. **NL → skill binding** — LabUtopia has no parser; `language_instruction` is not wired to skill
   selection. Build `parser.py` + the planner that emits a **controller sequence** (not 1 fixed task).
2. **Semantic grounding** — `ObjectUtils` gives geometry by USD path, **no categories/relations**.
   Add category labels + relations in `scene_graph.py` (annotate in config or a small map).
3. **Object state flags** — add the safety-relevant flags to objects (config-set), readable from state.
4. **Sequence executor** — drive a *sequence* of controllers with clean hand-offs (LabUtopia runs one
   controller per config); add `executor.py` (03).
5. **Offline evaluator** — LabUtopia checks success live per controller; add the metric layer (07)
   over structured logs.

## Execution guidance (feasibility-critical)

- **Drive scripted FSM controllers**, not learned policies. LabUtopia reports learned-policy success
  collapsing on long-horizon (Level-4 last sub-step ~0–1.6%) and ~0% on OOD object shapes. The
  scripted controllers (used to generate demos) are the reliable path.
- **Keep objects in-distribution** for the MVP.
- **Score per sub-step / per decision** so a dropped beaker doesn't penalize a correct planner.
- Robots available: Franka Panda (fixed), Fetch/Ridgeback+Panda (mobile, for navigate/mobile_pick).

## Env / runtime

**Split ownership: `mise` manages the runtime, `uv` manages packages.** A single project-local `.venv`
holds Isaac Sim + LabUtopia + LabMate; `uv.lock` pins packages; `mise.toml` pins the interpreter. No
conda, no manual `source`. Default shell is **zsh**.

- `./mise.toml` → `[tools] python = "3.11"`. mise installs a cpython-standalone 3.11 (ABI-identical to
  the builds uv uses, so isaacsim's cp311 wheels are fine) and exposes it on PATH. This overrides the
  global mise config's `python = "3.13"` only inside this project.
- `[tool.uv]` `python-preference = "only-system"` + `python-downloads = "never"` make uv build the
  `.venv` from **mise's** python and never fetch its own. (There is no `.python-version`; mise.toml is
  the single runtime source.)

> **This machine is aarch64 (NVIDIA GB10 / DGX Spark), CUDA 13.** LabUtopia's README targets x86 +
> CUDA 12.6; the *actual* working build here is **torch `2.9.0+cu130`** (not cu126). All versions below
> reproduce the known-good ARM venv (isaacsim `5.1.0.0`, numpy `1.26.0`).

Other key `pyproject.toml` wiring:
- `requires-python = ">=3.11,<3.12"` — Isaac Sim 5.1 ships cp311 wheels only.
- `[[tool.uv.index]]` **pytorch-cu130** (`download.pytorch.org/whl/cu130`, `explicit`) bound to the
  torch trio via `[tool.uv.sources]`; **nvidia** (`pypi.nvidia.com`) for isaacsim + its sub-pkgs.
- `index-strategy = "unsafe-best-match"` (mirror pip's `--extra-index-url`) and
  `environments = ["sys_platform == 'linux' and platform_machine == 'aarch64'"]`.
- `override-dependencies = ["torch==2.9.0", "torchvision==0.24.0", "torchaudio==2.9.0"]` — Isaac Sim
  5.1 conservatively pins torch 2.7 / torchvision 0.22; we force the newer cu130 trio past it (runs
  fine at runtime, as the original venv proved).

```bash
mise install            # ensure the project's python 3.11 is present (reads ./mise.toml)
uv sync                 # build the .venv from mise's python (wheels come from uv cache)
uv run python ...       # just works in zsh — see env injection below
```

**Isaac Sim runtime env (required on this box).** mise here runs in **shims mode** (`mise activate
--shims`), which does *not* support mise `[env]` auto-vars, so the two Isaac Sim env bits are injected
another way:
- `LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1` — **required**; without it isaacsim aborts at
  import ("shared libraries must be loaded before others").
- `OMNI_KIT_ACCEPT_EULA=YES` — accept the Omniverse EULA non-interactively (first kit bootstrap
  otherwise blocks on a Yes/No prompt and dies on EOF).

These live in the gitignored repo-root `.env`. A `uv()` wrapper in `~/.config/zsh/90-local.zsh` makes
plain **`uv run`** auto-load that `.env` (it walks up from cwd, sets `UV_ENV_FILE`) — so inside the repo
(and `src/labutopia/`) `uv run …` injects them with zero ceremony, and other projects are unaffected.
`scripts/labrun` is the tracked, shell-independent fallback (cron / non-interactive: it exports both
vars then calls `uv run`).

**LabUtopia placement:** cloned into `src/labutopia/` (gitignored — *not* vendored/forked) and put on
`sys.path` via `.venv/.../site-packages/_labutopia_path.pth`. It is a PYTHONPATH-style repo (no
packaging metadata; top-level `controllers/ factories/ tasks/ utils/ robots/ policy/`, entry
`main.py`). The `labutopia/adapter.py` boundary must **lazy-import** Isaac Sim/LabUtopia (inside
functions) so `import labmate` and unit tests still work if the sim isn't present. The optional remote
VLA client lives at `src/labutopia/packages/openpi-client` (its own pyproject; install on demand).

> If the `.venv` is ever rebuilt (`rm -rf .venv && uv sync`), recreate `_labutopia_path.pth`
> (one line: the absolute path to `src/labutopia`).
