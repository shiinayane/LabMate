"""Runtime safety monitor (B1b, docs/12) — stop the moment a non-target object is disturbed.

Geometric pre-checks (B1a) cannot predict a reactive motion controller's path; the real floor is to
watch the sim *during* execution and stop on actual disturbance, then hand control to the human. This
module is the pure, sim-free decision logic: it is fed each object's world position per frame (the sim
adapter reads them via ``ObjectUtils.get_geometry_center``) and reports the first NON-target object that
has moved past a threshold from its settled baseline. Reactive — it bounds damage, it does not prevent
first contact (that is B1a's job).
"""

from __future__ import annotations

import math
from typing import Optional, Sequence


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean distance over however many shared dims (3-D when poses have z)."""
    n = min(len(a), len(b))
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(n)))


class DisturbanceMonitor:
    """Trip when a non-target object moves past ``threshold`` from its baseline (ignoring jitter).

    Usage: ``set_baseline(positions)`` once after the scene has settled, then ``update(positions)`` each
    frame; a non-None return ``(name, displacement)`` means stop.
    """

    def __init__(self, target: Optional[str], threshold: float, deadband: float = 0.01):
        self.target = target
        self.threshold = float(threshold)
        self.deadband = float(deadband)
        self._baseline: dict[str, Sequence[float]] = {}

    @property
    def ready(self) -> bool:
        return bool(self._baseline)

    def set_baseline(self, positions: dict[str, Sequence[float]]) -> None:
        self._baseline = {k: list(v) for k, v in positions.items() if v is not None}

    def update(self, positions: dict[str, Sequence[float]]) -> Optional[tuple[str, float]]:
        """First non-target object displaced past threshold (largest first), else None."""
        worst: Optional[tuple[str, float]] = None
        for name, pos in positions.items():
            if name == self.target or pos is None or name not in self._baseline:
                continue
            d = _dist(pos, self._baseline[name])
            if d < self.deadband or d <= self.threshold:
                continue
            if worst is None or d > worst[1]:
                worst = (name, d)
        return worst
