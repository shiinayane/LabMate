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
  is jitter, not contact) and trips when a non-target moves past `disturb_threshold` (default 0.03 m,
  excluding the grasp target). On a hit, `run_skill` stops and records `_last_stop`; `SimBackend.execute`
  surfaces it as `last_outcome`; `interactive.run_turn` ends the turn with `stopped` + a readable reason
  ("bumped X"). **Verified in sim:** a clean isolated pick disturbs 0.0 cm (no false stop); the cramped
  `beaker1` pick halts the instant `conical_bottle02` crosses 3 cm. Switch: `SimSession(
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

- **B2 · `pick`-only robot motion.** `place`/`pour`/`clean` are LabUtopia *composite* controllers
  needing their own task (DualObjectTask/CleanBeakerTask); our single PickTask can't drive them. To do
  real `place` (and thus drop-and-pick-another instead of `reset`), wire a DualObjectTask path. Until
  then, the gripper-full case requires `reset` between picks.
- **B3 · Blocking REPL.** The viewport is static while you type (live only during robot motion). A
  background-input thread + a main-thread render loop would keep the window always live (the sim API
  must stay on the main thread).
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

- **B11 · W4** — metric aggregation runner (`scripts/run_benchmark.py`/`evaluate.py`/`make_figures.py`
  are still stubs), Figure 1/2, scale to 50–100 episodes, baseline configs with framework components OFF.
- **B12 · Multi-object `quantity` execution** (bring N) — grounding + `count_ge` eval exist; physical
  multi-pick delivery needs `place` (B2).
