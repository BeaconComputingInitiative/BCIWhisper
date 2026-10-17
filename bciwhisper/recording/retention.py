from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RetentionPolicy:
    minimum_locked_seconds: float = 15.0

    def keep(self, locked_seconds: float) -> bool:
        return float(locked_seconds) >= self.minimum_locked_seconds
