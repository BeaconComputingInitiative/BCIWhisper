# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bciwhisper.config.paths import AUDIO_LOG_DIR
from bciwhisper.config.runtime import RUNTIME


@dataclass(frozen=True)
class RecordingResult:
    raw_path: Path
    isolated_path: Path
    locked_seconds: float
    duration_seconds: float


class RecordingService:
    """Streaming RAW + ISOLATED recorder with the 15-second confirmed-lock rule."""

    def __init__(
        self,
        root: Path | str = AUDIO_LOG_DIR,
        *,
        keep_locked_seconds: float = RUNTIME.keep_locked_seconds,
        release_seconds: float = 2.0,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.keep_locked_seconds = float(keep_locked_seconds)
        self.release_seconds = float(release_seconds)
        self._raw = None
        self._isolated = None
        self._raw_path: Path | None = None
        self._isolated_path: Path | None = None
        self._sample_rate = 0
        self._started = 0.0
        self._locked_seconds = 0.0
        self._inactive_seconds = 0.0
        self.manual = False

    @property
    def recording(self) -> bool:
        return self._raw is not None and self._isolated is not None

    def _open(self, sample_rate: int) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        nonce = f"{time.time_ns() % 1_000_000_000:09d}"
        stem = f"bci-{stamp}-{nonce}"
        self._raw_path = self.root / f"{stem}_raw.wav"
        self._isolated_path = self.root / f"{stem}_isolated.wav"
        self._sample_rate = int(sample_rate)
        self._started = time.monotonic()
        self._locked_seconds = 0.0
        self._inactive_seconds = 0.0

        self._raw = wave.open(str(self._raw_path), "wb")
        self._isolated = wave.open(str(self._isolated_path), "wb")
        for writer in (self._raw, self._isolated):
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(self._sample_rate)

    def start_manual(self, sample_rate: int) -> None:
        if self.recording:
            raise RuntimeError("A recording is already active")
        if sample_rate <= 0:
            raise ValueError("A valid microphone sample rate is required")
        self._open(sample_rate)
        self.manual = True

    def stop_manual(self) -> RecordingResult | None:
        if not self.manual:
            return None
        return self.finish()

    @staticmethod
    def _pcm16(samples: np.ndarray) -> bytes:
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    def feed(
        self,
        *,
        raw: np.ndarray,
        isolated: np.ndarray,
        sample_rate: int,
        locked: bool,
    ) -> RecordingResult | None:
        raw = np.asarray(raw, dtype=np.float32).reshape(-1)
        isolated = np.asarray(isolated, dtype=np.float32).reshape(-1)
        if raw.size == 0 or isolated.size == 0:
            return None

        block_seconds = raw.size / float(sample_rate)

        if locked and not self.recording and not self.manual:
            self._open(sample_rate)

        if not self.recording:
            return None

        if int(sample_rate) != self._sample_rate:
            return self.finish(force_discard=True)

        self._raw.writeframesraw(self._pcm16(raw))
        self._isolated.writeframesraw(self._pcm16(isolated))

        if locked:
            self._locked_seconds += block_seconds
            self._inactive_seconds = 0.0
        else:
            self._inactive_seconds += block_seconds

        if not self.manual and self._inactive_seconds >= self.release_seconds:
            return self.finish()
        return None

    def finish(self, *, force_discard: bool = False) -> RecordingResult | None:
        if not self.recording:
            self.manual = False
            return None

        raw = self._raw
        isolated = self._isolated
        raw_path = self._raw_path
        isolated_path = self._isolated_path
        duration = max(0.0, time.monotonic() - self._started)

        self._raw = None
        self._isolated = None
        self._raw_path = None
        self._isolated_path = None

        for writer in (raw, isolated):
            try:
                writer.close()
            except Exception:
                pass

        keep = (not force_discard) and (self.manual or self._locked_seconds >= self.keep_locked_seconds)
        self.manual = False
        if not keep:
            for path in (raw_path, isolated_path):
                try:
                    if path is not None:
                        path.unlink(missing_ok=True)
                except Exception:
                    pass
            return None

        return RecordingResult(
            raw_path=Path(raw_path),
            isolated_path=Path(isolated_path),
            locked_seconds=float(self._locked_seconds),
            duration_seconds=float(duration),
        )

    def stop(self) -> RecordingResult | None:
        return self.finish()
