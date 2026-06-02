# 08 · LabUtopia integration

LabUtopia is the execution base (cloned separately; in the workspace at `../Sources/LabUtopia`).
Reuse it; do not reimplement manipulation. This doc lists concrete hooks and the build gaps.
Paths below are inside the LabUtopia repo.

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

**One environment, managed by `uv` (no conda).** A single project-local uv venv holds Isaac Sim +
LabUtopia + LabMate. Use `uv run …` so no manual `source` is ever needed.

```bash
uv python pin 3.11 && uv venv
# sim stack per LabUtopia README (CUDA 12.6 / Isaac Sim 5.1):
uv pip install torch==2.9.0 torchvision==0.24.0 torchaudio==2.9.0 --index-url https://download.pytorch.org/whl/cu126
uv pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
uv pip install -r ../Sources/LabUtopia/requirements.txt
uv pip install -e ".[dev]"        # LabMate, editable
uv run python scripts/run_episode.py ...   # no source needed
```

- **LabUtopia is a separate sibling git repo** (`../Sources/LabUtopia`, cloned independently). LabMate
  does not fork or vendor it; import it via editable install or `PYTHONPATH`.
- The `labutopia/adapter.py` boundary must **lazy-import** Isaac Sim/LabUtopia (inside functions) so
  `import labmate` and unit tests still work if the sim isn't present.
- LabMate adds minimal deps (jsonschema + LLM SDK; reuse the venv's numpy/hydra) to avoid conflicts.

> Detailed env bring-up is left to the implementer; the above is the intended shape.
