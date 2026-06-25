# 12 · Improvement backlog

> Living list of improvements **outside the current MVP scope** or surfaced during development. Not
> commitments; a place to capture "we should do this" so it isn't lost. Promote items into a weekly
> plan when picked up. (Design lives in 01–10; status/code-map in 11.)

## High-value

### B1 · Failure-aware escalation — hand control back to the human on failure / infeasibility
**Observed (2026-06):** in the interactive demo, `pick the left beaker` *executed* (the RMPFlow
obstacle-avoidance arm motion ran) but **did not grasp** — the controller returned `is_success=False`.
The demo did a single attempt, reported `executed=1 ok=False`, and moved on with **no recourse**.
Separately, picking with a full gripper yields a bare `no_feasible_skill` token.

**Improvement:** treat execution failure and infeasibility as *interaction points*, not dead ends:
- On `ok==False` (grasp slipped / avoidance blocked the approach): **ASK** the human — "I couldn't
  grasp `<obj>` — retry / pick a different one / abort?" — instead of silently failing.
- On `no_feasible_skill` / `s_aff==0`: surface a **human-readable reason** ("I'm holding `<x>`; say
  `reset` or place it first" — derived from the trace's `aff_failed`), not the raw token.
- Wire the existing `max_retries` budget into the **interactive** `run_turn` (today it does one
  attempt: `if sat or not ok: break`); the benchmark loop already retries.
- Deeper: **closed-loop grasp verification** from sim GT (did the prim actually lift?) rather than
  trusting the controller's `is_success`; ties to the deferred geometric held-check (B5).

This is the general pattern the framework is *about* (clarify/escalate rather than blunder on), so it
is the most on-thesis backlog item — worth a dedicated mini-plan.

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
