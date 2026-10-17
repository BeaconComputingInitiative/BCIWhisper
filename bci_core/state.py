#!/usr/bin/env python3
"""Explicit BCIWhisper application and audio-engine state machines.

This module owns control-plane state only.  It deliberately imports neither
Qt nor PortAudio/sounddevice so UI and hardware layers cannot acquire each
other through this boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Deque, Optional


class BCIApplicationPhase(str, Enum):
    STARTING = "starting"
    WAITING_FOR_AUDIO = "waiting_for_audio"
    CALIBRATING = "calibrating"
    READY = "ready"
    RECOVERING = "recovering"
    ERROR = "error"
    STOPPING = "stopping"


class BCIAudioPhase(str, Enum):
    OFFLINE = "offline"
    WAITING_SESSION = "waiting_session"
    WAITING_FRAMES = "waiting_frames"
    CALIBRATING = "calibrating"
    READY = "ready"
    RECOVERING = "recovering"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass(frozen=True)
class BCIStateTransition:
    monotonic: float
    old_state: str
    new_state: str
    reason: str


class _TransitionHistory:
    def __init__(self, maxlen: int = 96) -> None:
        self._history: Deque[BCIStateTransition] = deque(maxlen=maxlen)

    def append(self, old_state: str, new_state: str, reason: str) -> None:
        self._history.append(
            BCIStateTransition(
                monotonic=time.monotonic(),
                old_state=str(old_state),
                new_state=str(new_state),
                reason=str(reason or ""),
            )
        )

    def snapshot(self) -> tuple[BCIStateTransition, ...]:
        return tuple(self._history)


class BCIApplicationStateMachine:
    """Single authority for UI/application lifecycle state.

    The main display is a one-way latch.  Hardware loss after the analyzer has
    appeared moves the application into RECOVERING but never back into boot.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = BCIApplicationPhase.STARTING
        self._main_display_entered = False
        self._reason = "application created"
        self._history = _TransitionHistory()
        self._history.append("none", self._phase.value, self._reason)

    def _transition(
        self,
        phase: BCIApplicationPhase,
        reason: str,
        *,
        enter_main: Optional[bool] = None,
    ) -> None:
        with self._lock:
            old = self._phase
            if enter_main is True:
                self._main_display_entered = True
            elif enter_main is False and not self._main_display_entered:
                self._main_display_entered = False
            self._phase = phase
            self._reason = str(reason or "")
            if old != phase or self._history.snapshot() == ():
                self._history.append(old.value, phase.value, self._reason)

    def mark_waiting_for_audio(self, reason: str = "waiting for audio") -> None:
        with self._lock:
            already_main = self._main_display_entered
        self._transition(
            BCIApplicationPhase.RECOVERING if already_main else BCIApplicationPhase.WAITING_FOR_AUDIO,
            reason,
            enter_main=None,
        )

    def mark_calibrating(self, reason: str = "live audio confirmed") -> None:
        self._transition(BCIApplicationPhase.CALIBRATING, reason, enter_main=True)

    def mark_ready(self, reason: str = "baseline complete") -> None:
        self._transition(BCIApplicationPhase.READY, reason, enter_main=True)

    def mark_recovering(self, reason: str = "audio recovery") -> None:
        self._transition(BCIApplicationPhase.RECOVERING, reason, enter_main=None)

    def mark_error(self, reason: str = "application error") -> None:
        self._transition(BCIApplicationPhase.ERROR, reason, enter_main=None)

    def mark_stopping(self, reason: str = "application stopping") -> None:
        self._transition(BCIApplicationPhase.STOPPING, reason, enter_main=None)

    @property
    def phase(self) -> BCIApplicationPhase:
        with self._lock:
            return self._phase

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def main_display_entered(self) -> bool:
        with self._lock:
            return bool(self._main_display_entered)

    @property
    def boot_in_progress(self) -> bool:
        with self._lock:
            return not self._main_display_entered

    @property
    def analysis_started(self) -> bool:
        with self._lock:
            return bool(self._main_display_entered)

    def history(self) -> tuple[BCIStateTransition, ...]:
        with self._lock:
            return self._history.snapshot()


