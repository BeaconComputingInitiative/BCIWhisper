# BEACON COMPUTING INITIATIVE
# BCIWhisper 59.5 — Secondary Isolated Microphone
# Developer Seal: CJB-DEV-2026
from __future__ import annotations
import threading
from bciwhisper.audio.service import AudioBlock, AudioService


class SecondaryMicrophone:
    """Second isolated PortAudio process; does not change primary capture."""
    def __init__(self, on_block, on_event=None):
        self._lock = threading.RLock()
        self._on_event = on_event or (lambda event: None)
        self._audio = AudioService(on_block=on_block, on_event=self._event)
        self._configured = False

    def _event(self, event):
        self._on_event({"source": "secondary", **event})

    def start(self, device_id: int, device_name: str = "") -> None:
        if device_id < 0 and not device_name:
            raise ValueError("Secondary microphone must be explicitly selected")
        with self._lock:
            if self._audio.running:
                raise RuntimeError("Secondary microphone already running")
            selection = {"mode": "manual", "device_id": int(device_id), "device_name": str(device_name)}
            self._audio.start(selection)
            self._configured = True

    def stop(self) -> None:
        with self._lock:
            self._audio.stop()
            self._configured = False

    @property
    def running(self) -> bool:
        return self._audio.running

    @property
    def session(self) -> dict:
        return self._audio.session

    @property
    def pid(self) -> int:
        return int(self._audio.pid or 0)
