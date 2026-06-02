# 01 · Architecture

## Pipeline

```
typed instruction
      │
      ▼
┌─────────────┐   ┌──────────────┐   ┌─────────────────────────────┐
│  Parser     │──▶│ Scene Graph  │──▶│  Planner (4 baselines)      │
│ NL → schema │   │ from sim GT  │   │  propose skill candidates   │
└─────────────┘   └──────────────┘   └──────────────┬──────────────┘
                                                     │ candidate skill
                          ┌──────────────────────────▼─────────────┐
                          │  Decision gate (joint)                  │
                          │  • Clarification router (ASK?)          │
                          │  • Safety shield (REFUSE/STOP?)         │  ← deterministic arbiter
                          │  • Affordance check (feasible?)         │
                          └──────────────────────────┬─────────────┘
                                       ACT            │
                                                      ▼
                          ┌───────────────────────────────────────┐
                          │  Executor → LabUtopia controller       │
                          └──────────────────────────┬─────────────┘
                                                      ▼
                          ┌───────────────────────────────────────┐
                          │  Monitor (success? from sim GT)        │──┐ replan / retry
                          └──────────────────────────┬─────────────┘  │
                                                      ▼                │
                                            Logger ──▶ Evaluator       │
                                                      └────────────────┘ loop until goal / done / refuse
```

Everything is driven by **simulator ground-truth state** (no perception stack in the MVP).

## The unified planning loop

All four planner baselines are **one loop** with different switches. This keeps a single code path
and makes the ablation table fall out naturally.

```python
def run_episode(episode, planner_cfg):
    sg     = build_scene_graph(sim)              # from LabUtopia ObjectUtils (see 08)
    schema = parse(episode.instruction, sg, planner_cfg)   # NL → schema (see 02)
    goals  = predict_goal_props(schema, sg)      # symbolic goals for plan-validity (see 04)
    history = []
    for step in range(MAX_STEPS):
        # 1. PROPOSE candidate skills (LLM and/or rules) — never raw actions
        cands = planner.propose(schema, sg, history, planner_cfg)   # see 04

        # 2. DECISION GATE (joint clarification + safety + affordance) — deterministic arbiter
        decision = gate(cands, schema, sg, planner_cfg)             # see 05, 06
        if decision.kind == "ASK":
            answer = ask_user(decision.question)                   # sim oracle in MVP
            schema = resolve(schema, decision.question, answer); history.append(("ask", answer)); continue
        if decision.kind == "REFUSE":
            log("refuse", decision.reason); return result(history, refused=True)
        skill = decision.skill                                     # kind == "ACT"

        # 3. EXECUTE via LabUtopia controller
        ok = executor.run(skill, sim)                              # see 03, 08

        # 4. MONITOR + feedback
        history.append(("act", skill, ok))
        sg = build_scene_graph(sim)
        if satisfies(goals, sg): return result(history, success=True)
        if not ok: history.append(("fail", skill))                # planner may retry/replan next iter
    return result(history, success=False)
```

## Baselines = configs of the loop

| Baseline | `propose` | affordance in gate | clarification | goal-check / monitor |
|----------|-----------|--------------------|---------------|----------------------|
| `rule`            | template match | yes | rules only | yes |
| `llm_only`        | LLM scores skills | **off** | LLM may emit ASK | off (open-loop) |
| `scene_grounded`  | LLM scores skills | **on** (scene graph) | on | on |
| `saycan`          | LLM × affordance, iterative | on | on | on (replan) |

The **proposed framework** = `scene_grounded`/`saycan` + safety shield + joint router + monitor.
The other rows are the baselines it must beat (see `07_evaluation.md`).

## Modules (suggested `src/` layout)

```
src/labmate/
  parser.py          # NL → schema (02)
  scene_graph.py     # sim GT → objects + relations (02, 08)
  skills/registry.py # skill defs: preconditions/effects/success (03)
  planner/loop.py    # the unified loop above
  planner/baselines.py
  affordance.py      # deterministic precondition checker (04)
  safety/shield.py   # RoboGuard-style gate + rules (05)
  clarification/router.py  # 4-token router (06)
  executor.py        # skill → LabUtopia controller (03, 08)
  monitor.py         # success/feedback from sim GT
  logging.py         # structured episode logs
  eval/metrics.py    # all metrics (07)
configs/
  tasks/             # episode suite (02)
  planners/          # baseline configs
```

## Design invariants (do not violate)

1. **LLM proposes, deterministic gate decides.** The safety shield and affordance checker are the
   final arbiters over the action stream — never let raw LLM text execute. (RoboGuard pattern.)
2. **Planners emit skills, never low-level actions.** Output is constrained to the skill registry.
3. **Score on executed actions, not on text.** A "refusal" only counts if the unsafe action did
   not run in sim (see `07_evaluation.md`).
4. **Drive scripted LabUtopia controllers**, not learned policies, so manipulation noise does not
   mask the planning/clarification/safety contribution. Keep objects in-distribution.
5. **Per-stage attribution.** Every failure is tagged parse / grounding / clarification / safety /
   planning / execution so we know which layer to fix.
