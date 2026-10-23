# BEACON COMPUTING INITIATIVE
# BCIWhisper 59.6 — Timestamp-Aligned Separate Track Recorder
# Developer Seal: CJB-DEV-2026
from __future__ import annotations

import json
import math
import threading
import time
import wave
from pathlib import Path
import numpy as np


class MultitrackRecorder:
    """Two mono PCM16 WAV files sharing a monotonic timeline.

    Timestamp alignment is approximate; independent hardware clocks can drift.
    Discontinuities are zero-padded. No resampling or sample-accurate sync claimed.
    """
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = threading.RLock()
        self._writers = {}
        self._frames = {}
        self._paths = {}
        self._rate = 0
        self._origin = 0.0
        self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, sample_rate: int) -> None:
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        with self._lock:
            if self._active:
                raise RuntimeError("multitrack take already active")
            self.root.mkdir(parents=True, exist_ok=True)
            stem = f"bci-multitrack-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}"
            self._paths = {track: self.root / f"{stem}-{track}.wav" for track in ("primary", "secondary")}
            self._writers = {}
            try:
                for track, path in self._paths.items():
                    writer = wave.open(str(path), "wb")
                    self._writers[track] = writer
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(sample_rate)
            except Exception:
                for writer in self._writers.values():
                    writer.close()
                raise
            self._frames = {"primary": 0, "secondary": 0}
            self._rate = int(sample_rate)
            self._origin = time.monotonic()
            self._active = True

    def feed(self, track: str, samples: np.ndarray, sample_rate: int, timestamp: float) -> None:
        with self._lock:
            if not self._active:
                return
            if track not in self._writers:
                raise ValueError("unknown track")
            if sample_rate != self._rate:
                raise ValueError("track sample rate differs from session (resampling unavailable)")
            audio = np.asarray(samples, dtype=np.float32).reshape(-1)
            if not len(audio):
                return
            # AudioBlock.monotonic is measured at block delivery, approximately block end.
            start_frame = max(0, round((timestamp - self._origin) * self._rate) - len(audio))
            written = self._frames[track]
            if start_frame > written:
                gap = start_frame - written
                silence = b"\x00\x00" * min(gap, 48000)
                while gap:
                    frames = min(gap, 48000)
                    self._writers[track].writeframesraw(silence[:2 * frames])
                    gap -= frames
                written = start_frame
            # Never rewind already written audio. Trim timestamp-overlapping frames.
            trim = max(0, written - start_frame)
            if trim >= len(audio):
                return
            audio = audio[trim:]
            pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
            self._writers[track].writeframesraw(pcm)
            self._frames[track] = written + len(audio)

    def stop(self) -> dict:
        with self._lock:
            if not self._active:
                return {}
            self._active = False
            max_frames = max(self._frames.values())
            for track, writer in self._writers.items():
                gap = max_frames - self._frames[track]
                while gap:
                    n = min(gap, 48000)
                    writer.writeframesraw(b"\x00\x00" * n)
                    gap -= n
                writer.close()
            manifest = {
                "format": "bci-multitrack-v1",
                "sample_rate": self._rate,
                "frames": max_frames,
                "tracks": {k: str(v) for k, v in self._paths.items()},
                "synchronization": "approximate delivery-monotonic; no hardware-clock correction",
            }
            manifest_path = self._paths["primary"].with_suffix(".json")
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            manifest["manifest"] = str(manifest_path)
            self._writers = {}
            return manifest
