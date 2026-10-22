# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    from . import _bci_native as _native
except Exception:
    _native = None


@dataclass(frozen=True)
class NativeAudioMetrics:
    rms: float
    peak: float
    zero_crossing_rate: float
    dc_offset: float
    backend: str


def native_capabilities() -> dict[str, Any]:
    loaded = _native is not None
    return {
        "loaded": loaded,
        "language": "C++20" if loaded else "Python/NumPy fallback",
        "abi": int(getattr(_native, "__bci_abi__", 0)) if loaded else 0,
        "script": str(getattr(_native, "__bci_script__", "")) if loaded else "",
        "metrics": True,
        "ring_buffer": loaded,
    }


class NativeAudioAdapter:
    """Stable Python boundary around the optional C++20 native core."""

    def __init__(self) -> None:
        self._native = _native

    @property
    def native_loaded(self) -> bool:
        return self._native is not None

    def analyze(self, samples: np.ndarray) -> NativeAudioMetrics:
        data = np.asarray(samples, dtype=np.float32).reshape(-1)

        if self._native is not None:
            result = self._native.analyze_audio(data)
            return NativeAudioMetrics(
                rms=float(result.rms),
                peak=float(result.peak),
                zero_crossing_rate=float(result.zero_crossing_rate),
                dc_offset=float(result.dc_offset),
                backend="C++20",
            )

        if data.size == 0:
            return NativeAudioMetrics(0.0, 0.0, 0.0, 0.0, "NumPy")

        clean = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        rms = float(np.sqrt(np.mean(np.square(clean), dtype=np.float64)))
        peak = float(np.max(np.abs(clean)))
        dc_offset = float(np.mean(clean, dtype=np.float64))

        if clean.size > 1:
            signs = np.signbit(clean)
            zcr = float(np.count_nonzero(signs[1:] != signs[:-1]) / (clean.size - 1))
        else:
            zcr = 0.0

        return NativeAudioMetrics(
            rms=rms,
            peak=peak,
            zero_crossing_rate=zcr,
            dc_offset=dc_offset,
            backend="NumPy",
        )

    def create_ring_buffer(self, capacity: int):
        if self._native is None:
            raise RuntimeError(
                "C++20 native ring buffer is unavailable; build native/CMakeLists.txt first"
            )
        return self._native.AudioRingBuffer(int(capacity))
