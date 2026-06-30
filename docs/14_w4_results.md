# 14 · W4 results — decision-level metrics (MVP, sim-free)

> Snapshot of the W4-MVP benchmark. The live artifacts (`outputs/eval/metrics.{md,csv}`,
> `results.jsonl`) are gitignored; this file is the tracked copy for the paper / group meeting.
> Regenerate any time with the commands below. Date: 2026-06-30. (Reviewed + corrected after a
> 3-agent audit — see "What the numbers do and don't show".)

## How to reproduce

```bash
# 3 key-free baselines (deterministic, no API key, no Isaac):
./scripts/labrun python scripts/run_benchmark.py
# add the llm_only weak baseline (needs ANTHROPIC_API_KEY; loaded from .env):
./scripts/labrun python scripts/run_benchmark.py --with-llm
# aggregate -> outputs/eval/metrics.md + metrics.csv:
./scripts/labrun python scripts/evaluate.py
```

Everything runs **sim-free**: `run_benchmark` drives the real `NL → schema → propose → gate → execute`
pipeline over a deterministic `SymbolicBackend` (built from each episode's `init_overrides`), so the
suite finishes in seconds and is fully reproducible. Episodes: ~32 (`benchmark/episodes/`, regenerated
by `generate_suite.py`) across direct / reference / ambiguous / unsafe / recovery / quantity. (One run
overwrites `results.jsonl` with only the planners it ran — pass them all in one invocation.)

## Results (128 runs · 32 episodes × 4 planners)

| metric | rule | llm_only | scene_grounded | saycan |
| --- | --- | --- | --- | --- |
| task success (solvable) | 0.77 | 0.59 | **1.00** | **1.00** |
| grounding acc | 1.00 | 0.82 | **1.00** | **1.00** |
| ask recall | 1.00 | 0.00 | **1.00** | **1.00** |
| ask precision | 1.00 | n/a | **1.00** | **1.00** |
| unsafe-rejection rate | 1.00 | 0.00 | **1.00** | **1.00** |
| false-refusal rate ↓ | 0.15 | 0.00 | **0.00** | **0.00** |
| recovery rate | 1.00 | 0.00 | **1.00** | **1.00** |

_All metrics higher-is-better except false-refusal rate (↓). `scene_grounded` / `saycan` are the
framework rows (router + shield + grounding + affordance + closed-loop ON)._

**task success (solvable)** is over the 22 episodes where success is a meaningful sim-free signal —
direct / reference / ambiguous / recovery. It **excludes**: *unsafe* (success is inverted there — see
below — so it's reported via unsafe-rejection instead) and *quantity* (multi-pick delivery is
unimplemented sim-free, so success is structurally 0 for every planner; quantity is measured by its
gate *decision*, not success).

### Failure / block attribution (count by stage)

| stage | rule | llm_only | scene_grounded | saycan |
| --- | --- | --- | --- | --- |
| execution | 4 | 13 | 4 | 4 |
| grounding | 5 | 0 | 0 | 0 |
| safety | 6 | 0 | 6 | 6 |

## What the numbers show

- **The weak LLM baseline fails exactly where the framework's gate is designed to help.** `llm_only`
  (router / shield / affordance / monitor all OFF) scores **0.00 ask-recall** (never clarifies an
  ambiguous request), **0.00 unsafe-rejection** (it just grabs the hazardous bottle / acts amid a
  spill — 13 of its failures are at *execution*, with zero safety/grounding blocks because those stages
  are off), **0.82 grounding** (the LLM parser mis-resolves some referring expressions), and **0.00
  recovery**. The gate-equipped rows are 1.00 on all four. This `llm_only`-vs-gate gap is the headline
  result and it is robust (the 0s are structural — the switches are genuinely off — not LLM noise).
- **Safety must be read from unsafe-rejection, not success.** On the unsafe split, raw `is_held` success
  is *inverted*: a planner that refuses correctly scores 0 (it never holds the object) while one that
  blindly grabs the hazard scores 1. We therefore exclude unsafe from "task success" and report it via
  **unsafe-rejection rate (0.00 vs 1.00)**. This is the core argument for reporting decision-level safety
  metrics rather than task success alone.
- **`rule` (non-LLM template baseline)** is *not* a strawman — it shares the same router + shield, so it
  also gets 1.00 on ask / unsafe-rejection / recovery. Its only deficits are referring-expression
  grounding (its proposer ignores "left/right/nearest/farthest" → 5 grounding refusals → 0.77 success
  and the lone 0.15 false-refusal). This shows the clarification/safety wins come from the **gate** and
  the grounding wins come from **scene-grounded proposal**.

## What the numbers do *and don't* show (honesty notes, from the audit)

- **grounding acc is resolver-driven, not planner-driven for the key-free rows.** `rule`,
  `scene_grounded`, `saycan` all use the *same* deterministic resolver on the *same* parsed schema, so
  their 1.00 is identical *by construction* — it does **not** show the framework out-grounds `rule`. The
  only real grounding delta is `llm_only` (0.82), which reflects its LLM *parser*, not its proposer.
- **The ambiguity oracle only helps planners that ask.** Ambiguous episodes are auto-answered from
  `episode.answer`; this answer is injected *only* when a planner ASKs. So the framework's success on the
  ambiguous split measures *that it asks* (and a perfect human then answers), not that it would resolve a
  noisy real answer. Methodologically correct, but it is an oracle.
- **recovery rate is a retry *switch*, not a replanning algorithm.** `SymbolicBackend` fails the first
  attempt then succeeds; any planner with `max_retries ≥ 1` recovers 100%, `llm_only` (max_retries 0)
  recovers 0%. It demonstrates closed-loop-on/off, not sophisticated recovery.
- **Only 2 of 7 shield rules are exercised** (`hazardous_target`, `env_hazard`); the S1 / CONFIRM tiers
  and the geometric clutter (`feasibility`) gate are **not** triggered by this suite. The safety story
  here rests on those two rules.
- **`llm_only` is a single sample** (haiku, temp 0 — not bit-reproducible); the 3 key-free rows are fully
  deterministic. Treat the `llm_only` column as one draw, not a mean±std.

## Scope / deferred

- **Decision-level, sim-free.** These measure the gate's decisions (ground / ask / refuse / recover),
  not physical grasp success. Physical execution success via real Isaac Sim is deferred (per-episode
  subprocess; grasping is per-object flaky). docs/12 B11.
- **`composite` (multi-step) not included** — single-intent parser; true sequencing is future work.
- **n ≈ 4–6 per category** (recovery/quantity = 4). Enough to show the contrast; scale to 50–100 for
  final paper tables, and add S1/CONFIRM/clutter and AmbiK paired controls for breadth.
