# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from bci_audio.boundary import BCIAudioCaptureSupervisor
from bciwhisper.config.runtime import RUNTIME


@dataclass(frozen=True)
class AudioBlock:
    samples: np.ndarray
    sample_rate: int
    generation: int
    device_id: int
    device_name: str
    monotonic: float


class AudioService:
    """Owns the parent side of the isolated PortAudio process.

    This class contains no Qt code and never calls sounddevice directly.
    """

    def __init__(
        self,
        *,
        on_block: Callable[[AudioBlock], None],
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self._on_block = on_block
        self._on_event = on_event or (lambda event: None)
        self._supervisor = BCIAudioCaptureSupervisor(block_size=RUNTIME.block_size)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._session: dict = {}
        self._last_restart_reason = ""

    @property
    def running(self) -> bool:
        return self._running.is_set()

    @property
    def session(self) -> dict:
        return dict(self._session)

    @property
    def pid(self) -> int | None:
        return self._supervisor.pid

    def start(self, selection: dict | None = None) -> None:
        if self.running:
            return
        self._supervisor.start(selection)
        self._running.set()
        self._thread = threading.Thread(
            target=self._loop,
            name="BCI-AudioService",
            daemon=True,
        )
        self._thread.start()

    def select_device(self, *, device_id: int = -1, device_name: str = "", mode: str = "auto") -> None:
        self._supervisor.send(
            {
                "type": "select",
                "device_id": int(device_id),
                "device_name": str(device_name),
                "mode": str(mode),
            }
        )

    def request_probe(self) -> None:
        self._supervisor.send({"type": "probe"})

    def stop(self) -> None:
        self._running.clear()
        self._supervisor.stop()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._session = {}

    def _emit(self, event: dict) -> None:
        try:
            self._on_event(dict(event))
        except Exception:
            pass

    def _loop(self) -> None:
        while self.running:
            expired, reason = self._supervisor.watchdog_expired()
            if expired:
                self._last_restart_reason = reason
                self._emit({"type": "audio_restarting", "reason": reason})
                self._supervisor.restart(reason)
                time.sleep(0.05)
                continue

            polled = self._supervisor.poll(max_events=64, max_audio=64)

            for event in polled.events:
                kind = str(event.get("type", ""))
                if kind == "stream_opened":
                    self._session = dict(event)
                elif kind in {"stream_closed", "waiting", "open_error"}:
                    if kind != "waiting":
                        self._session = {}
                self._emit(event)

            session = dict(self._session)
            generation = int(session.get("generation", 0) or 0)
            sample_rate = int(session.get("sample_rate", 48000) or 48000)
            device_id = int(session.get("device_id", -1) or -1)
            device_name = str(session.get("device_name", "") or "")

            for packet in polled.audio:
                if int(packet.get("generation", 0) or 0) != generation:
                    continue
                pcm = packet.get("pcm", b"")
                frames = int(packet.get("frames", 0) or 0)
                if not pcm or frames <= 0:
                    continue
                data = np.frombuffer(pcm, dtype=np.float32)
                if data.size < frames:
                    continue
                samples = np.ascontiguousarray(data[:frames], dtype=np.float32)
                try:
                    self._on_block(
                        AudioBlock(
                            samples=samples,
                            sample_rate=sample_rate,
                            generation=generation,
                            device_id=device_id,
                            device_name=device_name,
                            monotonic=time.monotonic(),
                        )
                    )
                except Exception as exc:
                    self._emit({"type": "audio_consumer_error", "message": str(exc)})

            time.sleep(0.004)
