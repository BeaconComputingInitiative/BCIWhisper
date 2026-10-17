from __future__ import annotations
from dataclasses import dataclass

@dataclass
class BaselineAccumulator:
    required_seconds: float = 60.0
    valid_audio_seconds: float = 0.0
    blocks: int = 0
    completion_emitted: bool = False

    def reset(self):
        self.valid_audio_seconds = 0.0
        self.blocks = 0
        self.completion_emitted = False

    def add(self, frames: int, sample_rate: int) -> bool:
        if frames <= 0 or sample_rate <= 0:
            return False
        self.blocks += 1
        self.valid_audio_seconds += frames / float(sample_rate)
        if (
            self.valid_audio_seconds >= self.required_seconds
            and not self.completion_emitted
        ):
            self.completion_emitted = True
            return True
        return False
