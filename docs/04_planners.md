# 04 · Planners (4 baselines, one loop)

All baselines share the loop in `01_architecture.md`. They differ only in `propose()` and which
gate signals are active. Implement once, switch by config.

## Candidate scoring

A skill candidate `c = (skill, args)`. The general score (SayCan × Text2Motion shape):

```
score(c) = S_llm(c | instruction, history) ^ α  ×  S_aff(c | scene_graph) ^ β
```

- `S_llm` — LLM "is this skill useful next?". **Score fixed candidate strings**, do not free-generate.
  Enumerate admissible `(skill, grounded_args)` from the registry + scene graph; ask the LLM to
  rank/score them (logprobs, or a JSON ranking call). Guarantees plan validity for free.
- `S_aff` — **deterministic affordance** = `precondition(skill, args, scene_graph)` ∈ {0,1}
  (see `03_skills.md`). NO learned value functions. This is the key feasibility decision and
  doubles as Text2Motion's geometric-feasibility term and the OOD/infeasibility filter.

## `propose()` per baseline

```python
# rule:           pattern-match instruction → template skill sequence (no LLM)
# llm_only:       S_llm only; α=1, β=0  (affordance OFF → exposes ungrounded failures)
# scene_grounded: S_llm × S_aff; α=1, β=1
# saycan:         scene_grounded + iterative: pick argmax, execute, append to history, repeat;
#                 + goal lookahead (below) for termination & replanning
```

## Goal prediction & plan validity (Text2Motion `F_sat`)

```python
goals = llm_predict_goal_props(schema, scene_graph)   # e.g. [is_clean(beaker_03), is_in(beaker_03, rack)]
# a plan/step is valid iff applying skill effects (cheap symbolic transition) reaches a state
# satisfying some goal; episode terminates when satisfies(goals, scene_graph).
```

This gives the **plan-validity** metric automatically and a principled stop condition (better than
"LLM said done"). It also feeds `expected_skill_sequence` verification.

## Gate ordering (per candidate, deterministic)

```python
def gate(cands, schema, sg, cfg):
    # 1. clarification: missing slot or genuine ambiguity → ASK (see 06)
    if router.should_ask(schema, sg): return Decision("ASK", question=router.question(schema, sg))
    best = argmax(cands, score)
    # 2. safety shield: deterministic rules over sg → REFUSE/STOP/CONFIRM (see 05)
    verdict = shield.check(best, schema, sg)
    if verdict in {REFUSE, STOP}: return Decision("REFUSE", reason=verdict.reason)
    if verdict == CONFIRM:        return Decision("ASK", question=verdict.question)
    # 3. affordance: if best infeasible and candidate set empty → justified refusal
    if cfg.affordance and S_aff(best, sg) == 0:
        cands = [c for c in cands if S_aff(c, sg) == 1]
        if not cands: return Decision("REFUSE", reason="no_feasible_skill")
        best = argmax(cands, score)
    return Decision("ACT", skill=best)
```

Clarification and safety are evaluated **jointly** here — this joint ask-vs-refuse-vs-act decision
is a core novelty (see `06_clarification.md`).

## LLM usage notes

- Constrained decoding / JSON mode for the parser (02) and for candidate ranking. Never let the
  LLM emit executable actions directly.
- Temperature 0 for reproducibility; K≈5 candidates per step (Text2Motion setting).
- The LLM is a **proposer only**; the deterministic gate is the arbiter (invariant in 01).
- `llm_only` deliberately removes affordance + monitor to produce the failure baseline the
  framework beats — keep it faithful (don't sneak grounding in).

## Optional later: VLA / learned policy backend

Keep the executor's controller indirection (03) so a skill can later call OpenVLA/Octo/pi0 via
LabUtopia's remote-inference hook. **Not in the MVP** — see `08` and `09`.
