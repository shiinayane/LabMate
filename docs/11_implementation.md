# 11 · Implementation status & code map

> **Living doc — update it as each week lands.** Docs 01–10 are the (mostly frozen) *design*; this
> file tracks what is *actually built*, how the code maps to that design, and how to run it. When you
> finish a milestone, flip its row below and adjust the code map / "simplifications" list.

## Status

| Milestone (09_roadmap) | State | Notes |
|------------------------|-------|-------|
| Environment bring-up | ✅ done | mise(runtime)+uv(packages), Isaac Sim 5.1 on aarch64/GB10. See docs/08. |
| **W1 — schema + loop (`rule`, `llm_only`)** | ✅ done | end-to-end `pick` runs in sim; 9 unit tests green. |
| W2 — scene graph + grounding + `scene_grounded` | ⬜ next | referring-expression resolution, relations, reference/quantity episodes. |
| W3 — clarification router + safety shield + sequence exec + `saycan` | ⬜ | the two gate stubs become real; ambiguous/unsafe/recovery splits. |
| W4 — metric suite + the two figures | ⬜ | full metrics over logs; 50–100 episodes; Figure 1 + Figure 2. |

## The pipeline → code map

One instruction flows `NL → schema → propose → gate → execute → monitor → log`. Each stage is one
place in the code (design-doc reference in parentheses):

| Stage | What it does | Code | Design |
|-------|--------------|------|--------|
| ① parse | NL → structured `InstructionSchema` | `parser/rule_parser.py`, `parser/llm_parser.py` | 02 |
| — schema | the data structures + predicate library | `schema/{instruction,episode,predicates}.py` | 02 |
| — scene | objects + flags + relations (sim GT or dict) | `scene/scene_graph.py` | 02, 08 |
| ② propose | candidate `(skill, args)` from registry+scene | `planner/baselines.py`, `skills/registry.py` | 04, 03 |
| — skills | the 8 skills + preconditions/effects/success | `skills/definitions.py` | 03 |
| — affordance | deterministic feasibility `S_aff ∈ {0,1}` | `affordance.py`, `planner/scoring.py` | 04 |
| ③ gate | joint **ASK / REFUSE / ACT** arbiter | `planner/loop.py::gate` | 04 |
| — clarify | ASK router (**W1 stub → False**) | `clarification/router.py` | 06 |
| — safety | shield (**W1 stub → ALLOW**) | `safety/shield.py` | 05 |
| ④ execute | drive a LabUtopia controller | `skills/executor.py` (`SimBackend`), `labutopia/adapter.py` | 03, 08 |
| ⑤ monitor | success/PC from sim GT (stop condition) | `monitor.py`, `evaluation/metrics.py` | 01, 07 |
| — log | structured per-episode JSONL | `episode_logger.py` | 01, 07 |
| loop | ties it all together, 4 baselines = configs | `planner/loop.py::run_episode` | 01, 04 |
| LLM seam | provider-agnostic client (Anthropic) | `llm/client.py` | 04 |

**Invariant (do not break):** the LLM only *proposes*; the deterministic `gate()` decides. Raw LLM
text never drives the robot (docs/01).

**The only module that imports Isaac Sim is `labutopia/adapter.py`** (lazy imports inside methods).
Everything else is unit-testable on a plain machine — that is why `uv run pytest` needs no GPU/key.

## Data / configs (not code)

- `benchmark/episodes/<split>/*.json` — one task each (instruction + `gold_schema` + `eval_function`).
  W1 ships `direct/pick_conical_bottle.json` (the runnable proof).
- `benchmark/scenes/<scene>.json` — maps LabUtopia USD prim paths → `{category, flags}` (grounding map).
- `benchmark/schema/episode.schema.json` — **exported** from `Episode.model_json_schema()`; validates
  every episode. Regenerate with `from labmate.schema.episode import export_schema_file`.
- `configs/planners/{rule,llm_only}.yaml` — a baseline = a set of loop switches.

## How to run

```bash
# fast logic tests — no GPU, no key
uv run pytest

# one episode end-to-end in the sim (rule baseline; no LLM key needed)
uv run python scripts/run_episode.py \
  --episode benchmark/episodes/direct/pick_conical_bottle.json \
  --planner configs/planners/rule.yaml --headless
# → outputs/labmate/<episode_id>/<episode_id>.json  (schema, decisions, success, pc)

# llm_only (live): set ANTHROPIC_API_KEY, then
uv sync --extra llm
uv run python scripts/run_episode.py --episode ... --planner configs/planners/llm_only.yaml --headless
```

Env injection (`LD_PRELOAD`, EULA) is automatic under the user's zsh `uv run` — see docs/08.

## Key implementation decisions

- **Schemas = pydantic v2** (not dataclasses); JSON Schema is exported from the models (docs/02 note).
- **`Skill` is a plain dataclass** — it holds callables (preconditions/effects/success), not data.
- **`rule` baseline drives the W1 end-to-end run** (no LLM key). `llm_only` is wired + mock-tested;
  the Anthropic SDK is an **optional, lazy-imported** dep (`uv sync --extra llm`).
- **Two backends** implement one `Backend` protocol: `SymbolicBackend` (no sim, for tests/dry-runs,
  applies skill effects) and `SimBackend` (real sim via the adapter).

## W1 simplifications to revisit

- **`is_held` is derived from the pick controller's success** (object lifted ≥0.1 m) because LabUtopia
  exposes no gripper-held flag → W2: a geometric held-check.
- **Grounding is category-only** (first scene object of the schema's category); no referring-expression
  resolution yet → W2.
- **Clarification + safety gates are no-op stubs** (interfaces final) → W3.
- **One runnable episode**; reference/quantity/ambiguous/unsafe/recovery seeds need W2/W3 machinery.

## Gotchas

- **`SimulationApp.close()` hard-exits the process** (fastShutdown). Do all logging/printing BEFORE
  closing the session, or it silently never runs (`scripts/run_episode.py`).
