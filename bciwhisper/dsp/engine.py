# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bciwhisper.dsp.baseline import BaselineAccumulator
from bciwhisper.dsp.filters import StatefulBandpass
from bciwhisper.native import NativeAudioAdapter


@dataclass(frozen=True)
class DSPFrame:
    filtered: np.ndarray
    spectrum_db: np.ndarray
    frequencies_hz: np.ndarray
    sample_rate: int
    rms: float
    peak: float
    peak_freq: float
    noise_floor_db: float
    snr_db: float
    active: bool
    baseline_progress: float
    baseline_complete: bool
    backend: str


class DSPEngine:
    """Stateful DSP pipeline independent of Qt and hardware ownership."""

    def __init__(self, baseline_seconds: float = 60.0) -> None:
        self._native = NativeAudioAdapter()
        self._filter = StatefulBandpass()
        self._baseline = BaselineAccumulator(required_seconds=float(baseline_seconds))
        self._noise_samples: list[float] = []
        self._noise_floor_db = -120.0
        self._lowcut = 80.0
        self._highcut = 8000.0
        self._gain = 1.0
        self._sensitivity = 1.0
        self._configured_rate = 0

    def configure(self, *, lowcut: float, highcut: float, gain: float, sensitivity: float) -> None:
        self._lowcut = float(lowcut)
        self._highcut = float(highcut)
        self._gain = float(gain)
        self._sensitivity = max(0.05, float(sensitivity))

    def reset_baseline(self) -> None:
        self._baseline.reset()
        self._noise_samples.clear()
        self._noise_floor_db = -120.0

    def process(self, samples: np.ndarray, sample_rate: int) -> DSPFrame:
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        if x.size == 0:
            raise ValueError("empty audio block")

        if self._configured_rate != int(sample_rate):
            self._filter.configure(sample_rate, self._lowcut, self._highcut, self._gain)
            self._configured_rate = int(sample_rate)
        else:
            self._filter.configure(sample_rate, self._lowcut, self._highcut, self._gain)

        filtered = self._filter.process(x) * self._gain
        filtered = np.clip(filtered, -1.0, 1.0).astype(np.float32, copy=False)

        metrics = self._native.analyze(filtered)
        rms_db = 20.0 * np.log10(max(metrics.rms, 1e-9))

        baseline_just_completed = self._baseline.add(filtered.size, sample_rate)
        if not self._baseline.completion_emitted:
            self._noise_samples.append(float(rms_db))
            if len(self._noise_samples) > 2048:
                self._noise_samples = self._noise_samples[-2048:]
            if self._noise_samples:
                self._noise_floor_db = float(np.median(self._noise_samples))

        window = np.hanning(filtered.size).astype(np.float32)
        spectrum = np.fft.rfft(filtered * window)
        magnitude = np.abs(spectrum)
        spectrum_db = 20.0 * np.log10(np.maximum(magnitude, 1e-9))
        frequencies = np.fft.rfftfreq(filtered.size, d=1.0 / float(sample_rate))

        if spectrum_db.size:
            peak_index = int(np.argmax(spectrum_db))
            peak_freq = float(frequencies[peak_index])
        else:
            peak_freq = 0.0

        snr_db = float(rms_db - self._noise_floor_db)
        active = bool(snr_db >= (6.0 / self._sensitivity))

        progress = min(
            1.0,
            self._baseline.valid_audio_seconds / max(self._baseline.required_seconds, 1e-6),
        )

        return DSPFrame(
            filtered=filtered,
            spectrum_db=spectrum_db.astype(np.float32, copy=False),
            frequencies_hz=frequencies.astype(np.float32, copy=False),
            sample_rate=int(sample_rate),
            rms=float(metrics.rms),
            peak=float(metrics.peak),
            peak_freq=peak_freq,
            noise_floor_db=float(self._noise_floor_db),
            snr_db=snr_db,
            active=active,
            baseline_progress=float(progress),
            baseline_complete=bool(self._baseline.completion_emitted or baseline_just_completed),
            backend=metrics.backend,
        )
