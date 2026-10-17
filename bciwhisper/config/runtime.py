from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class RuntimeConfig:
    block_size: int = int(os.environ.get("BCI_BLOCK_SIZE", "2048"))
    baseline_seconds: float = float(os.environ.get("BCI_BASELINE_SECONDS", "60"))
    keep_locked_seconds: float = float(
        os.environ.get("BCI_RECORDING_KEEP_SECONDS", "15")
    )
    ui_fps: float = float(os.environ.get("BCI_UI_FPS", "20"))
    spectrum_hz: float = float(os.environ.get("BCI_SPECTRUM_HZ", "12.5"))

RUNTIME = RuntimeConfig()
