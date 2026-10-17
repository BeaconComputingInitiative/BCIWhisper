from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AudioEndpoint:
    index: int
    name: str
    backend: str
    channels: int
    sample_rate: int
    stable_id: str = ""

@dataclass(frozen=True)
class CaptureSession:
    endpoint: AudioEndpoint
    generation: int
