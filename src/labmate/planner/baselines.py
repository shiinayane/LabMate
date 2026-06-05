"""Planner baselines as ``propose()`` functions (docs/04).

Each baseline is the same loop (``planner.loop``) with a different proposer + gate switches:

- ``rule``      — pattern-match the instruction → a template skill sequence (no LLM). Affordance ON.
- ``llm_only``  — the LLM scores FIXED candidate strings; alpha=1, beta=0 (affordance OFF), monitor
                  OFF. Deliberately the failure baseline the framework beats — keep it faithful
                  (no hidden grounding), per docs/04/07.

``scene_grounded`` and ``saycan`` arrive in W2/W3.
"""

from __future__ import annotations

from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema
from ..skills.definitions import SKILLS
from ..skills.registry import Candidate, enumerate_candidates, ground_skill


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
    """Grounded candidate(s) for the current step of the template (deterministic, no LLM)."""
    template = _template(schema)
    step_idx = sum(1 for h in history if h and h[0] == "act")
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
