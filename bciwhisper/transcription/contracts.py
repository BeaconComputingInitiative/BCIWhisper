from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass(frozen=True)
class TranscriptResult:
    backend: str
    audio_path: Path
    text: str
    language: str = ""

class TranscriptionBackend(Protocol):
    name: str
    def available(self) -> bool: ...
    def transcribe(self, audio_path: Path) -> TranscriptResult: ...
