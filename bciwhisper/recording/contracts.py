from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class RecordingArtifact:
    raw_path: Path
    isolated_path: Path | None = None
    master_path: Path | None = None
    locked_seconds: float = 0.0
