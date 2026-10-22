# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import math

import numpy as np

from bciwhisper.native import NativeAudioAdapter, native_capabilities


class NativeDSPService:
    """Application-service facade for deterministic native DSP primitives."""

    def __init__(self) -> None:
        self._adapter = NativeAudioAdapter()
        self._last_self_test = "NOT_RUN"

    @property
    def native_loaded(self) -> bool:
        return self._adapter.native_loaded

    @property
    def backend_label(self) -> str:
        return "C++20 / pybind11" if self.native_loaded else "Python / NumPy fallback"

    @property
    def capabilities(self) -> dict:
        return native_capabilities()

    @property
    def last_self_test(self) -> str:
        return self._last_self_test

    def self_test(self) -> dict:
        sample_rate = 48_000
        duration = 0.05
        count = int(sample_rate * duration)
        t = np.arange(count, dtype=np.float32) / sample_rate
        signal = (0.25 * np.sin(2.0 * math.pi * 1000.0 * t)).astype(np.float32)

        metrics = self._adapter.analyze(signal)

        expected_rms = 0.25 / math.sqrt(2.0)
        ok = (
            abs(metrics.rms - expected_rms) < 0.01
            and 0.24 <= metrics.peak <= 0.26
            and 0.02 <= metrics.zero_crossing_rate <= 0.06
            and abs(metrics.dc_offset) < 0.01
        )

        self._last_self_test = "PASS" if ok else "FAIL"
        return {
            "ok": ok,
            "backend": metrics.backend,
            "rms": metrics.rms,
            "peak": metrics.peak,
            "zero_crossing_rate": metrics.zero_crossing_rate,
            "dc_offset": metrics.dc_offset,
        }
