# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 04a7dcc94ba88f72a3ed258245030576949bfc8458f647f801bb0a84bd60c41c
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

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
    model: str = ""
    duration_seconds: float = 0.0


class TranscriptionBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def transcribe(self, audio_path: Path) -> TranscriptResult: ...
