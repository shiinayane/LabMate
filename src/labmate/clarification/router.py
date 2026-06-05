"""Clarification router (docs/06).

W1 STUB with the final interface. The real 4-token router (ASK on missing slots / genuine
ambiguity, jointly with safety) lands in W3. Keeping the signature stable now means the unified
gate (docs/04) does not change when W3 fills this in.
"""

from __future__ import annotations

from ..scene.scene_graph import SceneGraph
from ..schema.instruction import InstructionSchema


def should_ask(schema: InstructionSchema, sg: SceneGraph) -> bool:
    """Return True if the system should ASK before acting. W1: never (no-op)."""
    return False


def question(schema: InstructionSchema, sg: SceneGraph) -> str:
    """The clarifying question to surface when should_ask is True. W1: placeholder."""
    return "Which object did you mean?"
