# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import threading
import wave
from pathlib import Path

import sounddevice as sd


class PlaybackService:
    """Output-only playback. Capture remains owned by the isolated input process."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def playing(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def play(self, path: Path | str) -> None:
        self.stop()
        target = Path(path)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True)
        self._thread.start()

    def _run(self, path: Path) -> None:
        with wave.open(str(path), "rb") as wf:
            if wf.getsampwidth() != 2:
                raise RuntimeError("playback supports 16-bit PCM WAV")
            with sd.RawOutputStream(
                samplerate=wf.getframerate(),
                channels=wf.getnchannels(),
                dtype="int16",
                blocksize=2048,
            ) as stream:
                while not self._stop.is_set():
                    data = wf.readframes(2048)
                    if not data:
                        break
                    stream.write(data)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None
