"""Candidate scoring (docs/04).

    score(c) = S_llm(c | instruction, history) ** alpha  ×  S_aff(c | scene_graph) ** beta

- ``S_llm`` — the LLM "is this skill useful next?" score over FIXED candidate strings (never
  free-generated). For ``rule`` it is uniform; ``llm_only``/``scene_grounded``/``saycan`` get it
  from the LLM client.
- ``S_aff`` — deterministic affordance ∈ {0,1} (see ``labmate.affordance``).

Per-baseline exponents: rule (n/a, template), llm_only (alpha=1, beta=0), scene_grounded /
saycan (alpha=1, beta=1).
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, TypeVar

T = TypeVar("T")


def combine(s_llm: float, s_aff: float, alpha: float = 1.0, beta: float = 1.0) -> float:
    return (s_llm ** alpha) * (s_aff ** beta)


def argmax(items: Sequence[T], key: Callable[[T], float]) -> Optional[T]:
    """argmax by key; None for an empty sequence. Stable (first max wins)."""
    best: Optional[T] = None
    best_score = float("-inf")
    for it in items:
        sc = key(it)
        if sc > best_score:
            best_score, best = sc, it
    return best
