# 12 · Improvement backlog

> Living list of improvements **outside the current MVP scope** or surfaced during development. Not
> commitments; a place to capture "we should do this" so it isn't lost. Promote items into a weekly
> plan when picked up. (Design lives in 01–10; status/code-map in 11.)

## High-value

### B1 · Failure-aware feasibility & escalation (the framework's core pattern: clarify/escalate, don't blunder on)

**Observed (2026-06):** in the interactive demo, `pick the left beaker` *executed* (the RMPFlow
obstacle-avoidance arm motion ran) but **did not grasp** (`is_success=False`); the demo reported
`executed=1 ok=False` and moved on with no recourse. Separately, a full-gripper pick yields a bare
`no_feasible_skill` token.

**Key realisation (the hard part).** The deterministic `s_aff` checks only **symbolic** preconditions
(gripper empty, graspable) — it **does not see the motion path**. RMPFlow is a *reactive* policy (local
obstacle avoidance, no global plan): for a target the gate has *approved* (`s_aff=1`), nearby objects
can still make it weave, stall in a local minimum, or throw a dangerous avoidance motion. So the danger
arises **during motion, on gate-approved actions** — a layer between the symbolic gate and the motor
controller that the framework does not model. (docs/04 designed `s_aff` as a *geometric*-feasibility
term à la Text2Motion; the implementation reduced it to symbolic preconditions.) Predicting RMPFlow
behaviour ≈ running a motion planner — genuinely hard. Three layers, escalating cost:

- **B1a · Conservative, path-aware clutter gate (DONE, 2026-06).** Don't predict success; be
  *conservative* and check the **approach path**, not just the target's neighbours. The gate **ASKs**
  (attribution `feasibility`) when either: an object lies in the straight corridor `robot → target`
  within `cfg.corridor_radius` (`SceneGraph.approach_blockers`), or the grasp column is crowded
  (nearest neighbour < `cfg.clearance`, `nearest_other`/`clearance`). Config switch `clutter_check` (ON
  for `scene_grounded`/`saycan`, OFF for the weak baselines), default OFF. The corridor check was added
  after the nearest-neighbour-only version passed `pick the left beaker` (neighbour 12.8 cm) yet the arm
  hit `conical_bottle02` 7.4 cm off the approach line — now correctly ASKed. Over-refuses by design (a
  clarification, not a guarantee). The REPL also surfaces `no_feasible_skill` as the unmet preconditions.
  **Refinements still open:** size-aware radius (gripper width + object radii vs centre distance);
  live end-effector start instead of the robot base; 3-D / true swept-volume. The real safety floor is
  still **B1b** runtime stop (no pre-flight check is complete against a reactive controller).
