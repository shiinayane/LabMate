# 09 · Roadmap (MVP)

Goal: a working `NL → schema → planner → execute → evaluate` loop on LabUtopia, 50–100 episodes,
producing the two headline figures (07). Sim-only. The framework is built incrementally; the
baselines it must beat come for free as configs of the same loop.

## Week 1 — schema + loop skeleton
- Implement the data structures in `02_schema.md` (instruction schema, episode schema, predicates).
- Implement the unified loop (`01`) with two baselines: `rule` and `llm_only`.
- Affordance = deterministic precondition checker (`04`).
- Author ~10 seed episodes (direct / reference / quantity) with gold schemas + eval functions.
- **Exit**: an instruction runs end-to-end on 1–2 LabUtopia scenes; logs written.

## Week 2 — grounding + scene graph
- `scene_graph.py` over `ObjectUtils`: categories, flags, relations (`08`).
- `parse_obj`-style referring-expression resolution (`02`/Code-as-Policies).
- Wire the `scene_grounded` baseline (affordance ON, grounding ON).
- **Exit**: object grounding accuracy measurable; reference/quantity episodes work.

## Week 3 — clarification + safety + sequence execution
- 4-token clarification router (`06`); safety shield + rules (`05`); exec sandbox.
- `saycan` baseline: iterative propose + goal lookahead + monitor/replan (`04`).
- Sequence executor with clean controller hand-offs (`03`/`08`).
- Add `ambiguous`, `unsafe`, `recovery` episodes.
- **Exit**: ASK / REFUSE / recovery paths fire and are logged with per-stage attribution.

## Week 4 — evaluator + experiments
- Metric layer (`07`) over logs; offline.
- Scale episodes to 50–100: ~40% safe (false-refusal probes), ~60% unsafe/ambiguous.
- Run all 4 baselines → **Figure 1** (framework vs baselines).
- Run ablations → **Figure 2** (open/closed-loop, ±shield, ±grounding, ±clarification).
- **Exit**: both figures + a failure taxonomy + reproducible logs.

## Scope guardrails (NOT in the MVP)
Speech input · real robot · VLA fine-tuning (keep the remote hook only) · full chemistry safety
(GHS/OSHA/reaction) · OOD object-shape generalization · perception-from-pixels (use sim GT).

## Definition of done (MVP)
- One loop, 4 baselines, 50–100 episodes, all metrics in `07`, the two figures, per-stage failure
  taxonomy, structured logs. Shows: (a) lab HRC needs clarification+safety+grounding; (b) LLM-only
  fails measurably; (c) the LabMate framework fixes it, with each component contributing.

## After the MVP (6-month)
Scale to several hundred episodes; richer splits; optional VLA atomic-skill baseline; tech report /
workshop draft. Watch competitor LABSHIELD v2 (see local research notes).
