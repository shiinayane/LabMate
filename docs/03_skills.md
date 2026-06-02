# 03 · Skill registry / DSL

Planners may only emit **skills** from this registry — never raw robot actions. Each skill is a
thin wrapper over an existing LabUtopia controller (see `08_labutopia_integration.md`) plus a
declarative contract used by the affordance checker (04) and safety shield (05).

## Skill contract

```python
@dataclass
class Skill:
    name: str
    args_spec: dict                  # arg name -> type/category
    preconditions: list[Predicate]   # must hold in scene graph before run (affordance)
    effects: list[Predicate]         # symbolic effect applied to scene graph after success
    success: Callable[[SceneGraph], bool]   # checked from sim GT after execution
    needs_confirmation: Callable[[Schema, SceneGraph], bool]  # e.g. discard a sample
    controller: str                  # LabUtopia controller_factory name (08)
    failure_reasons: list[str]       # enumerated, for logging/attribution
```

`precondition(skill, args, sg)` is the **affordance** signal (04): returns 1.0 if all
preconditions hold else 0.0. `effects` give a cheap symbolic transition for goal lookahead.

## The 8 MVP skills

| skill | args | preconditions | effects | LabUtopia controller |
|-------|------|---------------|---------|----------------------|
| `pick(target)` | target obj | `is_graspable(target)`, gripper empty | `is_held(target)` | `pick` |
| `place(target, dest)` | obj, location | `is_held(target)`, dest reachable | `is_on/in(target,dest)`, gripper empty | `place` / `pickplace` |
| `open(container)` | drawer/door | container closed & reachable | `is_open(container)` | `open` |
| `close(container)` | drawer/door | container open | `¬is_open(container)` | `close` |
| `pour(src, dst)` | source, target | `is_held(src)`, `is_filled(src)`, dst present | `is_filled(dst)`, `is_empty(src)` | `pour` / `pickpour` |
| `clean(target)` | obj | target present, wash_station present | `is_clean(target)` | `cleanbeaker` (composite) |
| `navigate(location)` | location | mobile robot, path exists | robot near location | `navigation` |
| `mobile_pick(target)` | obj | mobile robot, target graspable | `is_held(target)` | `mobile_pick` |

Composite intents (`bring(qty, category)`, "tidy the bench") are **decomposed by the planner**
into the above primitives; they are not new controllers.

## Confirmation-required cases (`needs_confirmation`)

Return True (→ route to ASK/CONFIRM before executing) when, e.g.:
- `discard`/dispose of an object where `is_sample(target)`,
- `pour` where `liquid_id(src) == unknown`,
- any skill on `is_hazardous(target)` lacking an explicit safe handling path.

These hook into the safety shield (05) and clarification router (06).

## Executor contract

```python
def run(skill, sim) -> bool:
    ctrl = controller_factory.create(skill.controller, cfg, robot)
    bind_targets(ctrl, skill.args, ObjectUtils)   # resolve category/ref → USD path (08)
    loop: state = task.step(); action, done, ok = ctrl.step(state); robot.apply(action)
    return ok and skill.success(build_scene_graph(sim))
```

Use the **scripted FSM controllers** (reliable path). Record `failure_reasons` on `not ok` for
per-stage attribution (07). Bound each skill by a step budget; on timeout return failure.

## Notes

- `clean` is already a Level-4 composite in LabUtopia (Pick-Pour-Place-Shake-…). Reuse it.
- Skill ↔ controller binding indirection lets us later swap a controller for a learned policy
  backend without changing planners.
- Keep `args` referring to **categories/refs**; grounding (02/08) resolves them to USD paths at
  execution bind time, so plans stay scene-independent and inspectable.
