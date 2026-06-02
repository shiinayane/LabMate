# LabMate

**LabMate: A Clarification- and Safety-Aware Benchmark for Human-Robot Collaboration in Scientific Laboratories.**

This repository holds the documentation and (later) the implementation of LabMate.
For now it contains only `docs/` — the design reference used when writing the code
on the remote development server. Source code, configs, and experiments will be added
alongside this folder over time.

> This `docs/` set is **self-contained and implementation-facing** (English). It is the
> canonical reference for anyone (human or coding agent) writing LabMate code remotely.

---

## What LabMate is

LabMate is built on top of **LabUtopia** (NeurIPS 2025), a high-fidelity Isaac Sim
laboratory simulator with hierarchical embodied tasks. LabMate extends it from
"execute a predefined task config" to "go from a natural-language human instruction →
object grounding → safety/clarification decision → skill execution → monitoring/recovery",
and turns that loop into a **reproducible benchmark + execution framework**.

It is **not** a new simulator, an autonomous scientist, or an end-to-end VLA robot.

**LabMate is a benchmark _and_ a proposed framework that wins on it.** The paper arc is:
(1) the problem needs clarification + safety + execution jointly; (2) naive LLM-only / end-to-end
VLA baselines fail on it in measurable ways; (3) we propose the LabMate framework — structured
schema + scene-graph grounding + deterministic affordance + a safety shield + a joint
ambiguity-and-safety decision router + closed-loop monitoring; (4) it significantly beats the
baselines; (5) ablations show each component matters. The two headline results are: **framework
vs LLM-only vs VLA** (we win on clarification / safety / success) and **ablations**
(open-loop vs closed-loop, with/without shield, with/without grounding).

## The problem

A researcher gives an instruction such as *"clean the beaker on the left"* or
*"bring two test tubes"*. The robot must decide:

- which object is referred to (object / reference),
- how many (quantity),
- whether the action is safe (safety),
- whether information is missing and clarification is needed (ambiguity),
- whether execution succeeded (outcome).

Existing lab-robot benchmarks assume predefined tasks and cannot jointly evaluate
**clarification, safe refusal, execution monitoring, and failure recovery**. LabMate
measures this full loop reproducibly.

## System overview (what to implement)

A 4-stage pipeline, each stage independently evaluable so failures can be attributed:

1. **Task suite** — a compact set of tasks on LabUtopia covering: direct commands,
   object-reference commands, quantity commands, composite assistance (cleanup, bench prep),
   ambiguous instructions, unsafe/inappropriate instructions, simple failure-recovery.

2. **Interaction schema** — map each instruction to a structured record:
   `intent / object_category / quantity / destination / missing_slots / safety_flag / expected_skill_sequence`.
   Grounding data is derived from LabUtopia scene info and object labels.

3. **Planner baselines** (increasing capability):
   - rule / template planner
   - LLM-only planner
   - scene-grounded LLM planner (consumes a scene graph)
   - SayCan-style planner (language usefulness × skill affordance × safety constraint)

4. **Execution + logging** — connect validated skill sequences to LabUtopia controllers
   or a trained policy backend; record structured execution logs.

### Skill registry / DSL

Wrap existing controllers as skills with declared preconditions, success conditions,
failure reasons, and confirmation requirements:
`pick / place / open / close / pour / clean / navigate / mobile_pick`.
AI output is constrained by schema + scene graph + skill registry + safety rules and
treated as a **verifiable plan**, never free-form low-level actions.

### Safety scope (do not over-claim)

Model only **executable, simulation-evaluable** safety constraints (not real wet-lab safety):
unknown liquid → confirm; hot object → no direct grasp; hazardous/unsupported → refuse;
fragile glassware → careful handling; device op → state preconditions; no discarding samples
without confirmation. Novelty = linking safety decisions to embodied action, preconditions,
logs, and metrics.

## Evaluation metrics

Measured separately to localize failure (language vs grounding vs safety vs planning vs control):
language parsing · object grounding accuracy · plan validity · clarification precision/recall ·
unsafe-action rejection · false refusal rate · skill execution success · recovery rate · task success.

## Milestones

- **3-month prototype**: typed instructions, object aliasing, scene grounding, skill registry,
  ≥3 planner baselines, an evaluator, 50–100 simulated episodes. Key result: how much scene
  grounding + clarification improve over an LLM-only baseline.
- **6-month**: expand to several hundred episodes with ambiguous / unsafe / recovery splits,
  multi-baseline comparison. Deliverables: task + annotation schema, baseline scripts,
  structured execution logs, the full metric suite, and a technical report / workshop draft.

## Known engineering notes (from running LabUtopia)

- RMPFlow-style low-level manipulation is unreliable in practice; a replacement policy
  backend is needed so low-level failure does not mask the high-level HRC contribution.
- VLA backends (OpenVLA / Octo / pi0) are an **optional** atomic-skill baseline, not core;
  keep the remote-inference hook but defer until the HRC protocol is stable.

## Planned repo layout (as code is added)

```
LabMate/
├── docs/        # this folder — design reference (current)
├── src/         # LabMate framework: parser, scene graph, skill registry, planners, evaluator (planned)
├── configs/     # task suite + annotation schema (planned)
└── ...          # logs, scripts, experiments (planned)
```

## Documents in this folder (read in order)

| Doc | Contents |
|-----|----------|
| `README.md` | This overview — start here. |
| `01_architecture.md` | System pipeline, the unified planning loop, how the 4 baselines are configs of one loop, module boundaries, data flow. |
| `02_schema.md` | Data structures: instruction schema, episode/annotation schema, eval-function (propositions/constraints), ambiguity types. |
| `03_skills.md` | Skill registry / DSL: the 8 skills with preconditions, effects, success conditions; mapping to LabUtopia controllers. |
| `04_planners.md` | The 4 planner baselines (rule, LLM-only, scene-grounded, SayCan-style) as one loop; scoring; deterministic affordance. |
| `05_safety.md` | Safety component: RoboGuard-style shield, 4-tier decisions, executable rules grounded in sim object flags. |
| `06_clarification.md` | Clarification component: 4-token router, ambiguity taxonomy, when-to-ask; joint with safety. |
| `07_evaluation.md` | Metric definitions and how each is computed; the two headline experiments. |
| `08_labutopia_integration.md` | What LabUtopia already provides vs what to build; concrete hooks (controllers, ObjectUtils, factories, language field). |
| `09_roadmap.md` | The MVP build plan (weeks), deliverables, scope guardrails. |
| `references.md` | Pointers to prior work (arXiv links; no PDFs). |

> These specs are derived from the research notes (kept locally outside this repo) and are the
> canonical source for implementation. If code and spec disagree, fix one deliberately.
