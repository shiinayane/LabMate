"""Structured episode logging (docs/01, 07).

One JSON record per episode (gate decisions + executed history + outcome), appended to a run-level
``episodes.jsonl`` and also dropped as a per-episode file. These logs are the substrate the offline
metric layer (07, W4) reads — so they capture *what happened*, not text.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EpisodeLogger:
    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.out_dir / "episodes.jsonl"

    def write(self, record: dict[str, Any]) -> Path:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        line = json.dumps(record, default=str)
        with self.jsonl.open("a") as f:
            f.write(line + "\n")
        per = self.out_dir / f"{record.get('episode_id', 'episode')}.json"
        per.write_text(json.dumps(record, indent=2, default=str) + "\n")
        return per
