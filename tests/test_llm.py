"""W1.c — llm_only proposer + LLM parser, against a MOCK client (no SDK, no key).

The live Anthropic path is deferred until ANTHROPIC_API_KEY is set; here we only verify wiring:
the proposer ranks fixed candidate strings, and the parser turns a JSON dict into a valid schema.
"""

from __future__ import annotations

from labmate.parser.llm_parser import LLMParser
from labmate.planner.baselines import propose_llm_only
from labmate.schema.instruction import InstructionSchema
from labmate.scene.scene_graph import SceneGraph


class MockClient:
    """Scores candidates by a fixed preference; returns a canned schema for parsing."""

    def __init__(self, prefer: str = "conical_bottle02"):
        self.prefer = prefer

    def score_candidates(self, instruction, candidates, history):
        return [1.0 if self.prefer in c else 0.1 for c in candidates]

    def complete_json(self, system, user, json_schema):
        return {"intent": "pick", "object_category": "conical_flask", "quantity": 1}


def _scene():
    return SceneGraph.from_dict({
        "objects": [
            {"name": "conical_bottle02", "category": "conical_flask"},
            {"name": "beaker_01", "category": "conical_flask"},
        ],
    })


def test_llm_only_ranks_candidates():
    schema = InstructionSchema(intent="pick", object_category="conical_flask")
    cands = propose_llm_only(schema, _scene(), history=[], client=MockClient())
    assert len(cands) == 2
    top = max(cands, key=lambda c: c.s_llm)
    assert top.args["target"] == "conical_bottle02" and top.s_llm == 1.0


def test_llm_only_requires_client():
    schema = InstructionSchema(intent="pick", object_category="conical_flask")
    try:
        propose_llm_only(schema, _scene(), history=[], client=None)
        assert False, "expected RuntimeError without a client"
    except RuntimeError:
        pass


def test_llm_parser_produces_valid_schema():
    schema = LLMParser(MockClient()).parse("pick up the conical bottle")
    assert isinstance(schema, InstructionSchema)
    assert schema.intent == "pick" and schema.object_category == "conical_flask"
