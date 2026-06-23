"""Planner baselines as ``propose()`` functions (docs/04).

Each baseline is the same loop (``planner.loop``) with a different proposer + gate switches:

- ``rule``      — pattern-match the instruction → a template skill sequence (no LLM). Affordance ON.
- ``llm_only``  — the LLM scores FIXED candidate strings; alpha=1, beta=0 (affordance OFF), monitor
                  OFF. Deliberately the failure baseline the framework beats — keep it faithful
                  (no hidden grounding), per docs/04/07.

``scene_grounded`` and ``saycan`` arrive in W2/W3.
"""

from __future__ import annotations

from ..scene import grounding
from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema
from ..skills.definitions import SKILLS
from ..skills.registry import (
    Candidate,
    enumerate_candidates,
    enumerate_grounded,
    ground_skill,
)


def _score(cands: list[Candidate], schema, history, client) -> list[Candidate]:
    """Attach LLM usefulness scores to candidates when a client is provided (else uniform)."""
    if client is not None and cands:
        scores = client.score_candidates(schema.model_dump(), [c.as_text() for c in cands], history)
        for c, s in zip(cands, scores):
            c.s_llm = float(s)
    return cands


# ---- rule ---------------------------------------------------------------
def _template(schema: InstructionSchema) -> list[str]:
    """Static skill sequence for an intent (template match)."""
    intent = schema.intent
    if intent in SKILLS:
        return [intent]
    if intent in ("bring", "composite"):
        return ["pick", "place"]
    return []


def propose_rule(schema: InstructionSchema, sg: SceneGraph, history: list) -> list[Candidate]:
    """Grounded candidate(s) for the current step of the template (deterministic, no LLM).

    Advance only on **successful** acts (``h == ("act", text, ok)``), so a failed step is re-proposed
    (retry) rather than skipped — the loop bounds the retries via ``max_retries``.
    """
    template = _template(schema)
    step_idx = sum(1 for h in history if h and h[0] == "act" and len(h) > 2 and h[2])
    if step_idx >= len(template):
        return []
    return ground_skill(template[step_idx], schema, sg)


# ---- llm_only -----------------------------------------------------------
def propose_llm_only(schema: InstructionSchema, sg: SceneGraph, history: list,
                     client) -> list[Candidate]:
    """Rank enumerated candidate strings with the LLM. No affordance, no monitor (open-loop).

    ``client.score_candidates(instruction, candidates, history) -> list[float]`` returns one
    usefulness score per candidate string. The score is stored on each candidate's ``s_llm``; the
    loop's gate picks argmax (beta=0, so affordance does not enter).
    """
    if client is None:
        raise RuntimeError("llm_only requires an LLM client (set ANTHROPIC_API_KEY / pass a client)")
    cands = enumerate_candidates(schema, sg)
    if not cands:
        return []
    scores = client.score_candidates(schema.model_dump(), [c.as_text() for c in cands], history)
    for c, s in zip(cands, scores):
        c.s_llm = float(s)
    return cands


# ---- scene_grounded -----------------------------------------------------
def propose_scene_grounded(schema: InstructionSchema, sg: SceneGraph, history: list,
                           client=None) -> list[Candidate]:
    """Grounded candidates (referring-expression resolution), optionally LLM-scored.

    `S_llm × S_aff` with affordance ON and grounding ON (the gate applies β=1). Runs **without** a
    client (s_llm uniform → pure grounding + affordance), so it is key-free for the first sim test.
    """
    return _score(enumerate_grounded(schema, sg), schema, history, client)


# ---- saycan -------------------------------------------------------------
def propose_saycan(schema: InstructionSchema, sg: SceneGraph, history: list,
                   client=None) -> list[Candidate]:
    """Goal-directed iterative proposer (docs/04): propose the next skill that advances the unmet
    goal given the CURRENT scene state. Because it keys off state (not a step counter), a failed
    skill leaves its goal unmet and is naturally re-proposed → closed-loop recovery / replan.
    """
    target = grounding.resolve(schema, sg).target
    if target is None:
        return []
    intent, dest = schema.intent, schema.destination
    o = sg.get(target)

    def step(skill_name: str) -> list[Candidate]:
        return _score(ground_skill(skill_name, schema, sg, object_names=[target]),
                      schema, history, client)

    if intent in ("pick", "mobile_pick"):
        return [] if sg.held == target else step(intent)
    if intent in ("place", "bring", "composite"):
        placed = bool(dest) and (sg.has_relation("is_on", target, dest)
                                 or sg.has_relation("is_in", target, dest))
        if placed:
            return []
        return step("place") if sg.held == target else step("pick")
    if intent == "clean":
        return [] if (o and o.is_clean) else step("clean")
    if intent == "open":
        return [] if (o and o.is_open) else step("open")
    if intent == "pour":
        d = sg.get(dest) if dest else None
        return [] if (d and d.is_filled) else step("pour")
    return _score(enumerate_grounded(schema, sg), schema, history, client)
