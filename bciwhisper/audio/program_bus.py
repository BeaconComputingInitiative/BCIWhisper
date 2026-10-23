# BEACON COMPUTING INITIATIVE
# BCIWhisper 59.3 — Studio Program Bus
# Developer Seal: CJB-DEV-2026
# SHA-256: recorded in release evidence
from __future__ import annotations

import threading
import numpy as np


class StudioProgramBus:
    """Single-input studio program bus; additional independent inputs require capture routing."""
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._gain = 1.0
        self._muted = False

    def configure(self, gain: float, muted: bool) -> None:
        if not 0.0 <= gain <= 2.0:
            raise ValueError("Program gain must be between 0 and 2")
        with self._lock:
            self._gain = float(gain)
            self._muted = bool(muted)

    def settings(self) -> dict:
        with self._lock:
            return {"gain": self._gain, "muted": self._muted}

    def process(self, mono: np.ndarray) -> np.ndarray:
        with self._lock:
            gain, muted = self._gain, self._muted
        source = np.asarray(mono, dtype=np.float32).reshape(-1)
        if muted:
            return np.zeros_like(source)
        return np.clip(source * gain, -1.0, 1.0).astype(np.float32, copy=False)
