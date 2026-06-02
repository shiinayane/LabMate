# 06 · Clarification router

Decides, per instruction step, whether to **ACT / ASK / REFUSE** — jointly with safety (05).
The joint ambiguity-and-safety decision is a core LabMate novelty: prior work does clarification
*or* safety, not both in one gate.

## Mechanism: explicit decision token (not thresholds, not training)

2025–2026 consensus (AbstainEQA, Ask-to-Clarify, Ask-to-Act): make ask/act/refuse an **explicit
emitted symbol** from a prompted model, NOT an entropy/conformal threshold and NOT a trained
classifier (AbstainEQA shows trained classifiers overfit text cues and lose to prompting).

4-token router output:

```
<ACT>       proceed with the chosen skill
<ASK>       ambiguity / missing slot → emit a clarifying question, get answer, re-enter
<RESOLVED>  ambiguity cleared after a prior <ASK> → commit the resolved schema
<REFUSE>    target absent / infeasible / unsafe → halt (ties into safety shield, 05)
```

```python
def should_ask(schema, sg) -> bool:
    return bool(schema.missing_slots) or is_genuinely_ambiguous(schema, sg)

def route(schema, sg) -> Token:
    # single prompted LLM call; output constrained to the 4 tokens + question text
    # prompt includes: instruction, scene object list (sg), dialogue history, ambiguity rubric
    ...
```

## When to ASK vs REFUSE (behavior-keyed)

Use the `ambiguity_type` taxonomy (02) to set the target behavior:

| condition | route |
|-----------|-------|
| `preferences` (multiple valid objects, preference unknowable) | **ASK** |
| `common_sense` (resolvable by world knowledge) | ACT (ask rarely) |
| referential-underspecification ("the white cabinet", several exist) | **ASK** |
| false-presupposition (references a nonexistent object) | **REFUSE** |
| information-unavailable / needs-action-to-know | ASK or REFUSE |
| `safety` (wrong choice harmful) / shield says CONFIRM | **ASK**; shield REFUSE/STOP → **REFUSE** |

The AbstainEQA 5 failure modes map onto the AmbiK 3 categories — annotate each episode with both
so ASK-vs-REFUSE is grounded; do not restructure into 5 categories.

## Clarification loop

```
<ASK> → question → answer (sim oracle in MVP) → resolve(schema) → <RESOLVED> → continue
```

- Single-turn is enough for the MVP; allow ≤2 turns.
- The "answer" comes from the episode's gold `answer` field (oracle user). No human in the loop.
- Resolving fills the `missing_slots`; the loop re-enters the gate.

## Anti-over-asking

Over-asking (asking when it should just act) is the #1 failure mode to guard against. Penalize it
explicitly via the metrics (07): report ask-decision **precision** alongside recall, and the
**Question Ratio** (questions asked / minimum required). Keep `common_sense` cases on the ACT path.

## Interaction with safety

The gate (04) calls clarification first, then the shield. But conceptually they are one joint
decision: a `safety`-type ambiguity should ASK (confirm) rather than silently act, and a confirmed
hazard should REFUSE. Implement `should_ask` and `shield.check` to share the same object-flag view
so they never contradict (e.g., never ACT on an unknown hazardous liquid without CONFIRM).