- **B1b · Runtime disturbance monitor (DONE v1, 2026-06).** The real safety floor: watch the sim
  *during* execution and **stop the moment a non-target object is disturbed**, then hand to the human.
  `safety/runtime.py::DisturbanceMonitor` (pure) is fed each object's `get_geometry_center` per frame by
  `adapter._run_skill_impl`; it baselines **after a settle delay** (`settle_frames`, the pre-settle drop
  is jitter, not contact) and trips when a non-target moves past `disturb_threshold` (default **0.05 m**,
  excluding the grasp target). On a hit, `run_skill` stops and records `_last_stop`; `SimBackend.execute`
  surfaces it as `last_outcome`; `interactive.run_turn` ends the turn with `stopped` + a readable reason
  ("bumped X"). **Threshold = 0.05 m (tuned 2026-06):** distinguishes a **real knock** (the flail demo
  flings its neighbour >>5 cm) from **incidental jiggle** (a far object brushed ~2 cm during a big arm
  motion — e.g. the arm swinging to open the drawer nudged a bottle 2 cm, which at the old 0.02 m
  **false-stopped the `open`**; 0.05 fixes that and a clean pick still disturbs 0 cm). Switch: `SimSession(
  monitor_disturbance=...)`, on by default for the demo (`--no-runtime-stop` to disable). Reactive —
  bounds damage, not zero-contact (that's why **B1a** stays as the preventive layer). **Deferred:** finger
  contact-sensor signal (catch contact *before* the object moves); joint-effort/EE-velocity (saturate —
  weak); a formal ASK-loop on stop; benchmark-fairness wiring (runtime-stop ON only for framework rows).
- **B1c · Geometric/motion-feasibility prediction (research, defer).** Actually validate a
  collision-free trajectory (plan with cuMotion/Lula, or sandbox-roll-out RMPFlow) before committing,
  feeding a true geometric term into `s_aff`. RMPFlow being reactive (no trajectory to validate) is the
  hard bit.

**Pragmatic safety stance:** full pre-flight prediction is out of reach (= motion planning); the real
strategy is **B1a (refuse risky/cluttered grasps) + B1b (stop fast when it goes wrong)**, B1c as
research. The demo currently dodges this purely at the **data level** (objects spaced apart) — a
limitation to state honestly.

## Interactive demo limitations (current cut)

- **B2 · More skills via approach B (open DONE, 2026-06).** The adapter builds the matching LabUtopia
  task **per skill** on one live session (`adapter._SKILL_TASK` + `_ensure_task`, cached), so a single
  session *can* do `pick` AND `open` — both run, task-switch is clean, pick still grasps after an open.
  `open` is wired end-to-end (parser/grounding/goals already supported it). **Scene split (2026-06):**
  the demo now ships **one scene per skill family** rather than one unified scene, because `pick` and
  `open` are *different* LabUtopia tasks and an object from a not-yet-built task is hidden — so in the
  unified scene the drawer *popped in* mid-session on the first `open`. The pick scene
  (`--scene chemistry_lab_multi --objects chemistry_demo.json`) is bottles+beakers only; the open scene
  (`--scene chemistry_drawer --objects chemistry_drawer.json`) makes `openclose` the **default** task so
  `Cabinet_01` is native and co-present from frame 0. The adapter pins a `fixed` furniture object's
  `obj_paths` range to its declared pose and, when fixed furniture is present, does a startup
  `task.reset()` so the drawer renders from frame 0 (pick scene path unchanged — guarded on fixed
  furniture). The unified single-session path still works (approach B is unchanged); the split is purely
  a cleaner demo narrative. **Polish (corrected):** the
  drawer-open is NOT an asset bug — **native LabUtopia (`main.py --config-name level1_open_drawer`)
  opens it perfectly**, and our isolated `run_skill('open')` succeeds. The earlier "12 m yank" was a
  `get_geometry_center` measurement artifact, and the demo's `ok=False` was the **B1b monitor
  false-stopping** the open (the arm swinging to the far cabinet brushed a bottle ~2 cm > the old 2 cm
  threshold). Fixed by raising `disturb_threshold` to 0.05 m (see B1b). **Remaining wart:** the open
  controller's own `is_success` is flaky (sometimes reports False even when the drawer opens) — same
  class as pick's borderline success; a sim-GT verification (B5) would fix the *reporting* but the
  drawer's bbox center is unreliable, so deferred. The robot physically opens the drawer. **`close`** is
  a trivial follow-up (same `openclose` task). **`place`/`pour`/`clean`** remain composite tasks
  (DualObjectTask/PickPourTask/CleanBeakerTask) — addable via the same B pattern + per-object tuning.
  Until `place` lands, the gripper-full case still needs `reset`.
- **HRC scene editing — Path A (DONE, 2026-06).** When the robot ASKs/stops, the human clears the
  obstacle: REPL `move <obj> <x> <y>` / `move <obj> aside` / `remove <obj>` (`adapter.move_object`/
  `remove_object`) relocate the prim AND update its declared pose, so `build_scene_graph` re-grounds
  against the new layout. Answering an ASK inline with a `move`/`remove` re-gates the same turn
  (`interactive.RETRY`). Verified: `pick the left beaker` → ASK → `move conical_bottle02 aside` →
  `path_blockers` flips to `[]` → ACT. **Path B (deferred):** mouse-drag in the Kit viewport — needs
  the **B3** background render thread (live, interactive window) + `build_scene_graph` switched to live
  `get_geometry_center` poses.
- **B3 · Blocking REPL.** The viewport is static while you type (live only during robot motion). A
  background-input thread + a main-thread render loop would keep the window always live (the sim API
  must stay on the main thread). Prerequisite for HRC Path B (mouse manipulation).
- **B4 · `reset` is symbolic + re-home.** It clears the tracked `held` and re-shows objects; it does
  not model physically placing the held object down.

## Deferred audit hardening (P2/P3 from the 2026-06 review)

- **B5 · Geometric/closed-loop held-check.** `is_held` is asserted symbolically from the controller's
  success, not measured from sim GT — so "the gripper holds the *left* prim, not the right" is never
  physically verified (only one object was co-present pre-demo; now they are co-present, so this is
  newly checkable). Also underlies B1's grasp verification.
- **B6 · `chosen`-flag string match after the affordance refilter** (`loop.gate_traced`) — track the
  winner by identity through the refilter so duplicate `as_text()` candidates can't both be `chosen`.
- **B7 · `discard_sample` safety rule references a non-existent `discard` skill** — it is currently
  dormant (never fires). Add the skill or remove the rule.
- **B8 · `build_scene_graph` live-pose fallback** can read a teleported (10 m) pose for an object that
  lacks a declared pose; prefer declared poses / skip non-current objects.
- **B9 · Bare `except Exception: pass`** in the adapter swallows real errors — log before the
  hard-exit close.
- **B10 · Test-coverage gaps.** Safety-rule *precedence* (two flags at once), the untested rules
  (`hot_target`/`open_cap_move`), `ask_precision_recall`/`attribution_distribution`, the
  `max_steps`-exhaustion terminal path, and non-`pick` intents end-to-end.

## Scope items already on the roadmap (09)

- **B11 · W4 — decision-level metrics MVP (DONE, 2026-06).** `scripts/run_benchmark.py` runs the whole
  episode suite × planner configs **sim-free** (`SymbolicBackend`, no Isaac — the paper's headline
  metrics are decision-level and don't need physical grasping), `scripts/evaluate.py` aggregates the
  `results.jsonl` into `outputs/eval/metrics.{md,csv}` via the existing `evaluation/metrics.py`. Suite is
  ~32 episodes (`benchmark/episodes/generate_suite.py`, ~5–6/category) across direct/reference/ambiguous/
  unsafe/recovery/quantity. The contrast is clean: `llm_only` (the faithful weak baseline) scores **0.00
  ask-recall, 0.00 unsafe-rejection, 0.82 grounding** vs **1.00 / 1.00 / 1.00** for `scene_grounded`/
  `saycan`. Two supporting fixes: the clarification router is now quantity-aware (a "bring two X" plural
  request is not treated as ambiguity), and `SymbolicBackend` honours `induce_failure` so the recovery
  split works sim-free. `llm_only` needs `ANTHROPIC_API_KEY` (`--with-llm`, loaded from `.env`); the 3
  key-free baselines run without it. **Still deferred:** `make_figures.py` (Figure 1/2), physical
  execution success-rate via real sim (needs Isaac + per-episode subprocess; grasp is flaky), `composite`
  multi-step episodes (single-intent parser), scale to 50–100, AmbiK paired AmbDif metric.
- **B12 · Multi-object `quantity` execution** (bring N) — grounding + `count_ge` eval exist; physical
  multi-pick delivery needs `place` (B2).
