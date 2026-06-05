"""Closed-loop monitor (docs/01).

Reads success/feedback from sim ground truth. In W1 the monitor's stop condition is "the episode's
``eval_function`` is satisfied over the executed trace" — a principled termination (better than
"LLM said done"). ``llm_only`` runs open-loop (monitor off) so it stays a faithful failure baseline.
"""

from __future__ import annotations

from typing import Sequence

from .evaluation.metrics import PCResult, compute_pc
from .schema.episode import EvalFunction
from .scene.scene_graph import SceneGraph


def evaluate(eval_function: EvalFunction, trace: Sequence[SceneGraph]) -> PCResult:
    return compute_pc(eval_function, trace)


def satisfies(eval_function: EvalFunction, trace: Sequence[SceneGraph]) -> bool:
    """True when the episode goal is reached over the trace (closed-loop stop condition)."""
    return compute_pc(eval_function, trace).success