class BCIAudioRuntimeStateMachine:
    """Atomic owner for DSP-side audio lifecycle flags.

    Compatibility properties remain available in AudioProcessorThread, but all
    three legacy flags are stored here so they cannot independently drift into
    contradictory copies spread around the worker.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = BCIAudioPhase.WAITING_SESSION
        self._calibrated = False
        self._full_baseline_needed = True
        self._device_changed = False
        self._reason = "audio worker created"
        self._history = _TransitionHistory()
        self._history.append("none", self._phase.value, self._reason)

    def _set_phase(self, phase: BCIAudioPhase, reason: str) -> None:
        old = self._phase
        self._phase = phase
        self._reason = str(reason or "")
        if old != phase:
            self._history.append(old.value, phase.value, self._reason)

    def mark_session_changed(self, reason: str = "hardware session changed") -> None:
        with self._lock:
            self._device_changed = True
            self._full_baseline_needed = True
            self._calibrated = False
            self._set_phase(BCIAudioPhase.WAITING_FRAMES, reason)

    def mark_capture_open(self, reason: str = "capture session opened") -> None:
        with self._lock:
            self._device_changed = False
            if self._calibrated and not self._full_baseline_needed:
                self._set_phase(BCIAudioPhase.READY, reason)
            else:
                self._set_phase(BCIAudioPhase.WAITING_FRAMES, reason)

    def mark_first_frames(self, reason: str = "live frames confirmed") -> None:
        with self._lock:
            if self._calibrated and not self._full_baseline_needed:
                self._set_phase(BCIAudioPhase.READY, reason)
            else:
                self._set_phase(BCIAudioPhase.CALIBRATING, reason)

    def mark_baseline_complete(self, reason: str = "room baseline complete") -> None:
        with self._lock:
            self._calibrated = True
            self._full_baseline_needed = False
            self._device_changed = False
            self._set_phase(BCIAudioPhase.READY, reason)

    def mark_filter_invalidated(self, reason: str = "filter parameters changed") -> None:
        with self._lock:
            self._calibrated = False
            if self._phase == BCIAudioPhase.READY:
                self._set_phase(BCIAudioPhase.CALIBRATING, reason)

    def mark_recovering(self, reason: str = "capture recovery") -> None:
        with self._lock:
            self._calibrated = False
            self._full_baseline_needed = True
            self._device_changed = True
            self._set_phase(BCIAudioPhase.RECOVERING, reason)

    def mark_error(self, reason: str = "audio error") -> None:
        with self._lock:
            self._set_phase(BCIAudioPhase.ERROR, reason)

    def mark_stopping(self, reason: str = "audio worker stopping") -> None:
        with self._lock:
            self._device_changed = True
            self._set_phase(BCIAudioPhase.STOPPING, reason)

    @property
    def phase(self) -> BCIAudioPhase:
        with self._lock:
            return self._phase

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def calibrated(self) -> bool:
        with self._lock:
            return bool(self._calibrated)

    @calibrated.setter
    def calibrated(self, value: bool) -> None:
        with self._lock:
            self._calibrated = bool(value)
            if value:
                self._set_phase(BCIAudioPhase.READY, "compat calibrated=true")
            elif self._phase == BCIAudioPhase.READY:
                self._set_phase(BCIAudioPhase.CALIBRATING, "compat calibrated=false")

    @property
    def full_baseline_needed(self) -> bool:
        with self._lock:
            return bool(self._full_baseline_needed)

    @full_baseline_needed.setter
    def full_baseline_needed(self, value: bool) -> None:
        with self._lock:
            self._full_baseline_needed = bool(value)

    @property
    def device_changed(self) -> bool:
        with self._lock:
            return bool(self._device_changed)

    @device_changed.setter
    def device_changed(self, value: bool) -> None:
        with self._lock:
            self._device_changed = bool(value)

    def history(self) -> tuple[BCIStateTransition, ...]:
        with self._lock:
            return self._history.snapshot()
