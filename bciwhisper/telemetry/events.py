from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

@dataclass(frozen=True)
class TelemetryEvent:
    name: str
    payload: dict[str, Any]
    timestamp_utc: str = ""

    def normalized(self) -> dict[str, Any]:
        ts = self.timestamp_utc or datetime.now(timezone.utc).isoformat()
        return {
            "name": self.name,
            "timestamp_utc": ts,
            **self.payload,
        }
