"""Provider-agnostic LLM client (docs/04).

Two capabilities the planner needs:
- ``complete_json(system, user, json_schema)`` — constrained JSON (the parser, 02).
- ``score_candidates(instruction, candidates, history)`` — usefulness score per FIXED candidate
  string (the ``llm_only`` proposer, 04). Never free-generates actions.

The default backend is Anthropic (Claude), temperature 0, with prompt caching on the static system
prompt. The ``anthropic`` SDK is imported lazily and is an optional dependency
(``uv sync --extra llm``) — so importing labmate and running the sim-free tests needs no SDK/key.
A live call without ``ANTHROPIC_API_KEY`` raises a clear error.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Protocol, Sequence


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, json_schema: dict) -> dict: ...
    def score_candidates(self, instruction: dict, candidates: Sequence[str], history: list) -> list[float]: ...


_DEFAULT_MODEL = "claude-opus-4-8"   # latest Claude; override via planner cfg `llm.model`


class AnthropicClient:
    """Anthropic backend. Uses tool-use for guaranteed-valid JSON and prompt caching."""

    def __init__(self, model: str = _DEFAULT_MODEL, temperature: float = 0.0,
                 max_tokens: int = 1024):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None
        self.last_exchange: Optional[dict] = None   # {system, user, tool, response} of the last call

    def _anthropic(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - exercised only on live use
                raise RuntimeError(
                    "anthropic SDK not installed; run `uv sync --extra llm`"
                ) from e
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set (required for live LLM calls)")
            self._client = anthropic.Anthropic()
        return self._client

    def _tool_call(self, system: str, user: str, tool_name: str, tool_schema: dict) -> dict:
        client = self._anthropic()
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=[{"name": tool_name, "description": "Emit the structured result.",
                    "input_schema": tool_schema}],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                out = dict(block.input)
                self.last_exchange = {"system": system, "user": user,
                                      "tool": tool_name, "response": out}
                return out
        raise RuntimeError("model did not return a tool_use block")

    def complete_json(self, system: str, user: str, json_schema: dict) -> dict:
        return self._tool_call(system, user, "emit", json_schema)

    def score_candidates(self, instruction: dict, candidates: Sequence[str], history: list) -> list[float]:
        system = (
            "You score how useful each candidate robot skill is as the NEXT step for the "
            "instruction. Return a score in [0,1] per candidate, same order. Do NOT invent skills."
        )
        user = json.dumps({"instruction": instruction, "history": history,
                           "candidates": list(candidates)})
        schema = {
            "type": "object",
            "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
            "required": ["scores"],
        }
        out = self._tool_call(system, user, "score", schema)
        scores = out.get("scores", [])
        # pad/trim defensively so callers always get one score per candidate
        scores = (list(scores) + [0.0] * len(candidates))[: len(candidates)]
        return [float(s) for s in scores]


def default_client(opts: Optional[dict] = None) -> AnthropicClient:
    opts = opts or {}
    return AnthropicClient(
        model=opts.get("model", _DEFAULT_MODEL),
        temperature=opts.get("temperature", 0.0),
        max_tokens=opts.get("max_tokens", 1024),
    )
