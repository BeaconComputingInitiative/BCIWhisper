#!/usr/bin/env python3
# ==============================================================================
# DEVELOPER SEAL: CJB-DEV-2026 | Chance Joaquin Boone
# ==============================================================================

import sys
import re
import os
import time
import wave
import threading
import multiprocessing as _bci_mp
import queue
import logging
import traceback
import functools
import subprocess
import shutil
import struct
import sqlite3
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from datetime import datetime
from collections import deque
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod
from typing import Any, Optional, Callable

import numpy as np
import sounddevice as sd
from scipy.signal import (
    butter,
    sosfilt,
    sosfilt_zi,
    sosfiltfilt,
    stft,
    istft,
    iirnotch,
    filtfilt,
    resample_poly,
)
from PyQt6 import QtCore, QtGui, QtWidgets
from bci_audio.boundary import (
    BCIAudioCaptureSupervisor,
    BOUNDARY_PROTOCOL_VERSION,
)
from bci_core.state import (
    BCIApplicationStateMachine,
    BCIAudioRuntimeStateMachine,
)

# ==============================================================================
# Configuration
# ==============================================================================

BLOCK_SIZE = 2048

# PortAudio capture is callback-driven and buffered independently from DSP.
# 128 blocks is about 5.5 seconds at 48 kHz / 2048 samples per block.
CAPTURE_QUEUE_BLOCKS = 128
CAPTURE_RING_FRAMES = CAPTURE_QUEUE_BLOCKS * BLOCK_SIZE
CAPTURE_QUEUE_TIMEOUT = 0.50
CAPTURE_STATUS_REPORT_SECONDS = 2.0
# Script 57.5: PortAudio input ownership lives behind a process boundary.
# The DSP worker still verifies that real frames arrive after a hardware
# session is announced; a native open/probe hang is supervised separately.
CAPTURE_FIRST_BLOCK_TIMEOUT_SECONDS = 4.0
CAPTURE_STALL_TIMEOUT_SECONDS = 4.0
AUDIO_BOUNDARY_WATCHDOG_SECONDS = 7.0
CALIBRATION_HEARTBEAT_SECONDS = 5.0

APP_DIR = Path(__file__).resolve().parent


def _bci_default_data_root():
    """
    Resolve writable BCIWhisper application data.

    BCI_DATA_DIR overrides automatic path selection.

    Source mode preserves the historical project-local layout.
    Frozen/package mode uses the platform-native per-user data root.
    """
    override = os.environ.get("BCI_DATA_DIR", "").strip()

    if override:
        return Path(override).expanduser().resolve()

    if not getattr(sys, "frozen", False):
        return APP_DIR

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")

        if base:
            return (
                Path(base)
                / "BCIWhisper"
            ).expanduser().resolve()

        return (
            Path.home()
            / "AppData"
            / "Local"
            / "BCIWhisper"
        ).resolve()

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "BCIWhisper"
        ).resolve()

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()

    if xdg_data_home:
        return (
            Path(xdg_data_home).expanduser()
            / "BCIWhisper"
        ).resolve()

    return (
        Path.home()
        / ".local"
        / "share"
        / "BCIWhisper"
    ).resolve()


BASE_DIR = _bci_default_data_root()
BASE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = str(BASE_DIR / "bci_audio_logs")
TELEMETRY_LOG = str(BASE_DIR / "bci_telemetry.log")
TELEMETRY_DB = str(BASE_DIR / "bci_telemetry.db")
SHORT_EVENT_LOG = str(BASE_DIR / "bci_short_events.jsonl")
ERROR_LOG = str(BASE_DIR / "bci_error.log")
MASTER_PREVIEW_DIR = BASE_DIR / ".bci_master_previews"
MASTER_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
MASTER_DEFAULT_PREVIEW_NAME = "bci_master_preview.wav"

# Go Live is explicitly opt-in. The service binds only after the user presses
# GO LIVE and stops immediately when they press STOP LIVE or exit BCIWhisper.
LIVE_STREAM_HOST = os.environ.get(
    "BCI_LIVE_HOST",
    "0.0.0.0",
)
LIVE_STREAM_PORT = int(
    os.environ.get(
        "BCI_LIVE_PORT",
        "8765",
    )
)
LIVE_STREAM_BITRATE_KBPS = int(
    os.environ.get(
        "BCI_LIVE_BITRATE_KBPS",
        "96",
    )
)
LIVE_STREAM_PUBLIC_URL = os.environ.get(
    "BCI_LIVE_PUBLIC_URL",
    "",
).strip()

BCI_BUILD = "2026.10.17-r6.34.10"
BCI_SCRIPT_REVISION = "57.10"

# BCI project versioning is based on materially produced/rewritten scripts:
#   scripts 1-10  -> v1.0
#   scripts 11-20 -> v2.0
#   scripts 21-30 -> v3.0
#   scripts 31-40 -> v4.0
#   scripts 41-50 -> v5.0
#   scripts 51-60 -> v6.0
# This file is script 57 in the BCIWhisper project thread.
BCI_SCRIPT_TALLY = 57
BCI_PROJECT_VERSION = "v6.0"

# Keep the public project version separate from the engineering build ID.
BCI_VERSION = BCI_PROJECT_VERSION


# =============================================================================
# BCI UNIVERSAL AUDIO ROUTING CONTRACT — Script 52
# =============================================================================
# The DSP core consumes normalized capture PCM. OS/device discovery and routing
# are isolated behind this contract so Linux, Windows and macOS can present
# different native backends without changing the signal-processing pipeline.

from dataclasses import dataclass as _bci_dataclass
from typing import Optional as _BCIOptional
import platform as _bci_platform

@_bci_dataclass(frozen=True)
class BCIAudioEndpoint:
    index: int
    name: str
    direction: str
    backend: str
    channels: int
    default_sample_rate: int
    physical: bool
    virtual: bool
    monitor: bool
    loopback: bool
    stable_hardware_id: _BCIOptional[str] = None

    @property
    def capture_safe(self) -> bool:
        return (
            self.direction == "input"
            and self.channels > 0
            and not self.monitor
            and not self.loopback
        )


class BCIUniversalAudioRouter:
    """OS-neutral device discovery, classification, scoring and safe selection."""

    REJECT_CAPTURE_TOKENS = (
        ".monitor", " monitor", "loopback", "stereo mix",
        "what u hear", "what you hear", "upmix", "downmix",
        "lavrate", "samplerate", "speexrate", "bluez_output.",
    )
    VIRTUAL_TOKENS = (
        "virtual", "null", "dummy", "loopback", ".monitor",
        "stereo mix", "what u hear", "what you hear",
    )
    PREFERRED_TOKENS = (
        "bci", "beacon", "usb", "microphone", "mic", "audio",
    )

    def __init__(self):
        self.system = _bci_platform.system().lower()
        self.backend_family = {
            "linux": "pipewire/pulseaudio/alsa",
            "windows": "wasapi",
            "darwin": "coreaudio",
        }.get(self.system, "portaudio")

    @staticmethod
    def _text(value):
        return str(value or "").strip()

    def classify(self, index, device, hostapi_name=""):
        name = self._text(device.get("name"))
        lower = name.lower()
        max_in = int(device.get("max_input_channels", 0) or 0)
        max_out = int(device.get("max_output_channels", 0) or 0)
        if max_in > 0:
            direction = "input"
            channels = max_in
        elif max_out > 0:
            direction = "output"
            channels = max_out
        else:
            direction = "unknown"
            channels = 0

        monitor = ".monitor" in lower or lower.endswith(" monitor")
        loopback = any(
            token in lower
            for token in ("loopback", "stereo mix", "what u hear", "what you hear")
        )
        virtual = any(token in lower for token in self.VIRTUAL_TOKENS)
        physical = direction in ("input", "output") and not virtual

        backend = self._text(hostapi_name) or self.backend_family
        stable = f"{self.system}:{backend}:{name}".lower()

        return BCIAudioEndpoint(
            index=int(index),
            name=name,
            direction=direction,
            backend=backend,
            channels=channels,
            default_sample_rate=int(
                float(device.get("default_samplerate", 0) or 0)
            ),
            physical=physical,
            virtual=virtual,
            monitor=monitor,
            loopback=loopback,
            stable_hardware_id=stable,
        )

    def enumerate_endpoints(self, devices=None, hostapis=None):
        """Classify an already-published hardware snapshot.

        Script 57.5 intentionally forbids this GUI/DSP-side contract from
        enumerating PortAudio on its own. Hardware discovery belongs to the
        isolated bci_audio.boundary process.
        """
        if devices is None:
            return []
        devices = list(devices or [])
        hostapis = list(hostapis or [])

        result = []
        for index, device in enumerate(devices):
            hostapi_name = ""
            try:
                hostapi_index = int(device.get("hostapi", -1))
                if 0 <= hostapi_index < len(hostapis):
                    hostapi_name = self._text(hostapis[hostapi_index].get("name"))
            except Exception:
                pass
            result.append(self.classify(index, device, hostapi_name))
        return result

    def capture_score(self, endpoint, preferred_hardware_id=None):
        if not endpoint.capture_safe:
            return -100000

        lower = endpoint.name.lower()
        if any(token in lower for token in self.REJECT_CAPTURE_TOKENS):
            return -100000

        score = 0
        if endpoint.physical:
            score += 1000
        if not endpoint.virtual:
            score += 250
        if endpoint.channels == 1:
            score += 100
        elif endpoint.channels > 1:
            score += 50
        if endpoint.default_sample_rate in (44100, 48000):
            score += 50
        if any(token in lower for token in self.PREFERRED_TOKENS):
            score += 25

        if (
            preferred_hardware_id
            and endpoint.stable_hardware_id == preferred_hardware_id
        ):
            score += 10000
        return score

    def choose_capture(self, preferred_hardware_id=None):
        endpoints = self.enumerate_endpoints()
        candidates = [
            endpoint
            for endpoint in endpoints
            if self.capture_score(endpoint, preferred_hardware_id) > -100000
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda endpoint: self.capture_score(
                endpoint,
                preferred_hardware_id,
            ),
        )


class BCIBroadcastConditioner:
    """Independent broadcast level policy; never inherits monitor gain."""

    def __init__(self, ceiling=0.89):
        self.ceiling = float(max(0.10, min(0.98, ceiling)))

    def process(self, block):
        samples = np.asarray(block, dtype=np.float32).reshape(-1).copy()
        if not samples.size:
            return samples

        samples = np.nan_to_num(
            samples,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        peak = float(np.max(np.abs(samples)))
        if peak > self.ceiling and peak > 0.0:
            samples *= self.ceiling / peak
        return samples.astype(np.float32, copy=False)


BCI_AUDIO_ROUTER = BCIUniversalAudioRouter()
BCI_BROADCAST_CONDITIONER = BCIBroadcastConditioner()
BCI_VERSION_TEXT = (
    f"BCIWhisper // {BCI_PROJECT_VERSION} "
    f"// Script {BCI_SCRIPT_REVISION} "
    f"// Build {BCI_BUILD}"
)

BCI_LEAD_DEVELOPER = "Chance Joaquin Boone"

# Disk-space guard. A new clip is refused below MIN_FREE_DISK_MB, and a clip in
# progress is closed cleanly if free space falls below half of it.
MIN_FREE_DISK_MB = 500.0

# Optional retention for bci_event_*.wav. 0 keeps everything (default).
RETENTION_DAYS = 0

# Keep in-progress WAV headers valid on disk in case of a crash or power loss.
WAV_CHECKPOINT_SECONDS = 2.0

# Smoothing for locked-band presence detection.
LOCK_PRESENCE_SMOOTHING = 0.5

# Script 54 presentation scheduler. DSP/capture stay full-rate; only visual
# animation and producer-to-GUI delivery are decimated. Twenty visual frames
# per second is smooth for spectrum motion while materially reducing QPainter
# and QGraphicsProxyWidget load on scaled Wayland desktops.
UI_FRAME_INTERVAL_MS = 50

# Normal analyzer packets are presentation data, not control data. Keeping them
# near 12.5 Hz avoids pushing every 2048-sample DSP block through the Qt main
# thread while the spectrum widget interpolates smoothly between targets.
AUDIO_GUI_UPDATE_INTERVAL_MS = 80

# Calibration uses a deliberately lower presentation cadence. Audio capture,
# RMS accounting, and baseline timing remain full-rate; only calibration
# visualization is reduced to avoid unnecessary Qt repaint/layout work.
CALIBRATION_GUI_UPDATE_INTERVAL_MS = 125

# Script 56 boot-progress clock. The progress bar owns a lightweight visual
# timer so the 60-second baseline visibly advances even when spectrum packets
# are decimated or Qt delivery is briefly busy. The audio worker remains the
# sole authority for declaring the baseline complete.
BOOT_PROGRESS_INTERVAL_MS = 100

# The isolated panel is purely cosmetic while no signal is locked. Slow its
# waiting animation instead of continuously repainting a second spectrum view.
SPECTRUM_IDLE_INTERVAL_MS = 100

# The full-window aura is decorative. Ten updates per second preserve the pulse
# without forcing a top-level repaint every 50 ms.
AURA_FRAME_INTERVAL_MS = 100

# Poll audio topology/default-route changes so AUTO follows Ubuntu/PipeWire and
# newly connected Bluetooth headsets or USB camera microphones appear without
# restarting the application.
DEVICE_SYNC_INTERVAL_MS = 2000

# Typography system.
# DejaVu ships with most Linux desktop distributions and gives BCI a cleaner
# industrial UI than using monospace for every control.
UI_FONT_FAMILY = "DejaVu Sans"
UI_BRAND_FONT_FAMILY = "DejaVu Sans Condensed"
UI_MONO_FONT_FAMILY = "DejaVu Sans Mono"

LOGO_ASSET = APP_DIR / "BCIWhisper_logo.jpeg"
ROOM_PROFILE_PATH = BASE_DIR / "bci_room_profile.npz"

# Local transcription configuration.
TRANSCRIPTION_AUTO = False

# Automatic offline enhancement of completed clips. RAW stays unchanged.
# The first-pass isolated WAV is analyzed, then rebuilt atomically from RAW.
POSTPROCESS_AUTO = False

# Reference analysis.
POSTPROCESS_ANALYSIS_WINDOWS = 48
POSTPROCESS_ANALYSIS_FRAMES = 8192
POSTPROCESS_MIN_BANDWIDTH_HZ = 450.0
POSTPROCESS_BAND_MARGIN_HZ = 140.0

# Chunked STFT reconstruction. This bounds memory even for long recordings.
POSTPROCESS_CHUNK_SECONDS = 8.0
POSTPROCESS_CHUNK_OVERLAP_SECONDS = 0.25
POSTPROCESS_STFT_NFFT = 2048
POSTPROCESS_STFT_HOP = 512
POSTPROCESS_NOISE_PERCENTILE = 18.0
POSTPROCESS_ROOM_PROFILE_BLEND = 0.42
POSTPROCESS_WIENER_OVERSUBTRACT = 1.15
POSTPROCESS_SPECTRAL_FLOOR = 0.08
POSTPROCESS_HARMONIC_FLOOR = 0.72

# Conservative dynamics.
POSTPROCESS_GATE_FRAME = 1024
POSTPROCESS_GATE_FLOOR = 0.14
POSTPROCESS_TARGET_RMS_DBFS = -16.0
POSTPROCESS_MAX_GAIN_DB = 24.0
POSTPROCESS_PEAK_LIMIT = 0.965

# Final mastering target. -14 LUFS is intentionally more forward/loud than the
# previous -16 LUFS target while the true-peak ceiling prevents clipping.
POSTPROCESS_TARGET_LUFS = -14.0
POSTPROCESS_TRUE_PEAK_DBTP = -1.0
POSTPROCESS_LRA = 9.0

# Intelligibility / clarity mastering. Amounts are automatically reduced when
# the measured SNR is poor so hiss is not boosted along with the foreground.
POSTPROCESS_MUD_LOW_HZ = 180.0
POSTPROCESS_MUD_HIGH_HZ = 500.0
POSTPROCESS_MUD_CUT_DB = 2.4

POSTPROCESS_PRESENCE_LOW_HZ = 1400.0
POSTPROCESS_PRESENCE_HIGH_HZ = 4300.0
POSTPROCESS_PRESENCE_BOOST_DB = 3.2

POSTPROCESS_AIR_LOW_HZ = 4800.0
POSTPROCESS_AIR_HIGH_HZ = 8500.0
POSTPROCESS_AIR_BOOST_DB = 1.4

POSTPROCESS_DEESS_LOW_HZ = 4800.0
POSTPROCESS_DEESS_HIGH_HZ = 9000.0
POSTPROCESS_DEESS_MAX_DB = 3.0
POSTPROCESS_DEESS_RATIO_TRIGGER = 0.28

# Quality-control tolerances. The original isolated WAV is preserved unless the
# enhanced candidate passes these sanity checks.
POSTPROCESS_MAX_CLIP_FRACTION = 0.0005
POSTPROCESS_MAX_SNR_REGRESSION_DB = 1.0
POSTPROCESS_MAX_SPEECH_BAND_REGRESSION = 0.15

# Local speech-to-text configuration. OpenAI Whisper is the primary backend.
# Keep Faster-Whisper as a local fallback because its CTranslate2 model format
# is different from the .pt checkpoints used by the OpenAI Whisper package.
LEGACY_WHISPER_MODEL = os.environ.get(
    "BCI_WHISPER_MODEL",
    "",
).strip()
OPENAI_WHISPER_MODEL = os.environ.get(
    "BCI_OPENAI_WHISPER_MODEL",
    "small.en",
).strip() or "small.en"
OPENAI_WHISPER_DOWNLOAD_ROOT = os.environ.get(
    "BCI_OPENAI_WHISPER_DOWNLOAD_ROOT",
    str(Path.home() / "Audio" / "models" / "openai-whisper"),
).strip()
OPENAI_WHISPER_DEVICE = os.environ.get(
    "BCI_OPENAI_WHISPER_DEVICE",
    "cpu",
).strip() or "cpu"
FASTER_WHISPER_MODEL = os.environ.get(
    "BCI_FASTER_WHISPER_MODEL",
    LEGACY_WHISPER_MODEL or str(
        BASE_DIR / "models" / "faster-whisper-small.en"
    ),
).strip()
TRANSCRIPTION_LANGUAGE = os.environ.get(
    "BCI_WHISPER_LANGUAGE",
    "en",
)
WHISPER_CPP_MODEL = os.environ.get(
    "BCI_WHISPER_CPP_MODEL",
    "",
)

DEFAULT_LOWCUT = 120.0
DEFAULT_HIGHCUT = 8000.0
DEFAULT_GAIN = 4.0
DEFAULT_SENSITIVITY = 1.2

STARTUP_CALIBRATION_SECONDS = 60.0
RECALIBRATION_SECONDS = 5.0
BASELINE_SPECTRUM_SAMPLE_STRIDE = 3
BASELINE_SPECTRUM_PERCENTILE = 40.0
BASELINE_MIN_VALID_SECONDS = 10.0
PREBUFFER_SECONDS = 1.0
RELEASE_SECONDS = 0.75
MIN_TRIGGER_BLOCKS = 2

# Completed recordings are only retained when BCI has been positively locked
# onto the signal for at least this long. Shorter candidates are deleted and
# replaced by a lightweight detection-history record.
MIN_SAVED_LOCK_SECONDS = 15.0

# Once a signal is locked, recording follows the LOCK rather than the original
# broad trigger. Speech pauses and brief level dips therefore do not end clips.
LOCK_RELEASE_SECONDS = 5.0
LOCK_PRESENCE_DB = 3.0

# 0 means no artificial clip-length cutoff. Audio is streamed to disk while
# recording, so a long lock does not accumulate the entire clip in RAM.
MAX_CLIP_SECONDS = 0.0

# Intelligent post-trigger spectral lock.
# The broad Lowcut/Highcut band is used for detection. Once an event is
# confirmed, the processed recording adaptively follows the spectral region
# containing most of that event's energy.
LOCK_UPDATE_SECONDS = 0.20
LOCK_ENERGY_LOW_QUANTILE = 0.12
LOCK_ENERGY_HIGH_QUANTILE = 0.92
LOCK_MIN_BANDWIDTH_HZ = 700.0
LOCK_MARGIN_HZ = 150.0
LOCK_SMOOTHING = 0.35
LOCK_MAX_STEP_HZ = 500.0
LOCK_RETUNE_THRESHOLD_HZ = 80.0

# Lightweight speech/music classification window.
CLASSIFIER_HISTORY_SECONDS = 1.5
CLASSIFIER_MIN_FRAMES = 8

os.makedirs(LOG_DIR, exist_ok=True)


# ==============================================================================
# Error handling / diagnostics
# ==============================================================================

def setup_logging():
    logger = logging.getLogger("BCI")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    try:
        file_handler = RotatingFileHandler(
            ERROR_LOG,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:
        print(f"[BCI] Could not open {ERROR_LOG}: {exc}")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


LOGGER = setup_logging()


def report_exception(context, exc):
    LOGGER.error(
        "%s: %s",
        context,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def report_warning(context, message):
    LOGGER.warning("%s: %s", context, message)


def guarded_slot(context):
    """Keep one GUI callback failure from tearing down the Qt event loop."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                report_exception(context, exc)

                owner = args[0] if args else None
                if owner is not None and hasattr(owner, "show_runtime_error"):
                    try:
                        owner.show_runtime_error(context, str(exc))
                    except Exception as banner_exc:
                        report_exception(
                            "runtime error banner",
                            banner_exc,
                        )

                return None

        return wrapper

    return decorator


class _ErrorBridge(QtCore.QObject):
    """
    Lives on the GUI thread. Worker-thread errors are handed to this object
    through a queued Qt signal before a dialog is created.
    """

    show_error = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._last_shown = float("-inf")
        self.show_error.connect(self._show)

    @QtCore.pyqtSlot(str)
    def _show(self, text):
        now = time.monotonic()

        if now - self._last_shown < 3.0:
            return

        self._last_shown = now

        try:
            QtWidgets.QMessageBox.critical(
                None,
                "BCI Error",
                text,
            )
        except Exception:
            pass


_ERROR_BRIDGE = None


def install_error_bridge():
    global _ERROR_BRIDGE

    if _ERROR_BRIDGE is None:
        _ERROR_BRIDGE = _ErrorBridge()


def prune_old_recordings():
    """
    Delete recording WAVs older than RETENTION_DAYS. Retention is disabled when
    RETENTION_DAYS <= 0. Matching transcript sidecars are removed as well.
    """
    if RETENTION_DAYS <= 0:
        return 0

    cutoff = time.time() - RETENTION_DAYS * 86400.0
    removed = 0

    for path in Path(LOG_DIR).glob("bci_event_*.wav"):
        try:
            if path.stat().st_mtime >= cutoff:
                continue

            sidecars = [
                path.with_suffix(".txt"),
                path.with_suffix(
                    ".enhancement.json"
                ),
            ]

            path.unlink()
            removed += 1

            for sidecar in sidecars:
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except Exception as exc:
                        report_warning(
                            f"retention sidecar: {sidecar.name}",
                            str(exc),
                        )

        except Exception as exc:
            report_warning(
                f"retention: {path.name}",
                str(exc),
            )

    if removed:
        LOGGER.info(
            "Retention removed %d recording(s) older than %d day(s)",
            removed,
            RETENTION_DAYS,
        )

    return removed

def install_global_exception_hook():
    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(
                exc_type,
                exc_value,
                exc_tb,
            )
            return

        LOGGER.critical(
            "Unhandled application exception",
            exc_info=(
                exc_type,
                exc_value,
                exc_tb,
            ),
        )

        try:
            traceback.print_exception(
                exc_type,
                exc_value,
                exc_tb,
            )
        except Exception:
            pass

        bridge = _ERROR_BRIDGE
        if bridge is not None:
            try:
                bridge.show_error.emit(
                    "An unexpected error occurred. "
                    f"Details were written to {ERROR_LOG}.\\n\\n"
                    f"{exc_value}"
                )
            except Exception:
                pass

    sys.excepthook = hook

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return

        hook(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )

    threading.excepthook = thread_hook


# ==============================================================================
# DSP helpers
# ==============================================================================

def clamp_band(lowcut, highcut, fs):
    nyquist = fs * 0.5
    lowcut = max(20.0, float(lowcut))
    highcut = min(float(highcut), nyquist * 0.98)

    if lowcut >= highcut:
        lowcut = max(20.0, highcut - 100.0)

    if lowcut >= highcut:
        raise ValueError(
            f"Invalid filter band: lowcut={lowcut}, highcut={highcut}, fs={fs}"
        )

    return lowcut, highcut


def design_bandpass(lowcut, highcut, fs, order=4):
    lowcut, highcut = clamp_band(lowcut, highcut, fs)
    return butter(
        order,
        [lowcut, highcut],
        btype="bandpass",
        fs=fs,
        output="sos",
    )


def rms_value(signal):
    if signal.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(signal), dtype=np.float64) + 1e-12))


def dbfs_from_rms(rms):
    return 20.0 * np.log10(max(float(rms), 1e-12))


def estimate_energy_band(
    magnitude,
    freqs,
    low_limit,
    high_limit,
    min_bandwidth=LOCK_MIN_BANDWIDTH_HZ,
    margin=LOCK_MARGIN_HZ,
):
    """
    Estimate the frequency region carrying most of the current signal energy.

    A small local spectral floor is removed first so broadband background noise
    contributes less to the lock estimate. The returned band is always clamped
    inside the user's Lowcut/Highcut listening band.
    """
    magnitude = np.asarray(magnitude, dtype=np.float64)
    freqs = np.asarray(freqs, dtype=np.float64)

    low_limit = float(low_limit)
    high_limit = float(high_limit)

    mask = (freqs >= low_limit) & (freqs <= high_limit)
    if not np.any(mask):
        return low_limit, high_limit

    band_freqs = freqs[mask]
    power = np.square(magnitude[mask])

    # Suppress the local spectral floor before calculating energy quantiles.
    local_floor = float(np.median(power))
    power = np.maximum(power - (local_floor * 1.5), 0.0)

    total_power = float(np.sum(power))
    if not np.isfinite(total_power) or total_power <= 1e-20:
        return low_limit, high_limit

    cumulative = np.cumsum(power)

    low_target = total_power * LOCK_ENERGY_LOW_QUANTILE
    high_target = total_power * LOCK_ENERGY_HIGH_QUANTILE

    low_index = int(np.searchsorted(cumulative, low_target, side="left"))
    high_index = int(np.searchsorted(cumulative, high_target, side="left"))

    low_index = max(0, min(low_index, len(band_freqs) - 1))
    high_index = max(low_index, min(high_index, len(band_freqs) - 1))

    estimated_low = float(band_freqs[low_index] - margin)
    estimated_high = float(band_freqs[high_index] + margin)

    # Weighted spectral center anchors the minimum lock width.
    weighted_center = float(
        np.sum(band_freqs * power) / max(np.sum(power), 1e-20)
    )

    if (estimated_high - estimated_low) < min_bandwidth:
        half = min_bandwidth * 0.5
        estimated_low = weighted_center - half
        estimated_high = weighted_center + half

    estimated_low = max(low_limit, estimated_low)
    estimated_high = min(high_limit, estimated_high)

    # Preserve the minimum width where possible after clamping.
    if (estimated_high - estimated_low) < min_bandwidth:
        center = min(
            max(weighted_center, low_limit + min_bandwidth * 0.5),
            high_limit - min_bandwidth * 0.5,
        )
        estimated_low = max(low_limit, center - min_bandwidth * 0.5)
        estimated_high = min(high_limit, center + min_bandwidth * 0.5)

    if estimated_low >= estimated_high:
        return low_limit, high_limit

    return float(estimated_low), float(estimated_high)


def spectral_flatness(magnitude):
    mag = np.asarray(magnitude, dtype=np.float64)
    mag = np.maximum(mag, 1e-12)
    geometric = np.exp(np.mean(np.log(mag)))
    arithmetic = np.mean(mag)
    return float(geometric / max(arithmetic, 1e-12))


def spectral_centroid(magnitude, freqs):
    mag = np.asarray(magnitude, dtype=np.float64)
    freqs = np.asarray(freqs, dtype=np.float64)
    total = float(np.sum(mag))
    if total <= 1e-20:
        return 0.0
    return float(np.sum(freqs * mag) / total)


def zero_crossing_rate(signal):
    data = np.asarray(signal, dtype=np.float64)
    if data.size < 2:
        return 0.0
    signs = np.signbit(data)
    return float(np.mean(signs[1:] != signs[:-1]))




# ==============================================================================
# Isolated signal analysis worker
# ==============================================================================

class SpeechMusicClassifier:
    """
    Cautious speech-vs-music estimate over a short feature history.

    Spectral features are measured inside the adaptive locked band whenever
    enough FFT bins are available.
    """

    MIN_BAND_BINS = 8

    def __init__(self):
        self.history = deque()
        self.label = "WAITING"
        self.confidence = 0.0

    def reset(self):
        self.history.clear()
        self.label = "WAITING"
        self.confidence = 0.0

    def update(
        self,
        isolated_block,
        magnitude,
        freqs,
        sample_rate,
        band_low=0.0,
        band_high=0.0,
    ):
        magnitude = np.asarray(
            magnitude,
            dtype=np.float64,
        )
        freqs = np.asarray(
            freqs,
            dtype=np.float64,
        )

        mask = np.ones(
            len(freqs),
            dtype=bool,
        )

        if band_high > band_low:
            band_mask = (
                (freqs >= band_low)
                & (freqs <= band_high)
            )

            if (
                np.count_nonzero(band_mask)
                >= self.MIN_BAND_BINS
            ):
                mask = band_mask

        band_mag = magnitude[mask]
        band_freqs = freqs[mask]

        flatness = spectral_flatness(
            band_mag
        )
        centroid = spectral_centroid(
            band_mag,
            band_freqs,
        )
        zcr = zero_crossing_rate(
            isolated_block
        )

        norm_mag = np.zeros(
            len(magnitude),
            dtype=np.float32,
        )
        norm_mag[mask] = (
            band_mag
            / max(
                float(
                    np.linalg.norm(
                        band_mag
                    )
                ),
                1e-12,
            )
        )

        if (
            self.history
            and len(
                self.history[-1]["norm_mag"]
            )
            == len(norm_mag)
        ):
            diff = (
                norm_mag
                - self.history[-1]["norm_mag"]
            )
            flux = float(
                np.sqrt(
                    np.mean(
                        np.square(diff)
                    )
                )
            )
        else:
            flux = 0.0

        peak = (
            float(
                np.max(band_mag)
            )
            if band_mag.size
            else 0.0
        )
        mean_mag = (
            float(
                np.mean(band_mag)
            )
            if band_mag.size
            else 0.0
        )
        tonality = (
            peak
            / max(
                mean_mag,
                1e-12,
            )
        )

        self.history.append(
            {
                "flatness": flatness,
                "centroid": centroid,
                "zcr": zcr,
                "flux": flux,
                "tonality": tonality,
                "norm_mag": norm_mag,
            }
        )

        max_frames = max(
            CLASSIFIER_MIN_FRAMES,
            int(
                np.ceil(
                    (
                        CLASSIFIER_HISTORY_SECONDS
                        * sample_rate
                    )
                    / BLOCK_SIZE
                )
            ),
        )

        while len(self.history) > max_frames:
            self.history.popleft()

        if len(self.history) < CLASSIFIER_MIN_FRAMES:
            self.label = "ANALYZING"
            self.confidence = 0.0
            return (
                self.label,
                self.confidence,
            )

        hist = list(self.history)

        flats = np.array(
            [f["flatness"] for f in hist],
            dtype=np.float64,
        )
        cents = np.array(
            [f["centroid"] for f in hist],
            dtype=np.float64,
        )
        zcrs = np.array(
            [f["zcr"] for f in hist],
            dtype=np.float64,
        )
        fluxes = np.array(
            [f["flux"] for f in hist],
            dtype=np.float64,
        )
        tonalities = np.array(
            [f["tonality"] for f in hist],
            dtype=np.float64,
        )

        flat_mean = float(np.mean(flats))
        centroid_mean = float(np.mean(cents))
        centroid_cv = float(
            np.std(cents)
            / max(
                abs(centroid_mean),
                1.0,
            )
        )
        zcr_mean = float(np.mean(zcrs))
        flux_mean = float(np.mean(fluxes))
        tonality_mean = float(
            np.mean(tonalities)
        )

        speech_score = 0.0

        if 250.0 <= centroid_mean <= 4200.0:
            speech_score += 1.2
        if 0.03 <= zcr_mean <= 0.24:
            speech_score += 1.0
        if centroid_cv >= 0.12:
            speech_score += 1.0
        if flux_mean >= 0.010:
            speech_score += 0.8
        if 0.03 <= flat_mean <= 0.55:
            speech_score += 0.6

        music_score = 0.0

        if tonality_mean >= 7.0:
            music_score += 1.2
        if centroid_cv <= 0.18:
            music_score += 1.0
        if flat_mean <= 0.35:
            music_score += 0.8
        if 300.0 <= centroid_mean <= 7000.0:
            music_score += 0.6
        if flux_mean <= 0.030:
            music_score += 0.5

        if (
            speech_score
            >= music_score + 0.7
            and speech_score >= 2.2
        ):
            label = "LIKELY TALKING"
            confidence = min(
                0.95,
                0.55
                + (
                    speech_score
                    - music_score
                )
                * 0.10,
            )
        elif (
            music_score
            >= speech_score + 0.7
            and music_score >= 2.2
        ):
            label = "LIKELY MUSIC"
            confidence = min(
                0.95,
                0.55
                + (
                    music_score
                    - speech_score
                )
                * 0.10,
            )
        else:
            label = "OTHER / UNCERTAIN"
            confidence = 0.45

        self.label = label
        self.confidence = float(
            confidence
        )

        return (
            self.label,
            self.confidence,
        )


class IsolatedSpectrumThread(QtCore.QThread):
    """
    Dedicated background worker for the LOCKED/RECORDED signal display.

    The audio worker never waits for this thread. If display analysis falls
    behind, stale frames are dropped and the newest isolated audio block wins.
    """

    result_ready = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.running = True
        self.work_queue = queue.Queue(
            maxsize=4
        )

        self.classifier = SpeechMusicClassifier()
        self.classification = "WAITING"
        self.classification_confidence = 0.0

    def submit(self, packet):
        if not self.running:
            return

        # Never block the recording/audio thread because visualization is slow.
        # Drop the oldest display frame and keep the newest one.
        try:
            self.work_queue.put_nowait(packet)
            return
        except queue.Full:
            pass

        try:
            self.work_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self.work_queue.put_nowait(packet)
        except queue.Full:
            pass

    def reset_analysis(self):
        self.submit({"reset": True})

    def stop(self):
        self.running = False

        try:
            self.work_queue.put_nowait(None)
        except queue.Full:
            try:
                self.work_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.work_queue.put_nowait(None)
            except queue.Full:
                pass

        self.wait(2000)

    def _reset_classifier(self):
        self.classifier.reset()
        self.classification = "WAITING"
        self.classification_confidence = 0.0

    def _classify(
        self,
        isolated_block,
        magnitude,
        freqs,
        sample_rate,
        band_low=0.0,
        band_high=0.0,
    ):
        (
            self.classification,
            self.classification_confidence,
        ) = self.classifier.update(
            isolated_block,
            magnitude,
            freqs,
            sample_rate,
            band_low,
            band_high,
        )

        return (
            self.classification,
            self.classification_confidence,
        )

    def run(self):
        while self.running:
            try:
                packet = self.work_queue.get(
                    timeout=0.20
                )
            except queue.Empty:
                continue

            if packet is None:
                break

            if packet.get("reset"):
                self._reset_classifier()

                # Drain stale isolated frames from the previous lock.
                while True:
                    try:
                        self.work_queue.get_nowait()
                    except queue.Empty:
                        break

                self.result_ready.emit(
                    {
                        "reset": True,
                        "classification": "WAITING",
                        "classification_confidence": 0.0,
                    }
                )
                continue

            try:
                block = np.asarray(
                    packet["block"],
                    dtype=np.float32,
                )
                sample_rate = float(
                    packet["sample_rate"]
                )

                if block.size == 0 or sample_rate <= 0:
                    continue

                window = np.hanning(
                    block.size
                ).astype(np.float32)

                fft_values = np.fft.rfft(
                    block * window
                )
                magnitude = (
                    np.abs(fft_values)
                    / max(1, block.size)
                )
                spectrum_db = (
                    20.0
                    * np.log10(
                        np.maximum(
                            magnitude,
                            1e-12,
                        )
                    )
                ).astype(np.float32)

                freqs = np.fft.rfftfreq(
                    block.size,
                    d=1.0 / sample_rate,
                )

                peak_index = int(
                    np.argmax(magnitude)
                )
                peak_freq = float(
                    freqs[peak_index]
                )

                (
                    classification,
                    confidence,
                ) = self._classify(
                    block,
                    magnitude,
                    freqs,
                    sample_rate,
                    float(
                        packet.get(
                            "lock_low",
                            0.0,
                        )
                    ),
                    float(
                        packet.get(
                            "lock_high",
                            0.0,
                        )
                    ),
                )

                self.result_ready.emit(
                    {
                        "spectrum_db": spectrum_db,
                        "peak_freq": peak_freq,
                        "sample_rate": sample_rate,
                        "lock_low": float(
                            packet.get("lock_low", 0.0)
                        ),
                        "lock_high": float(
                            packet.get("lock_high", 0.0)
                        ),
                        "lock_center": float(
                            packet.get(
                                "lock_center",
                                0.0,
                            )
                        ),
                        "classification": classification,
                        "classification_confidence": confidence,
                    }
                )

            except Exception as exc:
                report_exception(
                    "isolated spectrum analysis",
                    exc,
                )
                self.result_ready.emit(
                    {
                        "error": str(exc),
                    }
                )


# ==============================================================================
# Audio worker
# ==============================================================================

# ==============================================================================
# Real-time audio ring buffer
# ==============================================================================

# ==============================================================================
# Asynchronous SQLite telemetry
# ==============================================================================

class TelemetryDaemon:
    """Asynchronous telemetry logger using SQLite WAL mode."""

    def __init__(
        self,
        db_path: str = "bci_telemetry.db",
        min_free_disk_mb: int = 100,
        queue_capacity: int = 10000,
        batch_size: int = 100,
        flush_interval: float = 0.10,
    ):
        self.db_path = str(db_path)
        self.min_free_disk_mb = int(min_free_disk_mb)
        self.batch_size = max(1, int(batch_size))
        self.flush_interval = max(0.01, float(flush_interval))

        self.queue = queue.Queue(
            maxsize=max(100, int(queue_capacity))
        )
        self.running = False
        self.thread = None
        self._state_lock = threading.Lock()
        self._dropped_events = 0

    def start(self):
        """Start the telemetry worker iff it is currently inactive."""
        with self._state_lock:
            if self.running:
                return

            self._check_disk_space()
            self._init_db()
            self.running = True

            self.thread = threading.Thread(
                target=self._worker,
                name="BCI-Telemetry",
                daemon=True,
            )
            self.thread.start()

    def stop(self):
        """Gracefully stop after draining queued telemetry."""
        with self._state_lock:
            if not self.running:
                return
            self.running = False

        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

        self.thread = None

    def _check_disk_space(self):
        """Validate storage availability before logging begins."""
        dirname = (
            os.path.dirname(
                os.path.abspath(self.db_path)
            )
            or "."
        )

        os.makedirs(dirname, exist_ok=True)

        st = os.statvfs(dirname)
        free_mb = (
            st.f_bavail * st.f_frsize
        ) / (1024.0 * 1024.0)

        if free_mb < self.min_free_disk_mb:
            raise IOError(
                "Storage safety guard tripped: "
                f"Only {free_mb:.2f}MB available."
            )

        return float(free_mb)

    def _connect(self):
        conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
        )
        conn.execute(
            "PRAGMA journal_mode=WAL;"
        )
        conn.execute(
            "PRAGMA synchronous=NORMAL;"
        )
        conn.execute(
            "PRAGMA busy_timeout=5000;"
        )
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_events_timestamp
                ON telemetry_events(timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_events_type
                ON telemetry_events(event_type)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def log_event(
        self,
        event_type: str,
        payload: str,
    ) -> bool:
        """Queue an event without blocking the audio/DSP path."""
        with self._state_lock:
            active = self.running

        if not active:
            return False

        item = (
            time.time(),
            str(event_type),
            str(payload),
        )

        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            with self._state_lock:
                self._dropped_events += 1
            return False

    def dropped_events(self) -> int:
        with self._state_lock:
            return int(self._dropped_events)

    def _drain_batch(self):
        batch = []

        try:
            batch.append(
                self.queue.get(
                    timeout=self.flush_interval
                )
            )
        except queue.Empty:
            return batch

        while len(batch) < self.batch_size:
            try:
                batch.append(
                    self.queue.get_nowait()
                )
            except queue.Empty:
                break

        return batch

    def _worker(self):
        conn = None

        try:
            conn = self._connect()
            cursor = conn.cursor()

            while (
                self.running
                or not self.queue.empty()
            ):
                batch = self._drain_batch()

                if not batch:
                    continue

                try:
                    cursor.executemany(
                        """
                        INSERT INTO telemetry_events (
                            timestamp,
                            event_type,
                            payload
                        )
                        VALUES (?, ?, ?)
                        """,
                        batch,
                    )
                    conn.commit()

                except Exception:
                    conn.rollback()
                    LOGGER.exception(
                        "SQLite telemetry batch insert failed"
                    )

        except Exception:
            LOGGER.exception(
                "SQLite telemetry worker failed"
            )

        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


TELEMETRY_DAEMON = TelemetryDaemon(
    db_path=TELEMETRY_DB,
    min_free_disk_mb=100,
)


# ==============================================================================
# DEVELOPER SEAL: CJB-DEV-2026 | Chance Joaquin Boone
# ==============================================================================


class AudioRingBuffer:
    """Thread-safe circular ring buffer for real-time audio streams."""

    def __init__(
        self,
        capacity: int,
        channels: int = 1,
    ):
        if capacity <= 0:
            raise ValueError(
                "AudioRingBuffer capacity must be positive."
            )

        if channels <= 0:
            raise ValueError(
                "AudioRingBuffer channels must be positive."
            )

        self.capacity = int(capacity)
        self.channels = int(channels)

        self.buffer = np.zeros(
            (
                self.capacity,
                self.channels,
            ),
            dtype=np.float32,
        )

        self.head = 0
        self.tail = 0
        self.size = 0

        self.lock = threading.Lock()

        # Number of unread frames overwritten since the last diagnostics poll.
        self._overwritten_frames = 0

    def write(
        self,
        data: np.ndarray,
    ) -> bool:
        """
        Write incoming frames iff the array dimensions match channel specs.

        If the producer outruns the consumer, oldest unread frames are
        overwritten so the callback always preserves the newest microphone data.
        """
        data = np.asarray(
            data,
            dtype=np.float32,
        )

        if (
            data.ndim != 2
            or data.shape[1] != self.channels
        ):
            return False

        with self.lock:
            n = int(
                len(data)
            )

            if n <= 0:
                return True

            if n > self.capacity:
                data = data[
                    -self.capacity:
                ]
                n = self.capacity

            space_left = (
                self.capacity
                - self.size
            )

            overwritten = max(
                0,
                n - space_left,
            )

            if overwritten:
                self.tail = (
                    self.tail
                    + overwritten
                ) % self.capacity

                self.size = (
                    self.capacity
                )

                self._overwritten_frames += (
                    overwritten
                )
            else:
                self.size += n

            end_idx = (
                self.head + n
            ) % self.capacity

            if end_idx > self.head:
                self.buffer[
                    self.head:end_idx
                ] = data
            else:
                part1 = (
                    self.capacity
                    - self.head
                )

                self.buffer[
                    self.head:
                ] = data[
                    :part1
                ]

                if end_idx:
                    self.buffer[
                        :end_idx
                    ] = data[
                        part1:
                    ]

            self.head = end_idx

        return True

    def read(
        self,
        n_frames: int,
    ) -> np.ndarray:
        """
        Read up to n_frames from the oldest buffered audio.
        """
        n_frames = max(
            0,
            int(n_frames),
        )

        with self.lock:
            read_count = min(
                n_frames,
                self.size,
            )

            if read_count <= 0:
                return np.zeros(
                    (
                        0,
                        self.channels,
                    ),
                    dtype=np.float32,
                )

            end_idx = (
                self.tail
                + read_count
            ) % self.capacity

            if end_idx > self.tail:
                out = self.buffer[
                    self.tail:end_idx
                ].copy()
            else:
                first = self.buffer[
                    self.tail:
                ]
                second = self.buffer[
                    :end_idx
                ]

                out = np.vstack(
                    (
                        first,
                        second,
                    )
                )

            self.tail = end_idx
            self.size -= read_count

            return out

    def available(self) -> int:
        with self.lock:
            return int(
                self.size
            )

    def clear(self):
        with self.lock:
            self.head = 0
            self.tail = 0
            self.size = 0
            self._overwritten_frames = 0

    def take_overwritten_frames(self) -> int:
        with self.lock:
            count = int(
                self._overwritten_frames
            )
            self._overwritten_frames = 0
            return count


# ==============================================================================
# DEVELOPER SEAL: CJB-DEV-2026 | Chance Joaquin Boone
# ==============================================================================


class _BCILiveHTTPHandler(BaseHTTPRequestHandler):
    """Minimal browser-facing handler for the BCIWhisper live MP3 stream."""

    server_version = "BCIWhisperLive/1.0"

    def log_message(self, format, *args):
        # Keep request spam out of the terminal. Client counts and errors are
        # surfaced through the broadcaster's Qt signals instead.
        return

    def do_GET(self):
        broadcaster = getattr(
            self.server,
            "bci_broadcaster",
            None,
        )

        if broadcaster is None:
            self.send_error(503)
            return

        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            page = (
                "<!doctype html><html><head>"
                "<meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Beacon Computing Initiative — BCIWhisper Live</title>"
                "<style>"
                "body{background:#05080d;color:#dce6ec;font-family:sans-serif;"
                "max-width:760px;margin:8vh auto;padding:24px}"
                ".card{background:#0b1117;border:1px solid #31515b;"
                "border-radius:12px;padding:24px}"
                "h1{font-size:24px;letter-spacing:.06em;margin:0 0 8px}"
                "p{color:#8fa0aa}"
                "audio{width:100%;margin-top:18px}"
                ".live{color:#8fb8c1;font-weight:700}"
                "</style></head><body><div class='card'>"
                "<h1>BEACON COMPUTING INITIATIVE</h1>"
                "<div class='live'>BCIWhisper • LIVE AUDIO</div>"
                "<p>Processed monitor feed from the active BCIWhisper input.</p>"
                "<audio controls autoplay src='/live.mp3'></audio>"
                "</div></body></html>"
            ).encode("utf-8")

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8",
            )
            self.send_header(
                "Content-Length",
                str(len(page)),
            )
            self.send_header(
                "Cache-Control",
                "no-store",
            )
            self.end_headers()
            self.wfile.write(page)
            return

        if path == "/status.json":
            payload = json.dumps(
                broadcaster.status_snapshot(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/json",
            )
            self.send_header(
                "Content-Length",
                str(len(payload)),
            )
            self.send_header(
                "Cache-Control",
                "no-store",
            )
            self.end_headers()
            self.wfile.write(payload)
            return

        if path != "/live.mp3":
            self.send_error(404)
            return

        client_queue = broadcaster.register_client()

        if client_queue is None:
            self.send_error(503)
            return

        try:
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "audio/mpeg",
            )
            self.send_header(
                "Cache-Control",
                "no-store, no-cache, must-revalidate",
            )
            self.send_header(
                "Pragma",
                "no-cache",
            )
            self.send_header(
                "Connection",
                "close",
            )
            self.end_headers()

            while broadcaster.is_live:
                try:
                    chunk = client_queue.get(
                        timeout=1.0
                    )
                except queue.Empty:
                    continue

                if chunk is None:
                    break

                self.wfile.write(chunk)
                self.wfile.flush()

        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
        ):
            pass
        except Exception as exc:
            broadcaster.report_stream_error(
                f"client stream: {exc}"
            )
        finally:
            broadcaster.unregister_client(
                client_queue
            )



# ==============================================================================
# BCIWhisper v6.0 Broadcast Foundation — Script 51
# Platform-neutral contracts + bounded realtime broadcast bus.
# ==============================================================================

@dataclass(frozen=True)
class BroadcastAudioFrame:
    sequence: int
    created_monotonic: float
    sample_rate: int
    channels: int
    samples: Any


@dataclass(frozen=True)
class BroadcastTelemetryFrame:
    sequence: int
    created_monotonic: float
    payload: dict


class BroadcastBus:
    """Non-blocking bounded handoff for live-only audio and telemetry."""

    def __init__(self, audio_capacity=24, telemetry_capacity=8):
        self.audio_queue = queue.Queue(maxsize=max(2, int(audio_capacity)))
        self.telemetry_queue = queue.Queue(maxsize=max(2, int(telemetry_capacity)))
        self._lock = threading.Lock()
        self._audio_sequence = 0
        self._telemetry_sequence = 0
        self._audio_dropped = 0
        self._telemetry_dropped = 0

    @staticmethod
    def _put_latest(target_queue, item):
        dropped = False
        try:
            target_queue.put_nowait(item)
            return dropped
        except queue.Full:
            dropped = True
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            target_queue.put_nowait(item)
        except queue.Full:
            pass
        return dropped

    def publish_audio(self, samples, sample_rate, channels=1):
        with self._lock:
            self._audio_sequence += 1
            sequence = self._audio_sequence
        frame = BroadcastAudioFrame(
            sequence=sequence,
            created_monotonic=time.monotonic(),
            sample_rate=int(sample_rate),
            channels=int(channels),
            samples=samples,
        )
        if self._put_latest(self.audio_queue, frame):
            with self._lock:
                self._audio_dropped += 1
        return frame

    def publish_telemetry(self, payload):
        with self._lock:
            self._telemetry_sequence += 1
            sequence = self._telemetry_sequence
        frame = BroadcastTelemetryFrame(
            sequence=sequence,
            created_monotonic=time.monotonic(),
            payload=dict(payload or {}),
        )
        if self._put_latest(self.telemetry_queue, frame):
            with self._lock:
                self._telemetry_dropped += 1
        return frame

    def clear(self):
        for target_queue in (self.audio_queue, self.telemetry_queue):
            while True:
                try:
                    target_queue.get_nowait()
                except queue.Empty:
                    break

    def stats(self):
        with self._lock:
            return {
                "audio_depth": self.audio_queue.qsize(),
                "telemetry_depth": self.telemetry_queue.qsize(),
                "audio_dropped": self._audio_dropped,
                "telemetry_dropped": self._telemetry_dropped,
                "audio_sequence": self._audio_sequence,
                "telemetry_sequence": self._telemetry_sequence,
            }


PUBLIC_BROADCAST_TELEMETRY_FIELDS = frozenset({
    "broadcast_state", "uptime_seconds", "sample_rate", "channels",
    "level_dbfs", "peak_dbfs", "lock_confidence", "spectrum_bands",
    "codec", "bitrate_kbps", "connections", "dropped_audio_frames",
})


def sanitize_public_broadcast_telemetry(payload):
    """Strict allowlist: workstation identifiers and paths never pass through."""
    source = dict(payload or {})
    return {
        key: source[key]
        for key in PUBLIC_BROADCAST_TELEMETRY_FIELDS
        if key in source
    }


class BroadcastPublisher(ABC):
    """OS-neutral contract implemented by the authenticated Script 52 client."""

    @abstractmethod
    def start(self, sample_rate, channels=1):
        raise NotImplementedError

    @abstractmethod
    def submit_audio(self, samples, sample_rate, channels=1):
        raise NotImplementedError

    @abstractmethod
    def submit_telemetry(self, payload):
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def is_running(self):
        raise NotImplementedError


class AudioBackend(ABC):
    """Future Linux / Windows / macOS capture adapter boundary."""

    @abstractmethod
    def enumerate_inputs(self):
        raise NotImplementedError

    @abstractmethod
    def default_input(self):
        raise NotImplementedError

    @abstractmethod
    def open_input(self, device):
        raise NotImplementedError

    @abstractmethod
    def close_input(self):
        raise NotImplementedError


class GoLiveState(str, Enum):
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    LIVE = "LIVE"
    STOPPING = "STOPPING"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class GoLiveController:
    """Thread-safe, UI-independent broadcast lifecycle state machine."""

    _ALLOWED = {
        GoLiveState.OFFLINE: {GoLiveState.STARTING},
        GoLiveState.STARTING: {GoLiveState.LIVE, GoLiveState.ERROR, GoLiveState.STOPPING},
        GoLiveState.LIVE: {GoLiveState.RECONNECTING, GoLiveState.STOPPING, GoLiveState.ERROR},
        GoLiveState.RECONNECTING: {GoLiveState.LIVE, GoLiveState.STOPPING, GoLiveState.ERROR},
        GoLiveState.ERROR: {GoLiveState.OFFLINE, GoLiveState.STARTING, GoLiveState.STOPPING},
        GoLiveState.STOPPING: {GoLiveState.OFFLINE, GoLiveState.ERROR},
    }

    def __init__(self, on_change=None):
        self._lock = threading.RLock()
        self._state = GoLiveState.OFFLINE
        self._live_since = None
        self._last_error = ""
        self._on_change = on_change

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def is_live(self):
        return self.state == GoLiveState.LIVE

    @property
    def uptime_seconds(self):
        with self._lock:
            if self._live_since is None:
                return 0.0
            return max(0.0, time.monotonic() - self._live_since)

    def transition(self, target, reason=""):
        target = GoLiveState(target)
        with self._lock:
            previous = self._state
            if target == previous:
                return target
            if target not in self._ALLOWED.get(previous, set()):
                raise RuntimeError(
                    f"invalid Go-Live transition: {previous.value} -> {target.value}"
                )
            self._state = target
            if target == GoLiveState.LIVE:
                self._live_since = time.monotonic()
                self._last_error = ""
            elif target == GoLiveState.OFFLINE:
                self._live_since = None
            elif target == GoLiveState.ERROR:
                self._last_error = str(reason)[:500]
            callback = self._on_change
        if callback is not None:
            callback(previous, target, str(reason))
        return target

    def begin_start(self):
        if self.state == GoLiveState.ERROR:
            self.transition(GoLiveState.OFFLINE, "reset before start")
        return self.transition(GoLiveState.STARTING, "operator requested live")

    def mark_live(self):
        return self.transition(GoLiveState.LIVE, "publisher ready")

    def fail(self, reason):
        if self.state == GoLiveState.OFFLINE:
            self.begin_start()
        return self.transition(GoLiveState.ERROR, reason)

    def begin_stop(self):
        if self.state == GoLiveState.OFFLINE:
            return GoLiveState.OFFLINE
        return self.transition(GoLiveState.STOPPING, "operator requested stop")

    def mark_offline(self):
        if self.state == GoLiveState.OFFLINE:
            return GoLiveState.OFFLINE
        return self.transition(GoLiveState.OFFLINE, "broadcast stopped")


class BCILiveBroadcastServer(QtCore.QObject):
    """
    Non-blocking live MP3 broadcaster.

    Audio is submitted from the existing processed monitor path into a bounded
    queue. A worker feeds FFmpeg, another worker fans encoded MP3 frames out to
    HTTP clients. No network server exists until start_live() is called.
    """

    status_changed = QtCore.pyqtSignal(str, bool)
    client_count_changed = QtCore.pyqtSignal(int)
    stream_error = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.host = LIVE_STREAM_HOST
        self.port = int(LIVE_STREAM_PORT)
        self.bitrate_kbps = int(
            LIVE_STREAM_BITRATE_KBPS
        )

        self.is_live = False
        self.sample_rate = 48000
        self.started_at = ""

        self.http_server = None
        self.http_thread = None

        self.encoder = None
        self.encoder_input_thread = None
        self.encoder_output_thread = None

        self.audio_queue = queue.Queue(
            maxsize=160
        )

        self.clients_lock = threading.Lock()
        self.clients = []

        self.dropped_audio_blocks = 0

    @staticmethod
    def _best_local_ip():
        candidates = []

        try:
            host_name = socket.gethostname()
            for info in socket.getaddrinfo(
                host_name,
                None,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            ):
                address = info[4][0]
                if (
                    address
                    and not address.startswith("127.")
                    and address not in candidates
                ):
                    candidates.append(address)
        except Exception:
            pass

        # A UDP connect chooses the route without sending application data.
        try:
            probe = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM,
            )
            probe.settimeout(0.2)
            probe.connect(
                ("8.8.8.8", 80)
            )
            address = probe.getsockname()[0]
            probe.close()

            if (
                address
                and not address.startswith("127.")
                and address not in candidates
            ):
                candidates.insert(
                    0,
                    address,
                )
        except Exception:
            pass

        return (
            candidates[0]
            if candidates
            else "127.0.0.1"
        )

    def listening_url(self):
        if LIVE_STREAM_PUBLIC_URL:
            return LIVE_STREAM_PUBLIC_URL

        return (
            f"http://{self._best_local_ip()}:{self.port}/"
        )

    def status_snapshot(self):
        with self.clients_lock:
            client_count = len(
                self.clients
            )

        return {
            "project": "BCIWhisper",
            "organization": "Beacon Computing Initiative",
            "project_version": BCI_PROJECT_VERSION,
            "script_tally": BCI_SCRIPT_TALLY,
            "build": BCI_BUILD,
            "live": bool(self.is_live),
            "sample_rate": int(self.sample_rate),
            "bitrate_kbps": int(self.bitrate_kbps),
            "clients": int(client_count),
            "started_at": str(self.started_at),
            "dropped_audio_blocks": int(
                self.dropped_audio_blocks
            ),
        }

    def report_stream_error(self, message):
        LOGGER.warning(
            "Go Live: %s",
            message,
        )
        self.stream_error.emit(
            str(message)
        )

    def register_client(self):
        if not self.is_live:
            return None

        client_queue = queue.Queue(
            maxsize=96
        )

        with self.clients_lock:
            self.clients.append(
                client_queue
            )
            count = len(
                self.clients
            )

        self.client_count_changed.emit(
            count
        )

        return client_queue

    def unregister_client(self, client_queue):
        with self.clients_lock:
            try:
                self.clients.remove(
                    client_queue
                )
            except ValueError:
                pass

            count = len(
                self.clients
            )

        self.client_count_changed.emit(
            count
        )

    def _broadcast_chunk(self, chunk):
        stale = []

        with self.clients_lock:
            clients = list(
                self.clients
            )

        for client_queue in clients:
            try:
                client_queue.put_nowait(
                    chunk
                )
            except queue.Full:
                # Drop a slow client instead of allowing it to back-pressure
                # the real-time capture or encoder path.
                stale.append(
                    client_queue
                )

        for client_queue in stale:
            try:
                client_queue.put_nowait(
                    None
                )
            except Exception:
                pass
            self.unregister_client(
                client_queue
            )

    def _encoder_input_loop(self):
        while self.is_live:
            try:
                item = self.audio_queue.get(
                    timeout=0.5
                )
            except queue.Empty:
                continue

            if item is None:
                break

            try:
                block = np.asarray(
                    item,
                    dtype=np.float32,
                ).reshape(-1)

                block = np.nan_to_num(
                    block,
                    nan=0.0,
                    posinf=0.0,
                    neginf=0.0,
                )

                block = np.clip(
                    block,
                    -0.98,
                    0.98,
                ).astype(
                    np.float32,
                    copy=False,
                )

                encoder = self.encoder

                if (
                    encoder is None
                    or encoder.stdin is None
                    or encoder.poll() is not None
                ):
                    break

                encoder.stdin.write(
                    block.tobytes()
                )
                encoder.stdin.flush()

            except (
                BrokenPipeError,
                OSError,
            ):
                break
            except Exception as exc:
                self.report_stream_error(
                    f"encoder input: {exc}"
                )
                break

    def _encoder_output_loop(self):
        while self.is_live:
            encoder = self.encoder

            if (
                encoder is None
                or encoder.stdout is None
            ):
                break

            try:
                chunk = encoder.stdout.read(
                    4096
                )
            except Exception as exc:
                self.report_stream_error(
                    f"encoder output: {exc}"
                )
                break

            if not chunk:
                if encoder.poll() is not None:
                    break
                continue

            self._broadcast_chunk(
                chunk
            )

    def submit_audio(self, block, sample_rate):
        if not self.is_live:
            return

        try:
            incoming_rate = int(
                sample_rate
            )
        except Exception:
            incoming_rate = int(
                self.sample_rate
            )

        if incoming_rate != int(self.sample_rate):
            # A device/sample-rate change while live should be explicit rather
            # than silently playing at the wrong speed. The GUI restarts live
            # streaming after microphone changes if requested by the user.
            self.report_stream_error(
                "Audio sample rate changed while live. Stop and restart Go Live."
            )
            return

        try:
            self.audio_queue.put_nowait(
                np.asarray(
                    block,
                    dtype=np.float32,
                ).copy()
            )
        except queue.Full:
            self.dropped_audio_blocks += 1

    def start_live(self, sample_rate):
        if self.is_live:
            return self.listening_url()

        ffmpeg = shutil.which(
            "ffmpeg"
        )

        if not ffmpeg:
            raise RuntimeError(
                "FFmpeg is required for Go Live. "
                "Install it with: sudo apt install ffmpeg"
            )

        self.sample_rate = max(
            8000,
            int(sample_rate),
        )
        self.dropped_audio_blocks = 0

        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        self.encoder = subprocess.Popen(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "f32le",
                "-ar",
                str(self.sample_rate),
                "-ac",
                "1",
                "-i",
                "pipe:0",
                "-vn",
                "-c:a",
                "libmp3lame",
                "-b:a",
                f"{self.bitrate_kbps}k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

        try:
            self.http_server = ThreadingHTTPServer(
                (
                    self.host,
                    self.port,
                ),
                _BCILiveHTTPHandler,
            )
            self.http_server.daemon_threads = True
            self.http_server.bci_broadcaster = self

        except Exception:
            try:
                self.encoder.terminate()
            except Exception:
                pass
            self.encoder = None
            raise

        self.started_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self.is_live = True

        self.encoder_input_thread = threading.Thread(
            target=self._encoder_input_loop,
            name="BCILiveEncoderInput",
            daemon=True,
        )
        self.encoder_output_thread = threading.Thread(
            target=self._encoder_output_loop,
            name="BCILiveEncoderOutput",
            daemon=True,
        )
        self.http_thread = threading.Thread(
            target=self.http_server.serve_forever,
            kwargs={
                "poll_interval": 0.25,
            },
            name="BCILiveHTTP",
            daemon=True,
        )

        self.encoder_input_thread.start()
        self.encoder_output_thread.start()
        self.http_thread.start()

        url = self.listening_url()

        self.status_changed.emit(
            f"LIVE • {url}",
            True,
        )

        return url

    def stop_live(self):
        if not self.is_live:
            return

        self.is_live = False

        try:
            self.audio_queue.put_nowait(
                None
            )
        except queue.Full:
            pass

        server = self.http_server
        self.http_server = None

        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass

            try:
                server.server_close()
            except Exception:
                pass

        with self.clients_lock:
            clients = list(
                self.clients
            )
            self.clients.clear()

        for client_queue in clients:
            try:
                client_queue.put_nowait(
                    None
                )
            except Exception:
                pass

        self.client_count_changed.emit(
            0
        )

        encoder = self.encoder
        self.encoder = None

        if encoder is not None:
            try:
                if encoder.stdin is not None:
                    encoder.stdin.close()
            except Exception:
                pass

            try:
                encoder.terminate()
            except Exception:
                pass

            try:
                encoder.wait(
                    timeout=2.0
                )
            except Exception:
                try:
                    encoder.kill()
                except Exception:
                    pass

        for thread in (
            self.encoder_input_thread,
            self.encoder_output_thread,
            self.http_thread,
        ):
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(
                    timeout=1.0
                )

        self.encoder_input_thread = None
        self.encoder_output_thread = None
        self.http_thread = None

        self.status_changed.emit(
            "OFFLINE",
            False,
        )

class AudioProcessorThread(QtCore.QThread):
    spectrum_ready = QtCore.pyqtSignal(object)
    live_audio_block = QtCore.pyqtSignal(object)
    isolated_block_ready = QtCore.pyqtSignal(object)
    baseline_started = QtCore.pyqtSignal(object)
    baseline_interrupted = QtCore.pyqtSignal(str)
    boot_complete = QtCore.pyqtSignal(object)
    device_status = QtCore.pyqtSignal(str, bool)
    recording_saved = QtCore.pyqtSignal(str, str)
    short_event_logged = QtCore.pyqtSignal(object)
    error_event = QtCore.pyqtSignal(str, str)

    @property
    def calibrated(self):
        return self.runtime_state.calibrated

    @calibrated.setter
    def calibrated(self, value):
        self.runtime_state.calibrated = bool(value)

    @property
    def full_baseline_needed(self):
        return self.runtime_state.full_baseline_needed

    @full_baseline_needed.setter
    def full_baseline_needed(self, value):
        self.runtime_state.full_baseline_needed = bool(value)

    @property
    def device_changed(self):
        return self.runtime_state.device_changed

    @device_changed.setter
    def device_changed(self, value):
        self.runtime_state.device_changed = bool(value)

    def _emit_gui_packet(self, packet, force=False):
        """Publish at most one current visual packet per GUI frame interval.

        Capture, lock detection, recording, and DSP continue at full worker
        cadence. Dropping an obsolete presentation packet cannot drop audio.
        """
        now = time.monotonic()
        if (
            not force
            and (now - self._last_gui_emit_monotonic) < self._gui_emit_interval
        ):
            return
        self._last_gui_emit_monotonic = now
        self.spectrum_ready.emit(packet)

    def __init__(self):
        super().__init__()

        self.running = True
        self.lock = threading.Lock()

        # r6 reliability / lock-tracking state.
        self._wake = threading.Event()
        self._block_id = 0
        self._calibration_reset_needed = True
        self._presence_ema = None
        self._presence_cache_block = -1
        self._presence_cache_value = -120.0
        self._baseline_power = None
        self._baseline_power_src = None
        self._xfade_sos = None
        self._xfade_zi = None
        self._disk_warned_at = float("-inf")
        self.live_stream_enabled = False

        # Script 49 GUI load distribution. DSP/capture cadence is untouched;
        # only presentation packets are rate-limited before crossing into Qt.
        self._last_gui_emit_monotonic = 0.0
        self._gui_emit_interval = AUDIO_GUI_UPDATE_INTERVAL_MS / 1000.0

        self.lowcut = DEFAULT_LOWCUT
        self.highcut = DEFAULT_HIGHCUT
        self.gain = DEFAULT_GAIN
        self.sensitivity_multiplier = DEFAULT_SENSITIVITY

        # Capture selection is an intent, not a PortAudio object. Script 57.7
        # resolves this intent inside the isolated audio-hardware process.
        self.selected_device_id = -1
        self.selected_device_name = ""
        self.selection_mode = "auto"

        # Script 57.7: one DSP-side state authority replaces the independent
        # calibrated/full_baseline_needed/device_changed boolean stores.
        self.runtime_state = BCIAudioRuntimeStateMachine()

        # Hardware boundary state. No active input-device enumeration/opening
        # occurs in this QThread anymore. The boundary supervisor owns PortAudio
        # and publishes immutable stream sessions + PCM packets here.
        self._hardware_boundary = None
        self._hardware_session = None
        self._hardware_session_event = threading.Event()
        self._hardware_session_generation = 0
        self._hardware_snapshot_devices = []

        # Instance-owned timing prevents a renamed/missing module constant
        # from crashing the audio worker at runtime.
        self.startup_calibration_seconds = STARTUP_CALIBRATION_SECONDS
        self.recalibration_seconds = RECALIBRATION_SECONDS

        self.noise_floor_rms = 0.0005
        self.noise_floor_db = dbfs_from_rms(self.noise_floor_rms)

        # Frequency-by-frequency ambient room profile learned at BCI boot.
        self.noise_profile_db = None
        self.noise_profile_peak_freq = 0.0

        # Wall-clock baseline state. Progress must not freeze just because an
        # audio block is dropped.
        self.baseline_started_at = None
        self.baseline_valid_blocks = 0
        self.boot_complete_sent = False

        # PortAudio copies microphone frames into a bounded circular ring.
        # DSP, lock tracking, disk writes and display work remain outside the
        # real-time callback.
        self.capture_ring = AudioRingBuffer(
            capacity=CAPTURE_RING_FRAMES,
            channels=1,
        )
        self.capture_data_ready = threading.Event()

        self.capture_stats_lock = threading.Lock()
        self.capture_callback_flags = 0
        self.capture_last_status = ""
        self.capture_last_report_at = 0.0

        self.pre_buffer = deque()
        self.is_recording = False
        self.raw_recording_frames = []
        self.processed_recording_frames = []
        self.raw_filename = ""
        self.processed_filename = ""

        # WAV files are streamed while the lock is active. This supports long
        # recordings without retaining the entire event in memory.
        self.raw_writer = None
        self.processed_writer = None

        self.trigger_blocks = 0
        self.release_blocks = 0
        self.recorded_blocks = 0

        # Candidate-event accounting. recorded_blocks tracks candidate file
        # length after the trigger, while locked_signal_blocks counts only
        # blocks where the spectral lock is positively present. The latter is
        # what decides whether a recording is kept.
        self.locked_signal_blocks = 0
        self.event_started_at = ""
        self.event_started_unix = 0.0
        self.event_initial_peak_hz = 0.0
        self.event_peak_hz = 0.0
        self.event_max_rms = 0.0
        self.event_max_snr_db = -120.0
        self.event_lock_low_hz = 0.0
        self.event_lock_high_hz = 0.0

        self.sample_rate = 48000
        self.filter_sos = None
        self.filter_zi = None
        self.last_filter_signature = None

        # Adaptive signal-lock filter state.
        self.lock_active = False
        self.lock_low = 0.0
        self.lock_high = 0.0
        self.lock_center = 0.0
        self.lock_sos = None
        self.lock_zi = None
        self.lock_update_counter = 0

        # Speech/music classification lives in IsolatedSpectrumThread.
        self.classification = "WAITING"
        self.classification_confidence = 0.0

    def _report_worker_error(self, context, exc):
        report_exception(context, exc)

        try:
            self.error_event.emit(
                str(context),
                str(exc),
            )
        except Exception as signal_exc:
            report_exception(
                "audio error signal",
                signal_exc,
            )

    # --------------------------------------------------------------------------
    # Parameter handling
    # --------------------------------------------------------------------------

    def set_live_stream_enabled(self, enabled):
        with self.lock:
            self.live_stream_enabled = bool(
                enabled
            )

    def attach_hardware_boundary(self, boundary):
        """Attach the one input-hardware authority for this worker."""
        self._hardware_boundary = boundary

    def offer_hardware_snapshot(self, snapshot):
        """Cache a plain-Python device snapshot published by the boundary."""
        try:
            devices = list(snapshot.get("devices", []) or [])
        except Exception:
            devices = []
        with self.lock:
            self._hardware_snapshot_devices = devices

    def offer_hardware_session(self, payload):
        """Publish a newly opened capture session to the DSP worker.

        This method is intentionally lock/event-only so it is safe to call from
        the boundary QThread. The DSP thread consumes the session on its next
        outer-loop pass.
        """
        session = dict(payload or {})
        generation = int(session.get("generation", 0) or 0)
        with self.lock:
            previous = self._hardware_session
            previous_generation = int(
                (previous or {}).get("generation", 0) or 0
            )
            self._hardware_session = session
            self._hardware_session_generation = generation
            if generation != previous_generation:
                self.runtime_state.mark_session_changed(
                    "isolated hardware session generation changed"
                )
            else:
                self.runtime_state.mark_session_changed(
                    "isolated hardware session refreshed"
                )
            self.baseline_started_at = None
            self.baseline_valid_blocks = 0
            self.boot_complete_sent = False
            self.last_filter_signature = None

        self._hardware_session_event.set()
        self.capture_data_ready.set()
        self._wake.set()

    def invalidate_hardware_session(self, reason="capture boundary unavailable"):
        """Invalidate capture atomically and force a clean baseline on recovery."""
        with self.lock:
            had_session = self._hardware_session is not None
            self._hardware_session = None
            self._hardware_session_generation += 1
            self.runtime_state.mark_recovering(str(reason))
            self.baseline_started_at = None
            self.baseline_valid_blocks = 0
            self.boot_complete_sent = False
            self.last_filter_signature = None
            self._calibration_reset_needed = True

        self._hardware_session_event.clear()
        self.capture_ring.clear()
        self.capture_data_ready.set()
        self._wake.set()

        if had_session or reason:
            try:
                self.baseline_interrupted.emit(str(reason))
            except Exception:
                pass

    def accept_capture_packet(self, packet):
        """Accept PCM from the isolated hardware process into the local ring."""
        if not self.running:
            return

        try:
            packet_generation = int(packet.get("generation", 0) or 0)
            with self.lock:
                session = dict(self._hardware_session or {})
            session_generation = int(session.get("generation", 0) or 0)

            # Never mix late frames from an old process/session into a new
            # calibration or recording epoch.
            if (
                session_generation <= 0
                or packet_generation != session_generation
            ):
                return

            pcm = packet.get("pcm", b"")
            frames = int(packet.get("frames", 0) or 0)
            if not pcm or frames <= 0:
                return

            block = np.frombuffer(pcm, dtype=np.float32)
            if block.size < frames:
                return
            block = np.ascontiguousarray(block[:frames].reshape(-1, 1))

            callback_status = str(packet.get("status", "") or "")
            if callback_status:
                with self.capture_stats_lock:
                    self.capture_callback_flags += 1
                    self.capture_last_status = callback_status

            if self.capture_ring.write(block):
                self.capture_data_ready.set()

        except Exception as exc:
            self._report_worker_error("audio boundary packet", exc)

    def update_parameters(
        self,
        lowcut,
        highcut,
        gain,
        sensitivity,
        device_id,
        device_name="",
        selection_mode=None,
    ):
        device_switch = False
        boundary_command = None

        try:
            requested_id = int(device_id)
        except (TypeError, ValueError):
            requested_id = -1

        requested_mode = str(
            selection_mode
            or ("explicit" if requested_id >= 0 else "auto")
        ).lower()
        if requested_mode not in ("auto", "explicit"):
            requested_mode = "explicit" if requested_id >= 0 else "auto"
        requested_name = str(device_name or "").strip()

        with self.lock:
            filter_changed = (
                float(lowcut) != self.lowcut
                or float(highcut) != self.highcut
                or float(gain) != self.gain
            )

            self.lowcut = float(lowcut)
            self.highcut = float(highcut)
            self.gain = float(gain)
            self.sensitivity_multiplier = float(sensitivity)

            old_identity = (
                int(self.selected_device_id),
                str(self.selected_device_name),
                str(self.selection_mode),
            )
            new_identity = (
                requested_id,
                requested_name,
                requested_mode,
            )

            if new_identity != old_identity:
                self.selected_device_id = requested_id
                self.selected_device_name = requested_name
                self.selection_mode = requested_mode
                self.runtime_state.mark_session_changed(
                    "capture selection changed"
                )
                self.baseline_started_at = None
                self.baseline_valid_blocks = 0
                self.boot_complete_sent = False
                filter_changed = True
                device_switch = True
                boundary_command = {
                    "mode": requested_mode,
                    "device_name": requested_name,
                    "device_id": requested_id,
                }

            if filter_changed:
                self.runtime_state.mark_filter_invalidated(
                    "DSP filter parameters changed"
                )
                self.last_filter_signature = None

        if device_switch:
            self.capture_ring.clear()
            self._hardware_session_event.clear()
            self.capture_data_ready.set()
            self._wake.set()
            boundary = self._hardware_boundary
            if boundary is not None and boundary_command is not None:
                boundary.set_selection(**boundary_command)

    # --------------------------------------------------------------------------
    # Device helpers
    # --------------------------------------------------------------------------

    @staticmethod
    def _safe_capture_name(device_name):
        """
        Reject ALSA processing PCMs and playback-monitor sources.

        These objects can advertise input channels even though they are not
        microphones. In particular, opening ALSA's `upmix` PCM has been observed
        to terminate PortAudio inside libasound before Python can raise an
        exception.
        """
        name = str(device_name or "").strip().lower()

        blocked_exact = {
            "upmix",
            "vdownmix",
            "lavrate",
            "samplerate",
            "speexrate",
            "speex",
        }

        if name in blocked_exact:
            return False

        if ".monitor" in name or name.endswith(" monitor"):
            return False

        if name.startswith("bluez_output."):
            return False

        return True

    def _available_input_devices(self):
        """Return capture candidates from the last boundary-owned snapshot."""
        with self.lock:
            devices = list(self._hardware_snapshot_devices or [])
        out = []
        for index, info in enumerate(devices):
            if int(info.get("max_input_channels", 0) or 0) <= 0:
                continue
            if not self._safe_capture_name(info.get("name", "")):
                continue
            out.append((index, info))
        return out

    def _candidate_device_ids(self, requested_device_id, excluded_device_ids=None):
        """Resolve candidates from a cached immutable boundary snapshot.

        This helper is retained for diagnostics only. It never calls PortAudio.
        The actual open transaction is authoritative inside bci_audio.boundary.
        """
        with self.lock:
            devices = list(self._hardware_snapshot_devices or [])
            selected_name = str(self.selected_device_name or "").strip()
            mode = str(self.selection_mode or "auto").lower()

        excluded = {
            int(item)
            for item in (excluded_device_ids or ())
            if isinstance(item, (int, np.integer))
            or str(item).lstrip("-").isdigit()
        }
        candidates = []

        def add(device_id):
            try:
                device_id = int(device_id)
            except (TypeError, ValueError):
                return
            if device_id < 0 or device_id >= len(devices):
                return
            if device_id in excluded or device_id in candidates:
                return
            info = devices[device_id]
            if int(info.get("max_input_channels", 0) or 0) <= 0:
                return
            if not self._safe_capture_name(info.get("name", "")):
                return
            candidates.append(device_id)

        if mode == "explicit":
            if selected_name:
                wanted = selected_name.casefold()
                for index, info in enumerate(devices):
                    if str(info.get("name", "")).strip().casefold() == wanted:
                        add(index)
            if not candidates:
                add(requested_device_id)
            return candidates

        for preferred in ("pipewire", "pulse", "default source", "default"):
            for index, info in enumerate(devices):
                if str(info.get("name", "")).strip().casefold() == preferred:
                    add(index)
        return candidates

    def request_input_reopen(self):
        """Request a clean hardware-boundary reopen and fresh room profile."""
        with self.lock:
            self.runtime_state.mark_recovering(
                "capture reopen requested"
            )
            self.baseline_started_at = None
            self.baseline_valid_blocks = 0
            self.boot_complete_sent = False
            self.last_filter_signature = None

        self.capture_ring.clear()
        self._hardware_session_event.clear()
        self.capture_data_ready.set()
        self._wake.set()

        boundary = self._hardware_boundary
        if boundary is not None:
            boundary.request_reopen()

    def _reset_capture_queue(self):
        self.capture_ring.clear()
        self.capture_data_ready.clear()

        with self.capture_stats_lock:
            self.capture_callback_flags = 0
            self.capture_last_status = ""

    def _audio_input_callback(
        self,
        indata,
        frames,
        time_info,
        status,
    ):
        """
        PortAudio real-time callback.

        Only status capture, ring-buffer write, and consumer wakeup happen here.
        No FFT, filtering, Qt work, signal-lock analysis, or disk I/O is performed.
        """
        if not self.running:
            return

        if status:
            with self.capture_stats_lock:
                self.capture_callback_flags += 1
                self.capture_last_status = str(
                    status
                )

        try:
            block = np.asarray(
                indata,
                dtype=np.float32,
            )

            if block.ndim == 1:
                block = block.reshape(
                    -1,
                    1,
                )

            if (
                block.size <= 0
                or block.shape[1] != 1
            ):
                return

            if self.capture_ring.write(
                block
            ):
                self.capture_data_ready.set()

        except Exception:
            # The PortAudio callback must never block on recovery or UI work.
            return

    def _take_capture_diagnostics(self):
        overwritten_frames = (
            self.capture_ring.take_overwritten_frames()
        )

        dropped_blocks = int(
            np.ceil(
                overwritten_frames
                / max(
                    BLOCK_SIZE,
                    1,
                )
            )
        )

        with self.capture_stats_lock:
            flags = self.capture_callback_flags
            status = self.capture_last_status

            self.capture_callback_flags = 0
            self.capture_last_status = ""

        return (
            flags,
            dropped_blocks,
            status,
        )

    class _BoundaryStreamHandle:
        """No-op compatibility handle for the DSP worker's legacy lifecycle."""
        def stop(self):
            return None

        def close(self):
            return None

    def _open_input_stream(self, requested_device_id, excluded_device_ids=None):
        """Wait for a session opened by the isolated hardware boundary.

        No PortAudio function is called here. A native query/open/start that
        wedges lives in a killable child process supervised by
        BCIAudioBoundaryThread.
        """
        while self.running:
            if not self._hardware_session_event.wait(0.50):
                continue

            with self.lock:
                session = dict(self._hardware_session or {})

            if not session:
                self._hardware_session_event.clear()
                continue

            device_id = int(session.get("device_id", -1))
            device_name = str(session.get("device_name", "Boundary Input"))
            sample_rate = int(session.get("sample_rate", 48000) or 48000)
            info = {
                "name": device_name,
                "max_input_channels": 1,
                "default_samplerate": float(sample_rate),
                "boundary_generation": int(session.get("generation", 0) or 0),
            }
            return (
                self._BoundaryStreamHandle(),
                device_id,
                info,
                sample_rate,
            )

        raise RuntimeError("Audio worker stopped while waiting for hardware boundary")

    def _configure_filter(self, sample_rate, lowcut, highcut, gain):
        """Configure the worker-owned analysis band-pass filter.

        Script 57.7 restores this DSP boundary method after the 57.5/57.6
        hardware modularization accidentally removed its implementation while
        leaving the run-loop call site intact.  The method does not touch
        PortAudio or UI state; it owns only local DSP coefficients and marks
        calibration invalid when those coefficients change.
        """
        signature = (
            int(sample_rate),
            round(float(lowcut), 3),
            round(float(highcut), 3),
            round(float(gain), 3),
        )

        if signature == self.last_filter_signature:
            return

        sos = design_bandpass(lowcut, highcut, sample_rate, order=4)
        self.filter_sos = sos
        self.filter_zi = sosfilt_zi(sos) * 0.0
        self.last_filter_signature = signature
        self.runtime_state.mark_filter_invalidated(
            "band-pass filter coefficients changed"
        )
        self._calibration_reset_needed = True

    def _rebuild_prebuffer(self, sample_rate):
        blocks = max(
            1,
            int(np.ceil((PREBUFFER_SECONDS * sample_rate) / BLOCK_SIZE)),
        )
        self.pre_buffer = deque(maxlen=blocks)

    def _calibration_duration(self):
        if self.full_baseline_needed:
            return float(self.startup_calibration_seconds)
        return float(self.recalibration_seconds)

    def _calibration_block_count(self, sample_rate):
        duration = self._calibration_duration()
        return max(
            10,
            int(np.ceil((duration * sample_rate) / BLOCK_SIZE)),
        )

    def _release_block_count(self, sample_rate):
        return max(
            1,
            int(np.ceil((RELEASE_SECONDS * sample_rate) / BLOCK_SIZE)),
        )

    def _max_clip_blocks(self, sample_rate):
        if MAX_CLIP_SECONDS <= 0:
            return None

        return max(
            1,
            int(
                np.ceil(
                    (MAX_CLIP_SECONDS * sample_rate)
                    / BLOCK_SIZE
                )
            ),
        )


    # --------------------------------------------------------------------------
    # Intelligent signal-lock helpers
    # --------------------------------------------------------------------------

    def _reset_signal_lock(self):
        self.lock_active = False
        self.lock_low = 0.0
        self.lock_high = 0.0
        self.lock_center = 0.0
        self.lock_sos = None
        self.lock_zi = None
        self.lock_update_counter = 0

        self._xfade_sos = None
        self._xfade_zi = None

        self._presence_ema = None
        self._presence_cache_block = -1
        self._presence_cache_value = -120.0

    def _limit_lock_step(self, old_value, new_value):
        delta = float(new_value) - float(old_value)
        delta = max(-LOCK_MAX_STEP_HZ, min(LOCK_MAX_STEP_HZ, delta))
        return float(old_value) + delta

    def _set_signal_lock(
        self,
        proposed_low,
        proposed_high,
        base_low,
        base_high,
        force=False,
        seed_sample=0.0,
    ):
        proposed_low = max(float(base_low), float(proposed_low))
        proposed_high = min(float(base_high), float(proposed_high))

        if proposed_low >= proposed_high:
            return False

        if self.lock_active and not force:
            proposed_low = self._limit_lock_step(
                self.lock_low,
                proposed_low,
            )
            proposed_high = self._limit_lock_step(
                self.lock_high,
                proposed_high,
            )

            alpha = LOCK_SMOOTHING
            new_low = (
                (1.0 - alpha) * self.lock_low
                + alpha * proposed_low
            )
            new_high = (
                (1.0 - alpha) * self.lock_high
                + alpha * proposed_high
            )
        else:
            new_low = proposed_low
            new_high = proposed_high

        new_low, new_high = clamp_band(
            new_low,
            new_high,
            self.sample_rate,
        )

        # Never let the adaptive band escape the user's listening band.
        new_low = max(float(base_low), new_low)
        new_high = min(float(base_high), new_high)

        if new_low >= new_high:
            return False

        needs_retune = (
            force
            or not self.lock_active
            or abs(new_low - self.lock_low) >= LOCK_RETUNE_THRESHOLD_HZ
            or abs(new_high - self.lock_high) >= LOCK_RETUNE_THRESHOLD_HZ
        )

        self.lock_low = float(new_low)
        self.lock_high = float(new_high)
        self.lock_center = (self.lock_low + self.lock_high) * 0.5
        self.lock_active = True

        if needs_retune:
            # Preserve the outgoing filter for one-block crossfade so retunes
            # do not create an audible click in the isolated recording.
            if (
                not force
                and self.lock_sos is not None
                and self.lock_zi is not None
            ):
                self._xfade_sos = self.lock_sos
                self._xfade_zi = self.lock_zi

            self.lock_sos = design_bandpass(
                self.lock_low,
                self.lock_high,
                self.sample_rate,
                order=4,
            )
            self.lock_zi = (
                sosfilt_zi(self.lock_sos) * float(seed_sample)
            )

        return True

    def _update_signal_lock(
        self,
        magnitude,
        freqs,
        base_low,
        base_high,
        force=False,
        seed_sample=0.0,
    ):
        estimated_low, estimated_high = estimate_energy_band(
            magnitude,
            freqs,
            base_low,
            base_high,
        )

        return self._set_signal_lock(
            estimated_low,
            estimated_high,
            base_low,
            base_high,
            force=force,
            seed_sample=seed_sample,
        )

    def _filter_locked_block(self, raw_block):
        block = np.asarray(
            raw_block,
            dtype=np.float32,
        )

        if (
            not self.lock_active
            or self.lock_sos is None
            or self.lock_zi is None
        ):
            return block.copy()

        isolated, self.lock_zi = sosfilt(
            self.lock_sos,
            block,
            zi=self.lock_zi,
        )

        if (
            self._xfade_sos is not None
            and self._xfade_zi is not None
        ):
            try:
                old_out, self._xfade_zi = sosfilt(
                    self._xfade_sos,
                    block,
                    zi=self._xfade_zi,
                )

                fade = np.linspace(
                    0.0,
                    1.0,
                    block.size,
                    dtype=np.float64,
                )

                isolated = (
                    old_out * (1.0 - fade)
                    + isolated * fade
                )
            finally:
                self._xfade_sos = None
                self._xfade_zi = None

        return (
            isolated * self.gain
        ).astype(
            np.float32,
            copy=False,
        )


    # --------------------------------------------------------------------------
    # Speech / music classifier
    # --------------------------------------------------------------------------




    def _lock_presence_db(
        self,
        spectrum_db,
        freqs,
    ):
        """
        Return locked-band total-power excess over the room baseline in dB.

        Summing power across the adaptive band is substantially more stable than
        using a percentile of individual FFT-bin excess values. A short EMA then
        prevents a single noisy frame from resetting the release timer.
        """
        if (
            not self.lock_active
            or self.lock_high <= self.lock_low
            or spectrum_db is None
        ):
            return -120.0

        if (
            self._presence_cache_block
            == self._block_id
        ):
            return self._presence_cache_value

        spectrum = np.asarray(
            spectrum_db,
            dtype=np.float64,
        )
        freq_axis = np.asarray(
            freqs,
            dtype=np.float64,
        )

        mask = (
            (freq_axis >= self.lock_low)
            & (freq_axis <= self.lock_high)
        )

        if not np.any(mask):
            return -120.0

        profile = self.noise_profile_db

        if (
            profile is None
            or len(profile) != len(spectrum)
        ):
            return 0.0

        if self._baseline_power_src is not profile:
            q = (
                BASELINE_SPECTRUM_PERCENTILE
                / 100.0
            )

            correction_db = (
                -10.0
                * np.log10(
                    -np.log(
                        1.0 - q
                    )
                )
            )

            self._baseline_power = (
                10.0
                ** (
                    (
                        np.asarray(
                            profile,
                            dtype=np.float64,
                        )
                        + correction_db
                    )
                    / 10.0
                )
            )

            self._baseline_power_src = profile

        now_power = float(
            np.sum(
                10.0
                ** (
                    spectrum[mask]
                    / 10.0
                )
            )
        )

        base_power = float(
            np.sum(
                self._baseline_power[mask]
            )
        )

        raw_excess = (
            10.0
            * np.log10(
                max(
                    now_power,
                    1e-20,
                )
                / max(
                    base_power,
                    1e-20,
                )
            )
        )

        if self._presence_ema is None:
            self._presence_ema = raw_excess
        else:
            alpha = LOCK_PRESENCE_SMOOTHING
            self._presence_ema = (
                alpha * raw_excess
                + (
                    1.0 - alpha
                )
                * self._presence_ema
            )

        self._presence_cache_block = (
            self._block_id
        )
        self._presence_cache_value = float(
            self._presence_ema
        )

        return self._presence_cache_value

    # --------------------------------------------------------------------------
    # Recording helpers
    # --------------------------------------------------------------------------

    def _open_wav_writer(self, filename):
        try:
            Path(filename).parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            writer = wave.open(filename, "wb")
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(int(self.sample_rate))
            return writer

        except Exception as exc:
            self._report_worker_error(
                f"opening WAV file {filename}",
                exc,
            )
            raise RuntimeError(
                f"Could not open recording file: {filename}"
            ) from exc

    def _writer_write_block(self, writer, block):
        if writer is None or block is None:
            return

        try:
            data = np.asarray(
                block,
                dtype=np.float32,
            )
            data = np.clip(
                data,
                -1.0,
                1.0,
            )
            pcm = (
                data * 32767.0
            ).astype(np.int16)

            writer.writeframesraw(
                pcm.tobytes()
            )

        except Exception as exc:
            self._report_worker_error(
                "writing recording audio",
                exc,
            )
            raise RuntimeError(
                "Recording write failed"
            ) from exc

    def _start_recording(self, raw_block, peak_freq, rms, snr_db):
        self.is_recording = True
        self.release_blocks = 0
        self.recorded_blocks = 0
        self.locked_signal_blocks = 0

        started_now = datetime.now().astimezone()
        self.event_started_at = started_now.isoformat(
            timespec="milliseconds"
        )
        self.event_started_unix = time.time()
        self.event_initial_peak_hz = float(peak_freq)
        self.event_peak_hz = float(peak_freq)
        self.event_max_rms = float(rms)
        self.event_max_snr_db = float(snr_db)
        self.event_lock_low_hz = float(self.lock_low)
        self.event_lock_high_hz = float(self.lock_high)

        stamp = started_now.strftime("%Y%m%d_%H%M%S_%f")
        base = os.path.join(LOG_DIR, f"bci_event_{stamp}")

        self.raw_filename = f"{base}_raw.wav"
        self.processed_filename = f"{base}_isolated.wav"

        # Close stale handles defensively before opening a new event.
        for writer_name in ("raw_writer", "processed_writer"):
            writer = getattr(self, writer_name, None)
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass
                setattr(self, writer_name, None)

        try:
            self.raw_writer = self._open_wav_writer(
                self.raw_filename
            )
            self.processed_writer = self._open_wav_writer(
                self.processed_filename
            )
        except Exception:
            for writer_name in (
                "raw_writer",
                "processed_writer",
            ):
                writer = getattr(
                    self,
                    writer_name,
                    None,
                )
                if writer is not None:
                    try:
                        writer.close()
                    except Exception as close_exc:
                        self._report_worker_error(
                            f"closing {writer_name} after open failure",
                            close_exc,
                        )
                    setattr(
                        self,
                        writer_name,
                        None,
                    )

            self.is_recording = False
            raise

        # Current block is already the last pre-buffer entry. Exclude it so the
        # trigger block is not written twice.
        pre_items = list(self.pre_buffer)[:-1]
        pre_raw = [item[0] for item in pre_items]

        # Re-seed the adaptive isolated filter so the pre-trigger lead-in is
        # processed through the same spectral lock.
        if self.lock_sos is not None:
            seed = (
                float(pre_raw[0][0])
                if pre_raw and len(pre_raw[0]) > 0
                else float(raw_block[0])
                if len(raw_block) > 0
                else 0.0
            )
            self.lock_zi = sosfilt_zi(self.lock_sos) * seed

        for pre in pre_raw:
            isolated_pre = self._filter_locked_block(pre)
            self._writer_write_block(
                self.raw_writer,
                pre,
            )
            self._writer_write_block(
                self.processed_writer,
                isolated_pre,
            )

        isolated_current = self._filter_locked_block(
            raw_block
        )

        self._writer_write_block(
            self.raw_writer,
            raw_block,
        )
        self._writer_write_block(
            self.processed_writer,
            isolated_current,
        )
        self.recorded_blocks += 1

        self.log_telemetry(
            peak_freq=peak_freq,
            rms=rms,
            snr_db=snr_db,
            raw_filename=self.raw_filename,
            processed_filename=self.processed_filename,
        )

        return isolated_current

    def _append_recording(self, raw_block):
        isolated = self._filter_locked_block(
            raw_block
        )

        self._writer_write_block(
            self.raw_writer,
            raw_block,
        )
        self._writer_write_block(
            self.processed_writer,
            isolated,
        )
        self.recorded_blocks += 1

        if not self._checkpoint_recording():
            self._finish_recording(
                reason="disk_guard"
            )

        return isolated

    @staticmethod
    def _wav_duration_seconds(path):
        path = Path(path)

        if not path.exists():
            return 0.0

        try:
            with wave.open(str(path), "rb") as wf:
                sample_rate = int(wf.getframerate())
                frames = int(wf.getnframes())

                if sample_rate > 0:
                    return float(frames / sample_rate)

        except Exception:
            pass

        return 0.0

    @staticmethod
    def _remove_candidate_artifacts(*paths):
        removed = []

        for value in paths:
            if not value:
                continue

            path = Path(value)

            candidates = [
                path,
                path.with_suffix(".txt"),
                path.with_suffix(".enhancement.json"),
                path.with_suffix(".mastering.json"),
            ]

            for candidate in candidates:
                try:
                    if candidate.exists():
                        candidate.unlink()
                        removed.append(str(candidate))
                except Exception as exc:
                    report_warning(
                        "short-event cleanup",
                        f"{candidate}: {exc}",
                    )

        return removed

    def _log_short_event(self, payload):
        line = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        try:
            Path(SHORT_EVENT_LOG).parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with open(
                SHORT_EVENT_LOG,
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(line + "\n")

        except Exception as exc:
            self._report_worker_error(
                "short-event JSONL log",
                exc,
            )

        try:
            queued = TELEMETRY_DAEMON.log_event(
                "SHORT_SIGNAL_DETECTED",
                line,
            )

            if (
                TELEMETRY_DAEMON.running
                and not queued
            ):
                report_warning(
                    "SQLite telemetry",
                    "short-event telemetry queue full; event dropped",
                )

        except Exception as exc:
            self._report_worker_error(
                "short-event SQLite telemetry",
                exc,
            )

        try:
            with open(
                TELEMETRY_LOG,
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    f"[{payload.get('ended_at', '')}] "
                    f"SHORT_SIGNAL_DETECTED | "
                    f"Locked={payload.get('locked_seconds', 0.0):.2f}s | "
                    f"Peak={payload.get('peak_hz', 0.0):.1f}Hz | "
                    f"MaxSNR={payload.get('max_snr_db', 0.0):.2f}dB | "
                    f"Reason={payload.get('finish_reason', 'unknown')}\n"
                )

        except Exception as exc:
            self._report_worker_error(
                "short-event text telemetry",
                exc,
            )

    def _finish_recording(self, reason="signal_lost"):
        if not self.is_recording:
            return

        finished_raw = self.raw_filename
        finished_isolated = self.processed_filename

        locked_blocks = int(
            self.locked_signal_blocks
        )
        recorded_blocks = int(
            self.recorded_blocks
        )
        sample_rate = max(
            1,
            int(self.sample_rate),
        )
        locked_seconds = (
            locked_blocks
            * BLOCK_SIZE
            / sample_rate
        )

        event_snapshot = {
            "started_at": str(self.event_started_at),
            "started_unix": float(self.event_started_unix),
            "initial_peak_hz": float(self.event_initial_peak_hz),
            "peak_hz": float(self.event_peak_hz),
            "max_rms": float(self.event_max_rms),
            "max_level_dbfs": float(
                dbfs_from_rms(
                    max(
                        self.event_max_rms,
                        1e-12,
                    )
                )
            ),
            "max_snr_db": float(self.event_max_snr_db),
            "lock_low_hz": float(self.event_lock_low_hz),
            "lock_high_hz": float(self.event_lock_high_hz),
        }

        for writer_name in ("raw_writer", "processed_writer"):
            writer = getattr(self, writer_name, None)
            if writer is not None:
                try:
                    writer.close()
                except Exception as exc:
                    self._report_worker_error(
                        f"closing {writer_name}",
                        exc,
                    )
                setattr(self, writer_name, None)

        candidate_duration = self._wav_duration_seconds(
            finished_raw
        )

        ended_now = datetime.now().astimezone()

        qualifies_for_save = (
            locked_seconds
            >= MIN_SAVED_LOCK_SECONDS
        )

        self.is_recording = False
        self.raw_recording_frames = []
        self.processed_recording_frames = []
        self.raw_filename = ""
        self.processed_filename = ""
        self.release_blocks = 0
        self.recorded_blocks = 0
        self.locked_signal_blocks = 0
        self._reset_signal_lock()

        if qualifies_for_save:
            if finished_raw or finished_isolated:
                try:
                    TELEMETRY_DAEMON.log_event(
                        "RECORDING_RETAINED",
                        json.dumps(
                            {
                                "project_version": BCI_PROJECT_VERSION,
                                "script_tally": BCI_SCRIPT_TALLY,
                                "build": BCI_BUILD,
                                "started_at": event_snapshot["started_at"],
                                "ended_at": ended_now.isoformat(
                                    timespec="milliseconds"
                                ),
                                "locked_seconds": float(locked_seconds),
                                "candidate_duration_seconds": float(
                                    candidate_duration
                                ),
                                "minimum_saved_lock_seconds": float(
                                    MIN_SAVED_LOCK_SECONDS
                                ),
                                "finish_reason": str(reason),
                                "raw_file": str(finished_raw),
                                "isolated_file": str(finished_isolated),
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                except Exception as exc:
                    self._report_worker_error(
                        "retained-recording telemetry",
                        exc,
                    )

                self.recording_saved.emit(
                    finished_raw,
                    finished_isolated,
                )

            return

        short_payload = {
            "event": "SHORT_SIGNAL_DETECTED",
            "project_version": BCI_PROJECT_VERSION,
            "script_tally": BCI_SCRIPT_TALLY,
            "build": BCI_BUILD,
            "detected_at": event_snapshot["started_at"],
            "ended_at": ended_now.isoformat(
                timespec="milliseconds"
            ),
            "locked_seconds": float(locked_seconds),
            "candidate_duration_seconds": float(
                candidate_duration
            ),
            "locked_blocks": int(locked_blocks),
            "candidate_blocks": int(recorded_blocks),
            "minimum_saved_lock_seconds": float(
                MIN_SAVED_LOCK_SECONDS
            ),
            "initial_peak_hz": event_snapshot["initial_peak_hz"],
            "peak_hz": event_snapshot["peak_hz"],
            "max_rms": event_snapshot["max_rms"],
            "max_level_dbfs": event_snapshot["max_level_dbfs"],
            "max_snr_db": event_snapshot["max_snr_db"],
            "lock_low_hz": event_snapshot["lock_low_hz"],
            "lock_high_hz": event_snapshot["lock_high_hz"],
            "finish_reason": str(reason),
            "action": "discarded_audio_logged_detection",
            "discarded_raw_name": (
                Path(finished_raw).name
                if finished_raw
                else ""
            ),
            "discarded_isolated_name": (
                Path(finished_isolated).name
                if finished_isolated
                else ""
            ),
        }

        removed_paths = self._remove_candidate_artifacts(
            finished_raw,
            finished_isolated,
        )
        short_payload["removed_artifact_count"] = int(
            len(removed_paths)
        )

        self._log_short_event(
            short_payload
        )
        self.short_event_logged.emit(
            short_payload
        )

        print(
            "[BCI] Short signal logged, audio discarded: "
            f"{locked_seconds:.2f}s locked "
            f"(< {MIN_SAVED_LOCK_SECONDS:.1f}s minimum)"
        )

    def log_telemetry(
        self,
        peak_freq,
        rms,
        snr_db,
        raw_filename,
        processed_filename,
    ):
        payload = {
            "project_version": BCI_PROJECT_VERSION,
            "script_tally": BCI_SCRIPT_TALLY,
            "build": BCI_BUILD,
            "peak_hz": float(peak_freq),
            "rms": float(rms),
            "snr_db": float(snr_db),
            "lock_low_hz": float(self.lock_low),
            "lock_high_hz": float(self.lock_high),
            "raw_file": str(raw_filename),
            "isolated_file": str(processed_filename),
        }

        try:
            queued = TELEMETRY_DAEMON.log_event(
                "BCI_EVENT",
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

            if (
                TELEMETRY_DAEMON.running
                and not queued
            ):
                report_warning(
                    "SQLite telemetry",
                    "telemetry queue full; event dropped",
                )

        except Exception as exc:
            self._report_worker_error(
                "SQLite telemetry queue",
                exc,
            )

        # Keep the text file for tail/grep diagnostics.
        entry = (
            f"[{datetime.now().isoformat()}] "
            f"BCI_EVENT | "
            f"ProjectVersion={BCI_PROJECT_VERSION} | "
            f"Script={BCI_SCRIPT_TALLY} | "
            f"Build={BCI_BUILD} | "
            f"Peak={peak_freq:.1f}Hz | "
            f"RMS={rms:.6f} | "
            f"SNR={snr_db:.2f}dB | "
            f"Lock={self.lock_low:.1f}-{self.lock_high:.1f}Hz | "
            f"Raw={raw_filename} | "
            f"Isolated={processed_filename}\\n"
        )

        try:
            with open(
                TELEMETRY_LOG,
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(entry)

        except Exception as exc:
            self._report_worker_error(
                "telemetry log write",
                exc,
            )

    # --------------------------------------------------------------------------
    # Worker loop
    # --------------------------------------------------------------------------

    def run(self):
        retry_delay = 1.0

        while self.running:
            with self.lock:
                requested_device = self.selected_device_id

            stream = None

            try:
                self._reset_capture_queue()

                # Script 57.7: alias selection/open/failover is authoritative
                # inside the isolated hardware process. The DSP worker waits for
                # exactly one published session and never enumerates candidates.
                stream, active_device, device_info, sample_rate = (
                    self._open_input_stream(requested_device)
                )
                self.runtime_state.mark_capture_open(
                    "isolated capture session accepted by DSP"
                )

                self.sample_rate = int(sample_rate)
                self._rebuild_prebuffer(self.sample_rate)
                stream_opened_at = time.monotonic()
                last_complete_block_at = None
                baseline_announced = False
                calibration_last_heartbeat = 0.0

                active_name = str(
                    device_info.get("name", f"Device {active_device}")
                )

                try:
                    requested_is_auto = int(requested_device) < 0
                except (TypeError, ValueError):
                    requested_is_auto = True

                if requested_is_auto:
                    msg = (
                        f"AUTO INPUT -> {active_device}: "
                        f"{active_name} @ {self.sample_rate} Hz [RING BUFFERED]"
                    )
                elif active_device == requested_device:
                    msg = (
                        f"INPUT {active_device}: "
                        f"{active_name} @ {self.sample_rate} Hz [RING BUFFERED]"
                    )
                else:
                    msg = (
                        f"Selected input {requested_device} unavailable; "
                        f"using {active_device}: "
                        f"{active_name} @ {self.sample_rate} Hz [RING BUFFERED]"
                    )

                self.device_status.emit(msg, True)
                retry_delay = 1.0

                calibration_samples = []
                calibration_spectra = []
                calibration_frame_index = 0
                calibration_spectrum_db = None
                calibration_peak_freq = 0.0
                calibration_last_gui_emit = 0.0
                calibration_needed = self._calibration_block_count(
                    self.sample_rate
                )

                release_needed = self._release_block_count(self.sample_rate)
                lock_release_needed = max(
                    1,
                    int(
                        np.ceil(
                            (LOCK_RELEASE_SECONDS * self.sample_rate)
                            / BLOCK_SIZE
                        )
                    ),
                )
                max_clip_blocks = self._max_clip_blocks(self.sample_rate)

                freqs = np.fft.rfftfreq(
                    BLOCK_SIZE,
                    d=1.0 / self.sample_rate,
                )
                hann = np.hanning(BLOCK_SIZE).astype(np.float32)

                while self.running:
                    with self.lock:
                        if self.device_changed:
                            break

                        lowcut = self.lowcut
                        highcut = self.highcut
                        gain = self.gain
                        sensitivity = self.sensitivity_multiplier

                    self._configure_filter(
                        self.sample_rate,
                        lowcut,
                        highcut,
                        gain,
                    )

                    # Drain only complete DSP blocks. The wake event prevents
                    # busy-waiting while still allowing arbitrary callback frame
                    # sizes to accumulate in the ring.
                    if (
                        self.capture_ring.available()
                        < BLOCK_SIZE
                    ):
                        self.capture_data_ready.clear()

                        # Re-check after clearing to avoid a lost wakeup.
                        if (
                            self.capture_ring.available()
                            < BLOCK_SIZE
                        ):
                            if not self.capture_data_ready.wait(
                                CAPTURE_QUEUE_TIMEOUT
                            ):
                                now = time.monotonic()
                                liveness_anchor = (
                                    last_complete_block_at
                                    if last_complete_block_at is not None
                                    else stream_opened_at
                                )
                                timeout_limit = (
                                    CAPTURE_STALL_TIMEOUT_SECONDS
                                    if last_complete_block_at is not None
                                    else CAPTURE_FIRST_BLOCK_TIMEOUT_SECONDS
                                )
                                if now - liveness_anchor >= timeout_limit:
                                    # Script 57.3: an opened PortAudio stream that
                                    # produces no full blocks is not a valid input.
                                    # Without this watchdog Script 57.2 could wait
                                    # forever while the visual boot clock advanced.
                                    raise RuntimeError(
                                        "Input stream opened but delivered no "
                                        f"complete audio block for {timeout_limit:.1f}s "
                                        f"({active_device}:{active_name})"
                                    )
                                continue

                    if (
                        self.capture_ring.available()
                        < BLOCK_SIZE
                    ):
                        continue

                    raw_frames = self.capture_ring.read(
                        BLOCK_SIZE
                    )

                    if (
                        raw_frames.shape
                        != (
                            BLOCK_SIZE,
                            1,
                        )
                    ):
                        continue

                    block_now = time.monotonic()
                    last_complete_block_at = block_now

                    # A successfully started PortAudio stream is not sufficient
                    # evidence of capture. Begin the authoritative 60-second
                    # baseline only after the first complete microphone block.
                    if self.full_baseline_needed and not baseline_announced:
                        self.runtime_state.mark_first_frames(
                            "first complete PCM block consumed"
                        )
                        self.baseline_started_at = block_now
                        self.baseline_valid_blocks = 0
                        self.boot_complete_sent = False
                        baseline_announced = True
                        self.baseline_started.emit(
                            {
                                "duration": float(self.startup_calibration_seconds),
                                "device_id": int(active_device),
                                "device_name": active_name,
                                "sample_rate": int(self.sample_rate),
                            }
                        )
                        print(
                            "[BCI] First live microphone block confirmed -> "
                            f"baseline clock started ({active_name} @ "
                            f"{self.sample_rate} Hz)"
                        )

                    raw = raw_frames[
                        :,
                        0,
                    ].astype(
                        np.float32,
                        copy=False,
                    )

                    # Keep the consumer runnable if more full blocks are queued.
                    if (
                        self.capture_ring.available()
                        >= BLOCK_SIZE
                    ):
                        self.capture_data_ready.set()

                    flags, queue_drops, callback_status = (
                        self._take_capture_diagnostics()
                    )

                    if flags or queue_drops:
                        now = time.monotonic()

                        if (
                            now - self.capture_last_report_at
                            >= CAPTURE_STATUS_REPORT_SECONDS
                        ):
                            self.capture_last_report_at = now

                            if queue_drops:
                                message = (
                                    f"USB INPUT RECOVERED | "
                                    f"capture queue dropped "
                                    f"{queue_drops} stale block(s)"
                                )
                                healthy = False
                            else:
                                message = (
                                    f"USB INPUT CALLBACK STATUS RECOVERED"
                                )
                                healthy = True

                            if callback_status:
                                message += (
                                    f" | {callback_status}"
                                )

                            self.device_status.emit(
                                message,
                                healthy,
                            )

                    filtered, self.filter_zi = sosfilt(
                        self.filter_sos,
                        raw,
                        zi=self.filter_zi,
                    )
                    processed = (filtered * gain).astype(np.float32, copy=False)

                    with self.lock:
                        live_stream_enabled = bool(
                            self.live_stream_enabled
                        )

                    if live_stream_enabled:
                        broadcast_block = BCI_BROADCAST_CONDITIONER.process(
                            filtered
                        )
                        self.live_audio_block.emit(
                            {
                                "block": broadcast_block.copy(),
                                "sample_rate": int(
                                    self.sample_rate
                                ),
                                "channels": 1,
                                "source": "hardware_capture",
                            }
                        )

                    self._block_id += 1

                    # Pre-roll stores raw audio only; the adaptive lock filter
                    # is applied when the clip begins.
                    self.pre_buffer.append(
                        (
                            raw.copy(),
                            None,
                        )
                    )

                    rms = rms_value(processed)

                    # Startup ambient-noise calibration. Triggering and recording
                    # remain disabled during this entire pass. The broad spectrum
                    # stays live so the user can see exactly what contributes to
                    # the baseline.
                    if not self.calibrated:
                        # Never leave a clip logically open while calibration
                        # suspends normal recording writes.
                        if self.is_recording:
                            self._finish_recording(
                                reason="recalibration"
                            )

                        self.trigger_blocks = 0

                        if self._calibration_reset_needed:
                            self._calibration_reset_needed = False
                            calibration_samples.clear()
                            calibration_spectra.clear()
                            calibration_frame_index = 0
                            calibration_spectrum_db = None
                            calibration_peak_freq = 0.0
                            calibration_last_gui_emit = 0.0

                            if self.full_baseline_needed:
                                self.baseline_started_at = time.monotonic()
                                self.baseline_valid_blocks = 0

                        calibration_duration = self._calibration_duration()
                        calibration_needed = self._calibration_block_count(
                            self.sample_rate
                        )
                        calibration_samples.append(rms)

                        # RMS/timing remain full-rate, but spectral analysis is
                        # intentionally decimated. The previous implementation
                        # performed a complete RFFT/log/peak search on every DSP
                        # block and only applied the stride when storing results.
                        # Cache the latest spectrum for presentation and calculate
                        # a new one only at the room-profile sampling cadence.
                        calibration_frame_index += 1
                        calibration_spectrum_due = (
                            calibration_spectrum_db is None
                            or calibration_frame_index
                            % BASELINE_SPECTRUM_SAMPLE_STRIDE
                            == 0
                        )

                        if calibration_spectrum_due:
                            calibration_fft = np.fft.rfft(
                                processed * hann
                            )
                            calibration_magnitude = (
                                np.abs(calibration_fft)
                                / max(1, BLOCK_SIZE)
                            )
                            calibration_spectrum_db = (
                                20.0
                                * np.log10(
                                    np.maximum(
                                        calibration_magnitude,
                                        1e-12,
                                    )
                                )
                            )
                            calibration_peak_index = int(
                                np.argmax(calibration_magnitude)
                            )
                            calibration_peak_freq = float(
                                freqs[calibration_peak_index]
                            )
                            calibration_spectra.append(
                                calibration_spectrum_db.astype(
                                    np.float32,
                                    copy=True,
                                )
                            )

                        samples_collected = len(calibration_samples)

                        if self.full_baseline_needed:
                            now = time.monotonic()

                            if self.baseline_started_at is None:
                                self.baseline_started_at = now

                            self.baseline_valid_blocks += 1

                            elapsed_seconds = max(
                                0.0,
                                now - self.baseline_started_at,
                            )
                            valid_seconds = (
                                self.baseline_valid_blocks
                                * BLOCK_SIZE
                                / self.sample_rate
                            )

                            time_complete = (
                                elapsed_seconds
                                >= calibration_duration
                            )
                            audio_complete = (
                                valid_seconds
                                >= BASELINE_MIN_VALID_SECONDS
                            )

                            if (
                                now - calibration_last_heartbeat
                                >= CALIBRATION_HEARTBEAT_SECONDS
                            ):
                                calibration_last_heartbeat = now
                                print(
                                    "[BCI] Baseline progress "
                                    f"elapsed={elapsed_seconds:.1f}s/"
                                    f"{calibration_duration:.1f}s "
                                    f"valid_audio={valid_seconds:.1f}s "
                                    f"blocks={self.baseline_valid_blocks}"
                                )

                            calibration_complete = (
                                time_complete and audio_complete
                            )

                            if calibration_complete:
                                progress = 1.0
                            else:
                                progress = min(
                                    0.99,
                                    elapsed_seconds
                                    / max(calibration_duration, 1e-6),
                                )

                            remaining_seconds = max(
                                0.0,
                                calibration_duration
                                - elapsed_seconds,
                            )
                        else:
                            valid_seconds = (
                                samples_collected
                                * BLOCK_SIZE
                                / self.sample_rate
                            )
                            progress = min(
                                1.0,
                                samples_collected
                                / max(1, calibration_needed),
                            )
                            remaining_seconds = max(
                                0.0,
                                calibration_duration
                                * (1.0 - progress),
                            )
                            calibration_complete = (
                                samples_collected
                                >= calibration_needed
                            )

                        if calibration_complete:
                            # Use a robust lower-middle percentile so a cough,
                            # door slam, or short foreground sound during the
                            # minute does not define the ambient floor.
                            baseline = float(
                                np.percentile(calibration_samples, 40.0)
                            )
                            self.noise_floor_rms = max(baseline, 1e-6)
                            self.noise_floor_db = dbfs_from_rms(
                                self.noise_floor_rms
                            )

                            if calibration_spectra:
                                profile_stack = np.stack(
                                    calibration_spectra,
                                    axis=0,
                                )
                                self.noise_profile_db = np.percentile(
                                    profile_stack,
                                    BASELINE_SPECTRUM_PERCENTILE,
                                    axis=0,
                                ).astype(np.float32)

                                profile_peak_index = int(
                                    np.argmax(self.noise_profile_db)
                                )
                                self.noise_profile_peak_freq = float(
                                    freqs[profile_peak_index]
                                )
                            else:
                                self.noise_profile_db = (
                                    calibration_spectrum_db.copy()
                                )
                                self.noise_profile_peak_freq = (
                                    calibration_peak_freq
                                )

                            if calibration_duration >= 30.0:
                                self._persist_room_profile()

                            self.runtime_state.mark_baseline_complete(
                                "60-second room profile established"
                            )
                            print(
                                "[BCI] Room baseline complete; "
                                "entering analyzer"
                            )
                            progress = 1.0
                            remaining_seconds = 0.0
                            self.baseline_started_at = None
                            self.baseline_valid_blocks = 0
                            calibration_samples.clear()
                            calibration_spectra.clear()

                        calibration_status = (
                            "BASELINE_COMPLETE"
                            if calibration_complete
                            and not self.full_baseline_needed
                            else "CALIBRATING"
                        )

                        if (
                            calibration_status == "BASELINE_COMPLETE"
                            and calibration_duration >= 30.0
                            and not self.boot_complete_sent
                        ):
                            self.boot_complete_sent = True
                            self.boot_complete.emit(
                                {
                                    "noise_floor_db": self.noise_floor_db,
                                    "baseline_profile_peak_freq": (
                                        self.noise_profile_peak_freq
                                    ),
                                    "baseline_valid_seconds": valid_seconds,
                                    "sample_rate": self.sample_rate,
                                }
                            )

                        calibration_gui_now = time.monotonic()
                        calibration_gui_due = (
                            calibration_status == "BASELINE_COMPLETE"
                            or (
                                calibration_gui_now
                                - calibration_last_gui_emit
                            )
                            >= (
                                CALIBRATION_GUI_UPDATE_INTERVAL_MS
                                / 1000.0
                            )
                        )

                        if calibration_gui_due:
                            calibration_last_gui_emit = (
                                calibration_gui_now
                            )
                            self._emit_gui_packet(
                                {
                                    "spectrum_db": calibration_spectrum_db,
                                    "isolated_spectrum_db": None,
                                    "rms": rms,
                                    "peak_freq": calibration_peak_freq,
                                    "snr_db": 0.0,
                                    "is_active": False,
                                    "status": calibration_status,
                                    "lock_low": 0.0,
                                    "lock_high": 0.0,
                                    "lock_center": 0.0,
                                    "sample_rate": self.sample_rate,
                                    "classification": "BASELINING",
                                    "classification_confidence": 0.0,
                                    "calibration_progress": progress,
                                    "calibration_remaining": (
                                        remaining_seconds
                                    ),
                                    "noise_floor_db": self.noise_floor_db,
                                    "calibration_duration": (
                                        calibration_duration
                                    ),
                                    "baseline_profile_peak_freq": (
                                        self.noise_profile_peak_freq
                                    ),
                                    "baseline_valid_seconds": valid_seconds,
                                    "baseline_warning": (
                                        ""
                                        if valid_seconds
                                        >= BASELINE_MIN_VALID_SECONDS
                                        else (
                                            "COLLECTING VALID USB MIC AUDIO "
                                            f"({valid_seconds:.1f}s / "
                                            f"{BASELINE_MIN_VALID_SECONDS:.0f}s)"
                                        )
                                    ),
                                },
                                force=(
                                    calibration_status
                                    == "BASELINE_COMPLETE"
                                ),
                            )
                        continue

                    fft_complex = np.fft.rfft(processed * hann)
                    magnitude = np.abs(fft_complex) / max(1, BLOCK_SIZE)
                    spectrum_db = 20.0 * np.log10(
                        np.maximum(magnitude, 1e-12)
                    )

                    peak_index = int(np.argmax(magnitude))
                    peak_freq = float(freqs[peak_index])

                    current_db = dbfs_from_rms(rms)
                    snr_db = current_db - self.noise_floor_db

                    # Higher UI sensitivity means a lower required SNR.
                    required_snr_db = max(
                        2.0,
                        10.0 - (sensitivity - 0.5) * 4.0,
                    )

                    signal_active = snr_db >= required_snr_db

                    lock_excess_db = (
                        self._lock_presence_db(
                            spectrum_db,
                            freqs,
                        )
                        if self.is_recording
                        else -120.0
                    )
                    lock_signal_active = (
                        self.is_recording
                        and lock_excess_db >= LOCK_PRESENCE_DB
                    )

                    if signal_active:
                        self.trigger_blocks += 1
                    else:
                        self.trigger_blocks = 0

                    confirmed_trigger = (
                        self.trigger_blocks >= MIN_TRIGGER_BLOCKS
                    )

                    isolated_block = None
                    isolated_spectrum_db = None
                    display_peak_freq = peak_freq

                    lock_update_needed = max(
                        1,
                        int(
                            np.ceil(
                                (LOCK_UPDATE_SECONDS * self.sample_rate)
                                / BLOCK_SIZE
                            )
                        ),
                    )

                    if (
                        confirmed_trigger
                        and not self.is_recording
                        and self._disk_ok_to_record()
                    ):
                        # Acquire the first lock from the spectrum that caused
                        # the event trigger.
                        self._update_signal_lock(
                            magnitude,
                            freqs,
                            lowcut,
                            highcut,
                            force=True,
                            seed_sample=(
                                float(raw[0]) if len(raw) else 0.0
                            ),
                        )

                        isolated_block = self._start_recording(
                            raw,
                            peak_freq,
                            rms,
                            snr_db,
                        )

                    elif self.is_recording:
                        # Follow real movement of the spectral energy envelope,
                        # but retune slowly enough to avoid chasing individual
                        # FFT-bin fluctuations.
                        if signal_active or lock_signal_active:
                            self.lock_update_counter += 1

                            if (
                                self.lock_update_counter
                                >= lock_update_needed
                            ):
                                self._update_signal_lock(
                                    magnitude,
                                    freqs,
                                    lowcut,
                                    highcut,
                                    force=False,
                                    seed_sample=(
                                        float(raw[0])
                                        if len(raw)
                                        else 0.0
                                    ),
                                )
                                self.lock_update_counter = 0

                        isolated_block = self._append_recording(raw)

                    if isolated_block is not None:
                        # Visualization/classification is intentionally handled
                        # by a second QThread. The recorder only publishes a
                        # copy of the exact isolated block being written.
                        self.isolated_block_ready.emit(
                            {
                                "block": isolated_block.copy(),
                                "sample_rate": self.sample_rate,
                                "lock_low": self.lock_low,
                                "lock_high": self.lock_high,
                                "lock_center": self.lock_center,
                            }
                        )

                    if self.is_recording:
                        lock_excess_db = self._lock_presence_db(
                            spectrum_db,
                            freqs,
                        )
                        lock_signal_active = (
                            lock_excess_db >= LOCK_PRESENCE_DB
                        )

                        # Script 57.8 stabilization diagnostic:
                        # observe lock continuity without changing detector behavior.
                        if (
                            self.recorded_blocks == 1
                            or self.recorded_blocks % 25 == 0
                            or not lock_signal_active
                        ):
                            release_seconds = (
                                self.release_blocks
                                * BLOCK_SIZE
                                / max(1, self.sample_rate)
                            )

                            print(
                                "[BCI][LOCK-DIAG] "
                                f"broad_snr={snr_db:.2f}dB "
                                f"required_snr={required_snr_db:.2f}dB "
                                f"lock_excess={lock_excess_db:.2f}dB "
                                f"lock_threshold={LOCK_PRESENCE_DB:.2f}dB "
                                f"active={int(lock_signal_active)} "
                                f"release_blocks={self.release_blocks} "
                                f"release_seconds={release_seconds:.2f}s "
                                f"locked_blocks={self.locked_signal_blocks} "
                                f"lock={self.lock_low:.1f}-{self.lock_high:.1f}Hz"
                            )
                        # Once acquired, the LOCK controls recording. Brief
                        # speech pauses or broad-trigger dips do not stop it.
                        # Count only blocks where the spectral lock itself is
                        # positively present. Broad-trigger time, pre-roll and
                        # release grace do not count toward the 15-second keep rule.
                        if lock_signal_active:
                            self.locked_signal_blocks += 1
                            self.release_blocks = 0
                        else:
                            self.release_blocks += 1

                        if rms >= self.event_max_rms:
                            self.event_max_rms = float(rms)
                            self.event_peak_hz = float(peak_freq)

                        self.event_max_snr_db = max(
                            float(self.event_max_snr_db),
                            float(snr_db),
                        )

                        should_stop_for_loss = (
                            self.release_blocks
                            >= lock_release_needed
                        )
                        should_stop_for_cap = (
                            max_clip_blocks is not None
                            and self.recorded_blocks
                            >= max_clip_blocks
                        )

                        if (
                            should_stop_for_loss
                            or should_stop_for_cap
                        ):
                            if (
                                should_stop_for_loss
                                and should_stop_for_cap
                            ):
                                finish_reason = "signal_lost+max_clip"
                            elif should_stop_for_cap:
                                finish_reason = "max_clip"
                            else:
                                finish_reason = "signal_lost"

                            self._finish_recording(
                                reason=finish_reason
                            )

                    status = (
                        "SIGNAL LOCKED"
                        if self.is_recording
                        else "MONITORING"
                    )

                    self._emit_gui_packet(
                        {
                            "spectrum_db": spectrum_db,
                            "isolated_spectrum_db": isolated_spectrum_db,
                            "rms": rms,
                            "peak_freq": display_peak_freq,
                            "snr_db": snr_db,
                            "is_active": self.is_recording,
                            "status": status,
                            "lock_low": (
                                self.lock_low
                                if self.lock_active
                                else 0.0
                            ),
                            "lock_high": (
                                self.lock_high
                                if self.lock_active
                                else 0.0
                            ),
                            "lock_center": (
                                self.lock_center
                                if self.lock_active
                                else 0.0
                            ),
                            "sample_rate": self.sample_rate,
                            "classification": self.classification,
                            "classification_confidence": (
                                self.classification_confidence
                            ),
                            "calibration_progress": 1.0,
                            "calibration_remaining": 0.0,
                            "noise_floor_db": self.noise_floor_db,
                            "calibration_duration": 0.0,
                            "baseline_profile_peak_freq": (
                                self.noise_profile_peak_freq
                            ),
                            "lock_excess_db": lock_excess_db,
                        }
                    )

            except Exception as exc:
                message = f"Audio stream error: {exc}"

                # Any capture failure invalidates a partial room profile. The
                # next usable stream must prove live frames and then restart the
                # full baseline from zero.
                self.runtime_state.mark_recovering(str(exc))
                self.baseline_started_at = None
                self.baseline_valid_blocks = 0
                self.boot_complete_sent = False
                self._calibration_reset_needed = True
                self.baseline_interrupted.emit(str(exc))

                # PortAudio recovery belongs to the isolated boundary. The DSP
                # worker only invalidates its local epoch and requests a fresh
                # hardware transaction.
                boundary = self._hardware_boundary
                if boundary is not None:
                    boundary.request_reopen()

                self._report_worker_error(
                    "audio worker",
                    exc,
                )
                print(message)
                self.device_status.emit(
                    message,
                    False,
                )

                if self.is_recording:
                    self._finish_recording(
                        reason="stream_error"
                    )

                # Avoid rapidly hammering ALSA/PortAudio on failure.
                self._wake.wait(retry_delay)
                retry_delay = min(retry_delay * 2.0, 8.0)

            finally:
                if stream is not None:
                    try:
                        stream.stop()
                    except Exception:
                        pass

                    try:
                        stream.close()
                    except Exception:
                        pass

        if self.is_recording:
            self._finish_recording(
                reason="shutdown"
            )

    def stop(self):
        self.running = False
        self._wake.set()
        self.capture_data_ready.set()

        with self.lock:
            self.runtime_state.mark_stopping(
                "audio worker stop requested"
            )

        if not self.wait(5000):
            LOGGER.warning(
                "Audio worker did not stop within 5 s"
            )

    @staticmethod
    def _patch_wav_header(writer):
        """
        Make a still-open WAV file's header describe all audio written so far.
        """
        handle = getattr(
            writer,
            "_file",
            None,
        )

        if handle is None:
            return

        for name in (
            "_patchheader",
            "_patch_header",
        ):
            patch = getattr(
                writer,
                name,
                None,
            )

            if patch is not None:
                patch()
                handle.flush()
                return

        end = handle.tell()

        if end > 44:
            handle.seek(4)
            handle.write(
                struct.pack(
                    "<L",
                    end - 8,
                )
            )
            handle.seek(40)
            handle.write(
                struct.pack(
                    "<L",
                    end - 44,
                )
            )
            handle.seek(end)

        handle.flush()

    def _free_disk_mb(self):
        try:
            return (
                shutil.disk_usage(
                    LOG_DIR
                ).free
                / (
                    1024.0
                    * 1024.0
                )
            )
        except Exception as exc:
            report_warning(
                "disk-space query",
                str(exc),
            )
            return None

    def _disk_ok_to_record(self):
        free_mb = self._free_disk_mb()

        if (
            free_mb is None
            or free_mb
            >= MIN_FREE_DISK_MB
        ):
            return True

        now = time.monotonic()

        if (
            now - self._disk_warned_at
            >= 30.0
        ):
            self._disk_warned_at = now

            message = (
                f"Only {free_mb:.0f} MB free "
                f"(< {MIN_FREE_DISK_MB:.0f} MB); "
                "not starting a new recording"
            )

            report_warning(
                "disk space",
                message,
            )
            self.error_event.emit(
                "disk space",
                message,
            )

        return False

    def _checkpoint_recording(self):
        """
        Periodically make open WAV headers valid and protect the disk from a long
        recording that consumes the remaining free space.
        """
        interval = max(
            1,
            int(
                np.ceil(
                    (
                        WAV_CHECKPOINT_SECONDS
                        * self.sample_rate
                    )
                    / BLOCK_SIZE
                )
            ),
        )

        if (
            self.recorded_blocks
            % interval
            != 0
        ):
            return True

        for writer in (
            self.raw_writer,
            self.processed_writer,
        ):
            if writer is None:
                continue

            try:
                self._patch_wav_header(
                    writer
                )
            except Exception as exc:
                report_warning(
                    "WAV header checkpoint",
                    str(exc),
                )

        free_mb = self._free_disk_mb()

        if (
            free_mb is not None
            and free_mb
            < MIN_FREE_DISK_MB * 0.5
        ):
            message = (
                f"Only {free_mb:.0f} MB free; "
                "stopping the recording to protect the disk"
            )

            report_warning(
                "disk space",
                message,
            )
            self.error_event.emit(
                "disk space",
                message,
            )

            return False

        return True

    def _persist_room_profile(self):
        """
        Persist the learned room spectrum atomically for offline reconstruction.

        The profile is used as spectral shape information. The postprocessor scales
        it to the local recording noise level before blending it with the local
        noise estimate.
        """
        if self.noise_profile_db is None:
            return

        temp_path = Path(
            str(ROOM_PROFILE_PATH)
            + ".tmp.npz"
        )

        try:
            np.savez_compressed(
                str(temp_path),
                profile_db=np.asarray(
                    self.noise_profile_db,
                    dtype=np.float32,
                ),
                sample_rate=np.asarray(
                    [self.sample_rate],
                    dtype=np.int32,
                ),
                fft_size=np.asarray(
                    [BLOCK_SIZE],
                    dtype=np.int32,
                ),
                noise_floor_rms=np.asarray(
                    [self.noise_floor_rms],
                    dtype=np.float32,
                ),
                created_at=np.asarray(
                    [time.time()],
                    dtype=np.float64,
                ),
            )

            os.replace(
                str(temp_path),
                str(ROOM_PROFILE_PATH),
            )

            TELEMETRY_DAEMON.log_event(
                "ROOM_PROFILE_UPDATED",
                json.dumps(
                    {
                        "build": BCI_BUILD,
                        "sample_rate": int(
                            self.sample_rate
                        ),
                        "fft_size": int(
                            BLOCK_SIZE
                        ),
                        "noise_floor_dbfs": float(
                            self.noise_floor_db
                        ),
                        "path": str(
                            ROOM_PROFILE_PATH
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

        except Exception as exc:
            self._report_worker_error(
                "persisting room profile",
                exc,
            )

        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass


# ==============================================================================
# Spectrum widget
# ==============================================================================

class SpectrumWidget(QtWidgets.QWidget):
    """
    High-detail animated spectrum using the same metallic cyan/red neon visual
    language as the BCI boot screen.
    """

    DISPLAY_BINS = 96

    def __init__(self, parent=None, isolated_only=False):
        super().__init__(parent)

        self.isolated_only = bool(isolated_only)

        self.target_fft = np.full(
            self.DISPLAY_BINS,
            -120.0,
            dtype=np.float32,
        )
        self.fft_data = np.full(
            self.DISPLAY_BINS,
            -120.0,
            dtype=np.float32,
        )
        self.peak_hold = np.full(
            self.DISPLAY_BINS,
            -120.0,
            dtype=np.float32,
        )

        self.target_isolated_fft = None
        self.isolated_fft_data = None

        self.is_active = False
        self.calibrating = False

        self.target_lock_low = 0.0
        self.target_lock_high = 0.0
        self.target_lock_center = 0.0
        self.lock_low = 0.0
        self.lock_high = 0.0
        self.lock_center = 0.0

        self.sample_rate = 48000.0
        self.phase = 0.0
        self.scan_position = 0.0
        self.glaze_position = -0.20

        self.setMinimumHeight(320)
        # This widget paints every pixel of its surface itself. Marking it
        # opaque lets Qt skip needless background composition behind it.
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent,
            True,
        )
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            "background-color: #090d12;"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
        )

        self.animation_timer = QtCore.QTimer(self)
        self.animation_timer.setInterval(UI_FRAME_INTERVAL_MS)
        self.animation_timer.timeout.connect(
            self._animate_frame
        )
        self.animation_timer.start()

    @classmethod
    def _compress_spectrum(cls, spectrum_db):
        """Vectorized display-bin reduction.

        Script 53 split the FFT into 128 Python chunks and called
        ``np.percentile`` once per chunk on the GUI thread. Script 54 performs
        the same peak/body blend across all display rows in two vectorized
        NumPy reductions, eliminating thousands of tiny percentile calls/sec.
        """
        if spectrum_db is None:
            return None

        source = np.asarray(
            spectrum_db,
            dtype=np.float32,
        ).reshape(-1)

        if source.size == 0:
            return None

        bins = int(cls.DISPLAY_BINS)

        if source.size < bins:
            x_old = np.linspace(
                0.0,
                1.0,
                source.size,
                dtype=np.float32,
            )
            x_new = np.linspace(
                0.0,
                1.0,
                bins,
                dtype=np.float32,
            )
            return np.interp(
                x_new,
                x_old,
                source,
            ).astype(np.float32, copy=False)

        per_bin = max(1, source.size // bins)
        usable = bins * per_bin
        rows = source[:usable].reshape(bins, per_bin)

        local_peak = np.max(rows, axis=1)
        local_body = np.percentile(
            rows,
            72.0,
            axis=1,
        )

        values = (
            local_peak * 0.68
            + local_body * 0.32
        )

        return np.asarray(
            values,
            dtype=np.float32,
        )

    def update_data(
        self,
        spectrum_db,
        isolated_spectrum_db,
        is_active,
        lock_low,
        lock_high,
        lock_center,
        sample_rate,
        calibrating=False,
    ):
        if self.isolated_only:
            isolated = self._compress_spectrum(
                isolated_spectrum_db
            )
            self.target_fft = (
                isolated
                if isolated is not None
                else np.full(
                    self.DISPLAY_BINS,
                    -120.0,
                    dtype=np.float32,
                )
            )
            self.target_isolated_fft = None
        else:
            full = self._compress_spectrum(
                spectrum_db
            )
            if full is not None:
                self.target_fft = full

            self.target_isolated_fft = (
                self._compress_spectrum(
                    isolated_spectrum_db
                )
            )

        self.is_active = bool(
            is_active
        )
        self.calibrating = bool(
            calibrating
        )

        desired_interval = UI_FRAME_INTERVAL_MS
        if self.isolated_only and not self.is_active:
            desired_interval = SPECTRUM_IDLE_INTERVAL_MS
        if self.animation_timer.interval() != desired_interval:
            self.animation_timer.setInterval(desired_interval)

        self.target_lock_low = float(
            lock_low or 0.0
        )
        self.target_lock_high = float(
            lock_high or 0.0
        )
        self.target_lock_center = float(
            lock_center or 0.0
        )
        self.sample_rate = max(
            1.0,
            float(
                sample_rate or 48000.0
            ),
        )

    def _animate_frame(self):
        self.phase = (
            self.phase + 0.09
        ) % (2.0 * np.pi)

        self.scan_position = (
            self.scan_position + 0.006
        ) % 1.0

        self.glaze_position += 0.010
        if self.glaze_position > 1.30:
            self.glaze_position = -0.30

        if len(self.fft_data) != len(self.target_fft):
            self.fft_data = (
                self.target_fft.copy()
            )
            self.peak_hold = (
                self.target_fft.copy()
            )

        rising = (
            self.target_fft
            > self.fft_data
        )

        alpha = np.where(
            rising,
            0.47,
            0.16,
        ).astype(np.float32)

        self.fft_data += (
            self.target_fft
            - self.fft_data
        ) * alpha

        self.peak_hold = np.maximum(
            self.peak_hold - 0.48,
            self.fft_data,
        )

        if self.target_isolated_fft is not None:
            if (
                self.isolated_fft_data is None
                or len(
                    self.isolated_fft_data
                )
                != len(
                    self.target_isolated_fft
                )
            ):
                self.isolated_fft_data = (
                    self.target_isolated_fft.copy()
                )
            else:
                rising_iso = (
                    self.target_isolated_fft
                    > self.isolated_fft_data
                )

                iso_alpha = np.where(
                    rising_iso,
                    0.54,
                    0.20,
                ).astype(np.float32)

                self.isolated_fft_data += (
                    self.target_isolated_fft
                    - self.isolated_fft_data
                ) * iso_alpha
        else:
            self.isolated_fft_data = None

        lock_alpha = 0.20

        self.lock_low += (
            self.target_lock_low
            - self.lock_low
        ) * lock_alpha

        self.lock_high += (
            self.target_lock_high
            - self.lock_high
        ) * lock_alpha

        self.lock_center += (
            self.target_lock_center
            - self.lock_center
        ) * lock_alpha

        self.update()

    def _plot_rect(self):
        return QtCore.QRectF(
            54.0,
            12.0,
            max(
                1.0,
                self.width() - 68.0,
            ),
            max(
                1.0,
                self.height() - 42.0,
            ),
        )

    def _freq_to_x(
        self,
        freq,
        plot_rect=None,
    ):
        if plot_rect is None:
            plot_rect = self._plot_rect()

        nyquist = (
            self.sample_rate * 0.5
        )

        norm = max(
            0.0,
            min(
                1.0,
                float(freq)
                / max(nyquist, 1.0),
            ),
        )

        return (
            plot_rect.left()
            + norm
            * plot_rect.width()
        )

    @staticmethod
    def _db_to_y(
        db_value,
        plot_rect,
    ):
        floor_db = -100.0
        ceiling_db = 0.0

        norm = (
            float(db_value)
            - floor_db
        ) / (
            ceiling_db
            - floor_db
        )

        norm = max(
            0.0,
            min(1.0, norm),
        )

        return (
            plot_rect.bottom()
            - norm
            * plot_rect.height()
        )

    def _draw_background(
        self,
        painter,
        plot_rect,
    ):
        # Subtle metallic/radial background rather than a flat black panel.
        background = QtGui.QRadialGradient(
            plot_rect.center(),
            plot_rect.width() * 0.72,
        )
        background.setColorAt(
            0.00,
            QtGui.QColor(
                19,
                26,
                33,
                255,
            ),
        )
        background.setColorAt(
            0.62,
            QtGui.QColor(
                10,
                15,
                21,
                255,
            ),
        )
        background.setColorAt(
            1.00,
            QtGui.QColor(
                5,
                8,
                12,
                255,
            ),
        )

        painter.fillRect(
            self.rect(),
            QtGui.QBrush(background),
        )

        # Major/minor dB grid.
        for db in range(-100, 1, 10):
            y = self._db_to_y(
                db,
                plot_rect,
            )

            major = (
                db % 20 == 0
            )

            color = QtGui.QColor(
                55,
                72,
                84,
                92 if major else 48,
            )

            painter.setPen(
                QtGui.QPen(
                    color,
                    1.0,
                    QtCore.Qt.PenStyle.SolidLine
                    if major
                    else QtCore.Qt.PenStyle.DotLine,
                )
            )

            painter.drawLine(
                QtCore.QPointF(
                    plot_rect.left(),
                    y,
                ),
                QtCore.QPointF(
                    plot_rect.right(),
                    y,
                ),
            )

            painter.setPen(
                QtGui.QColor(
                    139,
                    148,
                    158,
                    205,
                )
            )

            font = painter.font()
            font.setPointSize(11)
            painter.setFont(font)

            painter.drawText(
                QtCore.QRectF(
                    3.0,
                    y - 8.0,
                    47.0,
                    16.0,
                ),
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                f"{db}",
            )

        # More detailed frequency grid: sixteen divisions.
        for division in range(17):
            ratio = (
                division / 16.0
            )

            x = (
                plot_rect.left()
                + ratio
                * plot_rect.width()
            )

            major = (
                division % 4 == 0
            )

            cyan_component = (
                72 if major else 46
            )
            red_component = (
                58 if major else 34
            )

            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(
                        cyan_component,
                        90,
                        100,
                        65 if major else 34,
                    ),
                    1.0,
                    QtCore.Qt.PenStyle.SolidLine
                    if major
                    else QtCore.Qt.PenStyle.DotLine,
                )
            )

            painter.drawLine(
                QtCore.QPointF(
                    x,
                    plot_rect.top(),
                ),
                QtCore.QPointF(
                    x,
                    plot_rect.bottom(),
                ),
            )

            if major:
                painter.setPen(
                    QtGui.QPen(
                        QtGui.QColor(
                            red_component,
                            45,
                            53,
                            34,
                        ),
                        1.0,
                    )
                )
                painter.drawLine(
                    QtCore.QPointF(
                        x + 1.0,
                        plot_rect.top(),
                    ),
                    QtCore.QPointF(
                        x + 1.0,
                        plot_rect.bottom(),
                    ),
                )

        # Plot outline.
        painter.setBrush(
            QtCore.Qt.BrushStyle.NoBrush
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    74,
                    88,
                    99,
                    190,
                ),
                1.0,
            )
        )
        painter.drawRect(
            plot_rect
        )

    def _draw_scan(
        self,
        painter,
        plot_rect,
    ):
        scan_x = (
            plot_rect.left()
            + self.scan_position
            * plot_rect.width()
        )

        pulse = (
            0.65
            + 0.35
            * np.sin(
                self.phase * 1.7
            )
        )

        glow = QtGui.QLinearGradient(
            scan_x - 28.0,
            0.0,
            scan_x + 28.0,
            0.0,
        )

        if self.isolated_only:
            center_color = QtGui.QColor(
                255,
                42,
                68,
                int(52 * pulse),
            )
        else:
            center_color = QtGui.QColor(
                0,
                238,
                255,
                int(52 * pulse),
            )

        glow.setColorAt(
            0.0,
            QtGui.QColor(
                center_color.red(),
                center_color.green(),
                center_color.blue(),
                0,
            ),
        )
        glow.setColorAt(
            0.5,
            center_color,
        )
        glow.setColorAt(
            1.0,
            QtGui.QColor(
                center_color.red(),
                center_color.green(),
                center_color.blue(),
                0,
            ),
        )

        painter.fillRect(
            QtCore.QRectF(
                scan_x - 28.0,
                plot_rect.top(),
                56.0,
                plot_rect.height(),
            ),
            QtGui.QBrush(glow),
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    238,
                    252,
                    255,
                    92
                    if not self.calibrating
                    else 145,
                ),
                1.0,
            )
        )

        painter.drawLine(
            QtCore.QPointF(
                scan_x,
                plot_rect.top(),
            ),
            QtCore.QPointF(
                scan_x,
                plot_rect.bottom(),
            ),
        )

    def _draw_waiting(
        self,
        painter,
        plot_rect,
    ):
        center_y = (
            plot_rect.center().y()
        )

        points = []

        steps = max(
            96,
            int(plot_rect.width() / 6),
        )

        for index in range(steps):
            ratio = (
                index
                / max(
                    1,
                    steps - 1,
                )
            )

            x = (
                plot_rect.left()
                + ratio
                * plot_rect.width()
            )

            envelope = np.exp(
                -(
                    (
                        ratio
                        - self.scan_position
                    )
                    / 0.15
                ) ** 2
            )

            y = (
                center_y
                + np.sin(
                    ratio * 34.0
                    + self.phase * 3.2
                )
                * 12.0
                * envelope
            )

            points.append(
                QtCore.QPointF(
                    x,
                    y,
                )
            )

        polygon = QtGui.QPolygonF(
            points
        )

        painter.setBrush(
            QtCore.Qt.BrushStyle.NoBrush
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    238,
                    255,
                    55,
                ),
                7.0,
            )
        )
        painter.drawPolyline(
            polygon
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    255,
                    42,
                    68,
                    72,
                ),
                4.0,
            )
        )
        painter.drawPolyline(
            polygon.translated(
                2.0,
                0.0,
            )
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    232,
                    244,
                    250,
                    190,
                ),
                1.2,
            )
        )
        painter.drawPolyline(
            polygon
        )

        dots = "." * (
            1
            + int(
                self.phase * 1.4
            ) % 3
        )

        font = painter.font()
        font.setPointSize(13)
        font.setBold(True)
        painter.setFont(font)

        painter.setPen(
            QtGui.QColor(
                168,
                180,
                190,
                220,
            )
        )

        painter.drawText(
            plot_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "WAITING FOR TRIGGER / "
            f"SIGNAL LOCK{dots}",
        )

    def _draw_lock_band(
        self,
        painter,
        plot_rect,
    ):
        if (
            not self.is_active
            or self.lock_high
            <= self.lock_low
        ):
            return

        x_low = self._freq_to_x(
            self.lock_low,
            plot_rect,
        )
        x_high = self._freq_to_x(
            self.lock_high,
            plot_rect,
        )
        x_center = self._freq_to_x(
            self.lock_center,
            plot_rect,
        )

        pulse = (
            0.5
            + 0.5
            * np.sin(
                self.phase
            )
        )

        band_rect = QtCore.QRectF(
            x_low,
            plot_rect.top(),
            max(
                1.0,
                x_high - x_low,
            ),
            plot_rect.height(),
        )

        fill = QtGui.QLinearGradient(
            x_low,
            0.0,
            x_high,
            0.0,
        )
        fill.setColorAt(
            0.00,
            QtGui.QColor(
                0,
                238,
                255,
                int(
                    22
                    + pulse * 18
                ),
            ),
        )
        fill.setColorAt(
            0.48,
            QtGui.QColor(
                105,
                115,
                125,
                int(
                    18
                    + pulse * 12
                ),
            ),
        )
        fill.setColorAt(
            1.00,
            QtGui.QColor(
                255,
                42,
                68,
                int(
                    22
                    + pulse * 18
                ),
            ),
        )

        painter.fillRect(
            band_rect,
            QtGui.QBrush(fill),
        )

        # Multiple glow passes on both lock edges.
        for width, opacity in (
            (10.0, 26),
            (6.0, 52),
            (2.0, 220),
        ):
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(
                        0,
                        238,
                        255,
                        int(
                            opacity
                            * (
                                0.72
                                + 0.28
                                * pulse
                            )
                        ),
                    ),
                    width,
                )
            )
            painter.drawLine(
                QtCore.QPointF(
                    x_low,
                    plot_rect.top(),
                ),
                QtCore.QPointF(
                    x_low,
                    plot_rect.bottom(),
                ),
            )

            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(
                        255,
                        42,
                        68,
                        int(
                            opacity
                            * (
                                0.72
                                + 0.28
                                * pulse
                            )
                        ),
                    ),
                    width,
                )
            )
            painter.drawLine(
                QtCore.QPointF(
                    x_high,
                    plot_rect.top(),
                ),
                QtCore.QPointF(
                    x_high,
                    plot_rect.bottom(),
                ),
            )

        # Metallic-white lock center.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    232,
                    240,
                    245,
                    int(
                        170
                        + pulse * 75
                    ),
                ),
                1.4,
                QtCore.Qt.PenStyle.DashLine,
            )
        )

        painter.drawLine(
            QtCore.QPointF(
                x_center,
                plot_rect.top(),
            ),
            QtCore.QPointF(
                x_center,
                plot_rect.bottom(),
            ),
        )

    def _spectrum_points(
        self,
        data,
        plot_rect,
    ):
        points = []

        count = len(data)

        if count == 0:
            return points

        for index, db_value in enumerate(data):
            ratio = (
                index
                / max(
                    1,
                    count - 1,
                )
            )

            x = (
                plot_rect.left()
                + ratio
                * plot_rect.width()
            )

            y = self._db_to_y(
                db_value,
                plot_rect,
            )

            points.append(
                QtCore.QPointF(
                    x,
                    y,
                )
            )

        return points

    def _draw_spectrum(
        self,
        painter,
        plot_rect,
    ):
        count = len(
            self.fft_data
        )

        if count == 0:
            return

        bar_width = (
            plot_rect.width()
            / count
        )

        # Broad spectrum uses cyan as primary, isolated uses red as primary.
        if self.isolated_only:
            primary = QtGui.QColor(
                255,
                42,
                68,
                235,
            )
            secondary = QtGui.QColor(
                0,
                238,
                255,
                175,
            )
        else:
            primary = QtGui.QColor(
                0,
                238,
                255,
                235,
            )
            secondary = QtGui.QColor(
                255,
                42,
                68,
                150,
            )

        glaze_x = (
            plot_rect.left()
            + self.glaze_position
            * plot_rect.width()
        )

        # Dense metallic/neon bars. The gradient is shared by the entire
        # spectrum frame instead of allocating a new QLinearGradient for every
        # bar on every repaint.
        gradient = QtGui.QLinearGradient(
            0.0,
            plot_rect.top(),
            0.0,
            plot_rect.bottom(),
        )

        top = QtGui.QColor(primary)
        top.setAlpha(238)
        middle = QtGui.QColor(150, 164, 176, 150)
        bottom = QtGui.QColor(primary)
        bottom.setAlpha(46)

        gradient.setColorAt(0.00, top)
        gradient.setColorAt(0.18, middle)
        gradient.setColorAt(
            0.42,
            QtGui.QColor(46, 58, 67, 145),
        )
        gradient.setColorAt(1.00, bottom)

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(gradient))

        for index, db_value in enumerate(
            self.fft_data
        ):
            y = self._db_to_y(
                db_value,
                plot_rect,
            )

            bar_height = max(
                0.0,
                plot_rect.bottom() - y,
            )

            x = (
                plot_rect.left()
                + index * bar_width
            )

            if bar_height <= 0.0:
                continue

            rect = QtCore.QRectF(
                x + 0.45,
                y,
                max(
                    0.7,
                    bar_width - 0.9,
                ),
                bar_height,
            )

            painter.drawRoundedRect(
                rect,
                0.8,
                0.8,
            )

            # Bright moving metallic sheen.
            distance = abs(
                rect.center().x()
                - glaze_x
            )

            if distance < 32.0:
                strength = (
                    1.0
                    - distance / 32.0
                )

                painter.fillRect(
                    rect,
                    QtGui.QColor(
                        245,
                        252,
                        255,
                        int(70 * strength),
                    ),
                )

        points = self._spectrum_points(
            self.fft_data,
            plot_rect,
        )

        if len(points) > 1:
            polygon = QtGui.QPolygonF(
                points
            )

            # Wide cyan/red halo.
            painter.setBrush(
                QtCore.Qt.BrushStyle.NoBrush
            )

            for width, alpha_value in (
                (10.0, 28),
                (6.0, 48),
                (3.2, 90),
            ):
                glow = QtGui.QColor(
                    primary
                )
                glow.setAlpha(
                    alpha_value
                )

                painter.setPen(
                    QtGui.QPen(
                        glow,
                        width,
                        QtCore.Qt.PenStyle.SolidLine,
                        QtCore.Qt.PenCapStyle.RoundCap,
                        QtCore.Qt.PenJoinStyle.RoundJoin,
                    )
                )
                painter.drawPolyline(
                    polygon
                )

            # Opposite-color chromatic edge offset.
            chroma = QtGui.QPolygonF(
                [
                    QtCore.QPointF(
                        p.x() + 1.5,
                        p.y() + 0.7,
                    )
                    for p in points
                ]
            )

            chroma_color = QtGui.QColor(
                secondary
            )
            chroma_color.setAlpha(
                128
            )

            painter.setPen(
                QtGui.QPen(
                    chroma_color,
                    1.6,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                    QtCore.Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPolyline(
                chroma
            )

            # Crisp metallic-white core trace.
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(
                        226,
                        238,
                        244,
                        222,
                    ),
                    1.15,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                    QtCore.Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPolyline(
                polygon
            )

        # Peak-hold indicators with opposite accent color.
        painter.setPen(
            QtGui.QPen(
                secondary,
                1.0,
            )
        )

        for index, db_value in enumerate(
            self.peak_hold
        ):
            y = self._db_to_y(
                db_value,
                plot_rect,
            )

            x1 = (
                plot_rect.left()
                + index * bar_width
            )
            x2 = (
                x1
                + max(
                    1.0,
                    bar_width - 0.8,
                )
            )

            painter.drawLine(
                QtCore.QPointF(
                    x1,
                    y,
                ),
                QtCore.QPointF(
                    x2,
                    y,
                ),
            )

    def _draw_isolated_overlay(
        self,
        painter,
        plot_rect,
    ):
        if (
            self.isolated_only
            or not self.is_active
            or self.isolated_fft_data is None
            or len(
                self.isolated_fft_data
            ) < 2
        ):
            return

        points = self._spectrum_points(
            self.isolated_fft_data,
            plot_rect,
        )

        polygon = QtGui.QPolygonF(
            points
        )

        painter.setBrush(
            QtCore.Qt.BrushStyle.NoBrush
        )

        for width, alpha_value in (
            (11.0, 25),
            (7.0, 45),
            (4.0, 72),
        ):
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(
                        255,
                        42,
                        68,
                        alpha_value,
                    ),
                    width,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                    QtCore.Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPolyline(
                polygon
            )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    255,
                    64,
                    88,
                    235,
                ),
                2.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPolyline(
            polygon
        )

        # Cyan chromatic offset matching the boot lettering.
        offset = QtGui.QPolygonF(
            [
                QtCore.QPointF(
                    p.x() - 1.5,
                    p.y(),
                )
                for p in points
            ]
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    238,
                    255,
                    138,
                ),
                1.2,
            )
        )
        painter.drawPolyline(
            offset
        )

    def _draw_frequency_labels(
        self,
        painter,
        plot_rect,
    ):
        painter.setPen(
            QtGui.QColor(
                160,
                172,
                183,
                225,
            )
        )

        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)

        nyquist = (
            self.sample_rate * 0.5
        )

        # Nine labels instead of five for more useful visual resolution.
        for index in range(9):
            freq = (
                nyquist
                * index
                / 8.0
            )

            x = self._freq_to_x(
                freq,
                plot_rect,
            )

            label = (
                f"{freq / 1000.0:.1f}k"
                if freq >= 1000.0
                else f"{freq:.0f}"
            )

            painter.drawText(
                QtCore.QRectF(
                    x - 25.0,
                    plot_rect.bottom() + 4.0,
                    50.0,
                    19.0,
                ),
                QtCore.Qt.AlignmentFlag.AlignHCenter
                | QtCore.Qt.AlignmentFlag.AlignTop,
                label,
            )

        # Unit labels.
        painter.setPen(
            QtGui.QColor(
                107,
                122,
                135,
                190,
            )
        )

        tiny = painter.font()
        tiny.setPointSize(8)
        tiny.setBold(True)
        painter.setFont(tiny)

        painter.drawText(
            5,
            13,
            "dB",
        )

        painter.drawText(
            int(
                plot_rect.right() - 18
            ),
            self.height() - 4,
            "Hz",
        )

    def _draw_lock_readout(
        self,
        painter,
        plot_rect,
    ):
        if (
            not self.is_active
            or self.lock_high
            <= self.lock_low
        ):
            return

        lock_text = (
            f"LOCK {self.lock_low:.0f}–"
            f"{self.lock_high:.0f} Hz   "
            f"CENTER {self.lock_center:.0f} Hz"
        )

        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)

        metrics = painter.fontMetrics()

        box = QtCore.QRectF(
            plot_rect.left() + 10.0,
            plot_rect.top() + 9.0,
            min(
                metrics.horizontalAdvance(
                    lock_text
                ) + 22.0,
                max(
                    1.0,
                    plot_rect.width()
                    - 20.0,
                ),
            ),
            metrics.height() + 12.0,
        )

        bg = QtGui.QLinearGradient(
            box.left(),
            0.0,
            box.right(),
            0.0,
        )
        bg.setColorAt(
            0.0,
            QtGui.QColor(
                0,
                238,
                255,
                32,
            ),
        )
        bg.setColorAt(
            0.50,
            QtGui.QColor(
                22,
                29,
                35,
                230,
            ),
        )
        bg.setColorAt(
            1.0,
            QtGui.QColor(
                255,
                42,
                68,
                32,
            ),
        )

        painter.fillRect(
            box,
            QtGui.QBrush(bg),
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    238,
                    255,
                    175,
                ),
                1.0,
            )
        )
        painter.drawLine(
            box.topLeft(),
            box.bottomLeft(),
        )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    255,
                    42,
                    68,
                    175,
                ),
                1.0,
            )
        )
        painter.drawLine(
            box.topRight(),
            box.bottomRight(),
        )

        painter.setPen(
            QtGui.QColor(
                230,
                239,
                244,
                240,
            )
        )

        painter.drawText(
            box.adjusted(
                10.0,
                0.0,
                -8.0,
                0.0,
            ),
            QtCore.Qt.AlignmentFlag.AlignVCenter
            | QtCore.Qt.AlignmentFlag.AlignLeft,
            lock_text,
        )

    def paintEvent(self, event):
        painter = QtGui.QPainter(
            self
        )

        painter.setRenderHint(
            QtGui.QPainter.RenderHint.Antialiasing,
            True,
        )
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.TextAntialiasing,
            True,
        )

        plot_rect = (
            self._plot_rect()
        )

        self._draw_background(
            painter,
            plot_rect,
        )

        self._draw_scan(
            painter,
            plot_rect,
        )

        if (
            self.isolated_only
            and not self.is_active
        ):
            self._draw_waiting(
                painter,
                plot_rect,
            )
            self._draw_frequency_labels(
                painter,
                plot_rect,
            )
            painter.end()
            return

        self._draw_lock_band(
            painter,
            plot_rect,
        )

        self._draw_spectrum(
            painter,
            plot_rect,
        )

        self._draw_isolated_overlay(
            painter,
            plot_rect,
        )

        self._draw_frequency_labels(
            painter,
            plot_rect,
        )

        self._draw_lock_readout(
            painter,
            plot_rect,
        )

        painter.end()

    def showEvent(self, event):
        self.animation_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.animation_timer.stop()
        super().hideEvent(event)


# ==============================================================================
# BCI boot screen
# ==============================================================================

class BCIBootVisual(QtWidgets.QWidget):
    """
    Animated BCI boot mark.

    The three letters reveal one at a time over the 60-second room baseline:
      B -> first third
      C -> second third
      I -> final third

    A rotating gear and circular progress arc visualize the active listening
    process. A moving highlight/glaze sweeps across revealed lettering.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.progress = 0.0
        self.gear_angle = 0.0
        self.glaze_position = -0.25
        self.glow_phase = 0.0

        self.setMinimumHeight(220)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

        self.animation_timer = QtCore.QTimer(self)
        self.animation_timer.setInterval(UI_FRAME_INTERVAL_MS)  # target ~60 FPS
        self.animation_timer.timeout.connect(
            self._animate_frame
        )
        self.animation_timer.start()

    def set_progress(self, progress):
        self.progress = max(
            0.0,
            min(1.0, float(progress)),
        )
        self.update()

    @staticmethod
    def _smoothstep(value):
        value = max(0.0, min(1.0, float(value)))
        return value * value * (3.0 - 2.0 * value)

    def _letter_alpha(self, index):
        # Each letter owns one third of the full baseline.
        segment_start = index / 3.0
        segment_end = (index + 1) / 3.0

        local = (
            (self.progress - segment_start)
            / max(segment_end - segment_start, 1e-6)
        )

        return self._smoothstep(local)

    def _animate_frame(self):
        # Smooth, slower mechanical rotation. The motion eases as calibration
        # approaches completion rather than looking like a game sprite.
        if self.progress < 1.0:
            speed = (
                1.10
                + (1.0 - self.progress) * 0.45
            )
        else:
            speed = 0.28

        self.gear_angle = (
            self.gear_angle + speed
        ) % 360.0

        # A slow optical highlight crosses the chrome rather than a fast white wipe.
        self.glaze_position += 0.0038
        if self.glaze_position > 1.30:
            self.glaze_position = -0.30

        self.glow_phase = (
            self.glow_phase + 0.027
        ) % (2.0 * np.pi)

        self.update()

    def _letter_path(self, letter, rect):
        cache = self.__dict__.setdefault(
            "_glyph_cache",
            {},
        )

        key = (
            letter,
            rect.x(),
            rect.y(),
            rect.width(),
            rect.height(),
        )

        cached = cache.get(key)

        if cached is not None:
            return cached

        if len(cache) > 16:
            cache.clear()

        font = QtGui.QFont(UI_BRAND_FONT_FAMILY)
        font.setStyleHint(
            QtGui.QFont.StyleHint.TypeWriter
        )
        font.setWeight(
            QtGui.QFont.Weight.Black
        )
        font.setPixelSize(144)

        raw = QtGui.QPainterPath()
        raw.addText(
            0.0,
            0.0,
            font,
            letter,
        )

        bounds = raw.boundingRect()

        transform = QtGui.QTransform()
        transform.translate(
            rect.center().x()
            - bounds.center().x(),
            rect.center().y()
            - bounds.center().y(),
        )

        path = transform.map(raw)
        cache[key] = path
        return path

    def _draw_letter(
        self,
        painter,
        letter,
        rect,
        alpha,
        letter_index,
    ):
        if alpha <= 0.001:
            return

        path = self._letter_path(
            letter,
            rect,
        )
        bounds = path.boundingRect()

        pulse = (
            0.92
            + 0.08
            * np.sin(
                self.glow_phase
                + letter_index * 0.55
            )
        )

        # A restrained dark depth layer gives the chrome body physical separation.
        shadow_path = QtGui.QTransform.fromTranslate(
            0.0,
            3.0,
        ).map(path)

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    0,
                    0,
                    int(125 * alpha),
                ),
                5.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(shadow_path)

        # Soft two-tone ambient bloom. Broad glows stay low-opacity to avoid the
        # fuzzy/chalk-outline look of the previous renderer.
        cyan_path = QtGui.QTransform.fromTranslate(
            -1.1,
            0.0,
        ).map(path)
        red_path = QtGui.QTransform.fromTranslate(
            1.1,
            0.0,
        ).map(path)

        for glow_path, color in (
            (
                cyan_path,
                QtGui.QColor(
                    0,
                    231,
                    255,
                    int(36 * alpha * pulse),
                ),
            ),
            (
                red_path,
                QtGui.QColor(
                    255,
                    45,
                    82,
                    int(30 * alpha * pulse),
                ),
            ),
        ):
            painter.setPen(
                QtGui.QPen(
                    color,
                    10.0,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                    QtCore.Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(glow_path)

        # Precision chrome: broad, continuous tonal transitions instead of brushed
        # micro-lines. This reads like polished glass/metal at normal UI scale.
        chrome = QtGui.QLinearGradient(
            bounds.left(),
            bounds.top(),
            bounds.right(),
            bounds.bottom(),
        )
        chrome.setColorAt(
            0.00,
            QtGui.QColor(
                244,
                250,
                253,
                int(255 * alpha),
            ),
        )
        chrome.setColorAt(
            0.12,
            QtGui.QColor(
                126,
                145,
                160,
                int(255 * alpha),
            ),
        )
        chrome.setColorAt(
            0.28,
            QtGui.QColor(
                31,
                40,
                50,
                int(255 * alpha),
            ),
        )
        chrome.setColorAt(
            0.44,
            QtGui.QColor(
                224,
                236,
                243,
                int(255 * alpha),
            ),
        )
        chrome.setColorAt(
            0.59,
            QtGui.QColor(
                79,
                95,
                108,
                int(255 * alpha),
            ),
        )
        chrome.setColorAt(
            0.77,
            QtGui.QColor(
                246,
                251,
                253,
                int(255 * alpha),
            ),
        )
        chrome.setColorAt(
            1.00,
            QtGui.QColor(
                28,
                35,
                43,
                int(255 * alpha),
            ),
        )

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.fillPath(
            path,
            QtGui.QBrush(chrome),
        )

        # Glass top-coat clipped inside the glyph. A quiet upper reflection gives
        # the letters a premium polished surface without adding texture noise.
        painter.save()
        painter.setClipPath(path)

        glass = QtGui.QLinearGradient(
            0.0,
            bounds.top(),
            0.0,
            bounds.bottom(),
        )
        glass.setColorAt(
            0.00,
            QtGui.QColor(
                255,
                255,
                255,
                int(92 * alpha),
            ),
        )
        glass.setColorAt(
            0.24,
            QtGui.QColor(
                198,
                241,
                255,
                int(38 * alpha),
            ),
        )
        glass.setColorAt(
            0.50,
            QtGui.QColor(
                255,
                255,
                255,
                0,
            ),
        )
        glass.setColorAt(
            1.00,
            QtGui.QColor(
                255,
                255,
                255,
                int(18 * alpha),
            ),
        )

        painter.fillRect(
            bounds,
            QtGui.QBrush(glass),
        )

        # Slow cinematic glaze.
        total_width = max(
            1.0,
            float(self.width()),
        )
        glaze_x = (
            self.glaze_position
            * total_width
        )
        glaze_half_width = max(
            36.0,
            rect.width() * 0.18,
        )

        glaze = QtGui.QLinearGradient(
            glaze_x - glaze_half_width,
            0.0,
            glaze_x + glaze_half_width,
            0.0,
        )
        glaze.setColorAt(
            0.00,
            QtGui.QColor(255, 255, 255, 0),
        )
        glaze.setColorAt(
            0.40,
            QtGui.QColor(
                205,
                245,
                255,
                int(24 * alpha),
            ),
        )
        glaze.setColorAt(
            0.50,
            QtGui.QColor(
                255,
                255,
                255,
                int(145 * alpha),
            ),
        )
        glaze.setColorAt(
            0.60,
            QtGui.QColor(
                255,
                222,
                230,
                int(24 * alpha),
            ),
        )
        glaze.setColorAt(
            1.00,
            QtGui.QColor(255, 255, 255, 0),
        )

        painter.fillRect(
            bounds,
            QtGui.QBrush(glaze),
        )
        painter.restore()

        # Precision rim.
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    236,
                    246,
                    252,
                    int(205 * alpha),
                ),
                1.15,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(path)

        # Clean neon edge-light: crisp, narrow, and intentionally asymmetric.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    238,
                    255,
                    int(205 * alpha),
                ),
                1.55,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(cyan_path)

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    255,
                    54,
                    88,
                    int(188 * alpha),
                ),
                1.35,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(red_path)

    def _build_gear_path(
        self,
        radius,
        teeth=16,
    ):
        path = QtGui.QPainterPath()

        outer = radius
        root = radius * 0.79

        points = []

        # Four vertices per tooth gives the tooth flank more mechanical shape
        # than simple rectangles.
        for tooth in range(teeth):
            base_angle = (
                (2.0 * np.pi * tooth)
                / teeth
            )

            for fraction, current_radius in (
                (0.00, root),
                (0.17, outer),
                (0.58, outer),
                (0.78, root),
            ):
                angle = (
                    base_angle
                    + fraction
                    * (2.0 * np.pi / teeth)
                )

                points.append(
                    QtCore.QPointF(
                        np.cos(angle)
                        * current_radius,
                        np.sin(angle)
                        * current_radius,
                    )
                )

        if points:
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            path.closeSubpath()

        return path

    def _draw_gear(
        self,
        painter,
        center,
        radius,
    ):
        painter.save()
        painter.translate(center)
        painter.rotate(self.gear_angle)

        gear_path = self._build_gear_path(
            radius,
            teeth=18,
        )

        # Deep floating shadow.
        shadow = QtGui.QTransform.fromTranslate(
            0.0,
            radius * 0.08,
        ).map(gear_path)

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(
            QtGui.QColor(
                0,
                0,
                0,
                105,
            )
        )
        painter.drawPath(shadow)

        # Machined outer body.
        outer_metal = QtGui.QRadialGradient(
            QtCore.QPointF(
                -radius * 0.30,
                -radius * 0.34,
            ),
            radius * 1.42,
        )
        outer_metal.setColorAt(
            0.00,
            QtGui.QColor(247, 251, 253, 255),
        )
        outer_metal.setColorAt(
            0.22,
            QtGui.QColor(145, 159, 171, 255),
        )
        outer_metal.setColorAt(
            0.48,
            QtGui.QColor(42, 52, 62, 255),
        )
        outer_metal.setColorAt(
            0.70,
            QtGui.QColor(111, 126, 138, 255),
        )
        outer_metal.setColorAt(
            1.00,
            QtGui.QColor(17, 23, 30, 255),
        )

        painter.setBrush(
            QtGui.QBrush(outer_metal)
        )
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    224,
                    235,
                    242,
                    215,
                ),
                1.15,
            )
        )
        painter.drawPath(gear_path)

        # Recessed center cavity.
        cavity = QtGui.QRadialGradient(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.68,
        )
        cavity.setColorAt(
            0.00,
            QtGui.QColor(20, 27, 34, 255),
        )
        cavity.setColorAt(
            0.72,
            QtGui.QColor(10, 15, 21, 255),
        )
        cavity.setColorAt(
            1.00,
            QtGui.QColor(58, 70, 80, 255),
        )

        painter.setBrush(
            QtGui.QBrush(cavity)
        )
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    150,
                    170,
                    184,
                    150,
                ),
                1.1,
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.66,
            radius * 0.66,
        )

        # Six swept turbine blades. They read more like a precision mechanism than
        # flat rectangular spokes.
        blade_fill = QtGui.QLinearGradient(
            -radius * 0.15,
            -radius * 0.58,
            radius * 0.24,
            radius * 0.18,
        )
        blade_fill.setColorAt(
            0.00,
            QtGui.QColor(225, 235, 241, 235),
        )
        blade_fill.setColorAt(
            0.40,
            QtGui.QColor(102, 119, 132, 235),
        )
        blade_fill.setColorAt(
            1.00,
            QtGui.QColor(30, 39, 48, 245),
        )

        painter.setBrush(
            QtGui.QBrush(blade_fill)
        )
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    205,
                    220,
                    229,
                    120,
                ),
                0.8,
            )
        )

        for blade in range(6):
            painter.save()
            painter.rotate(
                blade * 60.0
            )

            blade_path = QtGui.QPainterPath()
            blade_path.moveTo(
                -radius * 0.09,
                -radius * 0.15,
            )
            blade_path.cubicTo(
                -radius * 0.16,
                -radius * 0.28,
                -radius * 0.16,
                -radius * 0.50,
                -radius * 0.03,
                -radius * 0.57,
            )
            blade_path.cubicTo(
                radius * 0.11,
                -radius * 0.49,
                radius * 0.16,
                -radius * 0.30,
                radius * 0.10,
                -radius * 0.12,
            )
            blade_path.closeSubpath()

            painter.drawPath(blade_path)
            painter.restore()

        # Floating hub.
        hub = QtGui.QRadialGradient(
            QtCore.QPointF(
                -radius * 0.08,
                -radius * 0.10,
            ),
            radius * 0.34,
        )
        hub.setColorAt(
            0.00,
            QtGui.QColor(247, 251, 253, 255),
        )
        hub.setColorAt(
            0.44,
            QtGui.QColor(113, 129, 141, 255),
        )
        hub.setColorAt(
            1.00,
            QtGui.QColor(26, 34, 42, 255),
        )

        painter.setBrush(QtGui.QBrush(hub))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    230,
                    239,
                    245,
                    190,
                ),
                1.0,
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.30,
            radius * 0.30,
        )

        # Central aperture with an optical glass tint.
        bore = QtGui.QRadialGradient(
            QtCore.QPointF(
                -radius * 0.02,
                -radius * 0.03,
            ),
            radius * 0.13,
        )
        bore.setColorAt(
            0.00,
            QtGui.QColor(12, 41, 48, 255),
        )
        bore.setColorAt(
            0.65,
            QtGui.QColor(3, 16, 21, 255),
        )
        bore.setColorAt(
            1.00,
            QtGui.QColor(0, 3, 6, 255),
        )

        painter.setBrush(QtGui.QBrush(bore))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    224,
                    242,
                    110,
                ),
                1.0,
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.115,
            radius * 0.115,
        )

        # Controlled specular highlight.
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    255,
                    255,
                    255,
                    72,
                ),
                1.6,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            QtCore.QRectF(
                -radius * 0.76,
                -radius * 0.76,
                radius * 1.52,
                radius * 1.52,
            ),
            36 * 16,
            82 * 16,
        )

        painter.restore()

        # Stationary calibration halo around the rotating mechanism.
        arc_rect = QtCore.QRectF(
            center.x() - radius * 1.30,
            center.y() - radius * 1.30,
            radius * 2.60,
            radius * 2.60,
        )

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        # Diffuse halo.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    226,
                    255,
                    28,
                ),
                11.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            arc_rect,
            90 * 16,
            int(
                -360
                * 16
                * self.progress
            ),
        )

        # Dark precision track.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    68,
                    81,
                    91,
                    120,
                ),
                2.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            arc_rect,
            90 * 16,
            -360 * 16,
        )

        # Primary cyan progress line.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    0,
                    238,
                    255,
                    235,
                ),
                3.2,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            arc_rect,
            90 * 16,
            int(
                -360
                * 16
                * self.progress
            ),
        )

        # Fine red inner accent.
        accent_rect = arc_rect.adjusted(
            4.5,
            4.5,
            -4.5,
            -4.5,
        )
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    255,
                    48,
                    84,
                    142,
                ),
                1.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            accent_rect,
            90 * 16,
            int(
                -360
                * 16
                * self.progress
            ),
        )

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)

        painter.setRenderHint(
            QtGui.QPainter.RenderHint.Antialiasing,
            True,
        )
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.TextAntialiasing,
            True,
        )
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform,
            True,
        )

        self._draw_polished_backdrop(
            painter
        )

        width = self.width()
        height = self.height()

        logo_width = int(
            width * 0.70
        )

        gap = max(
            10,
            int(
                logo_width * 0.022
            ),
        )

        letter_width = max(
            88,
            int(
                (
                    logo_width
                    - gap * 4
                )
                / 3
            ),
        )

        letters = (
            "B",
            "C",
            "I",
        )

        for index, letter in enumerate(
            letters
        ):
            left = (
                gap
                + index
                * (
                    letter_width
                    + gap
                )
            )

            rect = QtCore.QRect(
                left,
                21,
                letter_width,
                height - 42,
            )

            self._draw_letter(
                painter,
                letter,
                rect,
                self._letter_alpha(
                    index
                ),
                index,
            )

        gear_center = QtCore.QPointF(
            width * 0.845,
            height * 0.50,
        )

        gear_radius = min(
            height * 0.285,
            width * 0.073,
        )

        self._draw_gear(
            painter,
            gear_center,
            gear_radius,
        )

        painter.end()

    def showEvent(self, event):
        self.animation_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.animation_timer.stop()
        super().hideEvent(event)

    def _draw_polished_backdrop(self, painter):
        w = float(self.width())
        h = float(self.height())

        # Deep cinematic base.
        base = QtGui.QLinearGradient(
            0.0,
            0.0,
            w,
            h,
        )
        base.setColorAt(
            0.00,
            QtGui.QColor(8, 13, 19, 248),
        )
        base.setColorAt(
            0.48,
            QtGui.QColor(13, 21, 29, 248),
        )
        base.setColorAt(
            1.00,
            QtGui.QColor(5, 8, 13, 248),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(base),
        )

        # Large optical cyan/red ambience. These are deliberately subtle so the
        # background feels illuminated rather than illustrated.
        cyan = QtGui.QRadialGradient(
            QtCore.QPointF(
                w * 0.20,
                h * 0.32,
            ),
            w * 0.48,
        )
        cyan.setColorAt(
            0.00,
            QtGui.QColor(0, 209, 235, 30),
        )
        cyan.setColorAt(
            0.58,
            QtGui.QColor(0, 125, 155, 10),
        )
        cyan.setColorAt(
            1.00,
            QtGui.QColor(0, 0, 0, 0),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(cyan),
        )

        red = QtGui.QRadialGradient(
            QtCore.QPointF(
                w * 0.88,
                h * 0.62,
            ),
            w * 0.36,
        )
        red.setColorAt(
            0.00,
            QtGui.QColor(255, 38, 76, 21),
        )
        red.setColorAt(
            0.62,
            QtGui.QColor(120, 18, 42, 7),
        )
        red.setColorAt(
            1.00,
            QtGui.QColor(0, 0, 0, 0),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(red),
        )

        # One floating glass surface, with no visible "computer panel" grid.
        card = QtCore.QRectF(
            8.0,
            8.0,
            max(1.0, w - 16.0),
            max(1.0, h - 16.0),
        )

        glass = QtGui.QLinearGradient(
            card.left(),
            card.top(),
            card.left(),
            card.bottom(),
        )
        glass.setColorAt(
            0.00,
            QtGui.QColor(255, 255, 255, 16),
        )
        glass.setColorAt(
            0.18,
            QtGui.QColor(80, 118, 138, 10),
        )
        glass.setColorAt(
            0.70,
            QtGui.QColor(4, 8, 13, 12),
        )
        glass.setColorAt(
            1.00,
            QtGui.QColor(255, 255, 255, 5),
        )

        painter.setBrush(QtGui.QBrush(glass))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    190,
                    220,
                    232,
                    26,
                ),
                1.0,
            )
        )
        painter.drawRoundedRect(
            card,
            18.0,
            18.0,
        )

        # Top-edge glass catchlight.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    235,
                    250,
                    255,
                    38,
                ),
                1.0,
            )
        )
        painter.drawLine(
            QtCore.QPointF(
                card.left() + 22.0,
                card.top() + 1.0,
            ),
            QtCore.QPointF(
                card.right() - 22.0,
                card.top() + 1.0,
            ),
        )


class BCINameExpansion(QtWidgets.QLabel):
    """
    Progress-driven expansion of BCI into:

        Beacon  Computing  Initiative

    Each word reveals during the same third of the baseline that reveals its
    corresponding B, C, or I in the main metallic boot mark.
    """

    WORDS = (
        "Beacon",
        "Computing",
        "Initiative",
    )

    def __init__(self, parent=None):
        super().__init__(parent)

        self.progress = 0.0
        self.phase = 0.0

        self.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.setMinimumHeight(46)
        self.setTextFormat(
            QtCore.Qt.TextFormat.RichText
        )
        self.setStyleSheet(
            "background: transparent;"
            "border: none;"
        )

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(
            UI_FRAME_INTERVAL_MS
        )
        self.timer.timeout.connect(
            self._animate
        )
        self.timer.start()

        self._render()

    @staticmethod
    def _segment_progress(
        progress,
        index,
    ):
        start = index / 3.0
        end = (index + 1) / 3.0

        value = (
            (progress - start)
            / max(
                end - start,
                1e-6,
            )
        )

        return max(
            0.0,
            min(1.0, value),
        )

    def set_progress(self, progress):
        self.progress = max(
            0.0,
            min(
                1.0,
                float(progress),
            ),
        )
        self._render()

    def _animate(self):
        self.phase = (
            self.phase + 0.055
        ) % (2.0 * np.pi)

        self._render()

    def _render(self):
        chunks = []

        pulse = (
            0.80
            + 0.20
            * np.sin(self.phase)
        )

        cyan_alpha = int(
            225 + 30 * pulse
        )
        red_alpha = int(
            210 + 35 * pulse
        )

        for index, word in enumerate(
            self.WORDS
        ):
            local = self._segment_progress(
                self.progress,
                index,
            )

            # The initial letter is always present once its segment begins.
            if local <= 0.0:
                visible_count = 0
            else:
                visible_count = max(
                    1,
                    min(
                        len(word),
                        int(
                            np.ceil(
                                local
                                * len(word)
                            )
                        ),
                    ),
                )

            visible = word[
                :visible_count
            ]

            if not visible:
                # Keep horizontal spacing stable before a word begins.
                chunks.append(
                    "<span style='color:rgba(120,130,140,0.18);'>"
                    "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                    "</span>"
                )
                continue

            initial = visible[0]
            remainder = visible[1:]

            # Alternate cyan/red emphasis through B-C-I so the expansion
            # carries the same chromatic language as the boot mark.
            if index % 2 == 0:
                initial_color = (
                    f"rgba(0,238,255,{cyan_alpha})"
                )
                shadow_color = (
                    "rgba(255,42,68,0.70)"
                )
            else:
                initial_color = (
                    f"rgba(255,42,68,{red_alpha})"
                )
                shadow_color = (
                    "rgba(0,238,255,0.70)"
                )

            chunks.append(
                "<span style='"
                "font-family:'DejaVu Sans';"
                "font-size:28px;"
                "font-weight:900;"
                f"color:{initial_color};"
                f"text-shadow:0 0 7px {shadow_color};"
                "'>"
                f"{initial}"
                "</span>"
                "<span style='"
                "font-family:'DejaVu Sans';"
                "font-size:23px;"
                "font-weight:700;"
                "color:#dce4ea;"
                "letter-spacing:1px;"
                "'>"
                f"{remainder}"
                "</span>"
            )

        self.setText(
            "&nbsp;&nbsp;&nbsp;".join(
                chunks
            )
        )

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)


class BCIMachinedGearWidget(QtWidgets.QWidget):
    """Slow machined-steel gear used as the restrained boot identity."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.gear_angle = 0.0

        self.setMinimumSize(190, 190)
        self.setMaximumSize(230, 230)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self.animation_timer = QtCore.QTimer(self)
        self.animation_timer.setInterval(33)
        self.animation_timer.timeout.connect(self._advance)
        self.animation_timer.start()

    def _advance(self):
        # About 3.3 degrees per second: deliberate, mechanical motion.
        self.gear_angle = (
            self.gear_angle + 0.11
        ) % 360.0
        self.update()

    @staticmethod
    def _gear_path(radius, teeth=22):
        path = QtGui.QPainterPath()
        outer_radius = radius
        root_radius = radius * 0.82
        tooth_pitch = 2.0 * np.pi / max(teeth, 1)

        profile = (
            (0.00, root_radius),
            (0.10, root_radius),
            (0.22, outer_radius * 0.985),
            (0.56, outer_radius),
            (0.72, outer_radius * 0.985),
            (0.90, root_radius),
        )

        points = []

        for tooth in range(teeth):
            base = tooth * tooth_pitch

            for fraction, current_radius in profile:
                angle = base + fraction * tooth_pitch
                points.append(
                    QtCore.QPointF(
                        np.cos(angle) * current_radius,
                        np.sin(angle) * current_radius,
                    )
                )

        if points:
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            path.closeSubpath()

        return path

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.Antialiasing,
            True,
        )

        w = float(self.width())
        h = float(self.height())
        center = QtCore.QPointF(w * 0.5, h * 0.5)
        radius = min(w, h) * 0.40

        painter.save()
        painter.translate(center)

        # Fixed diffuse shadow behind the moving mechanism.
        shadow = QtGui.QRadialGradient(
            QtCore.QPointF(0.0, radius * 0.10),
            radius * 1.25,
        )
        shadow.setColorAt(0.0, QtGui.QColor(0, 0, 0, 118))
        shadow.setColorAt(0.70, QtGui.QColor(0, 0, 0, 44))
        shadow.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(shadow))
        painter.drawEllipse(
            QtCore.QPointF(0.0, radius * 0.08),
            radius * 1.10,
            radius * 1.10,
        )

        painter.rotate(self.gear_angle)

        gear_path = self._gear_path(radius, teeth=22)

        # Machined steel body.
        body = QtGui.QRadialGradient(
            QtCore.QPointF(
                -radius * 0.34,
                -radius * 0.38,
            ),
            radius * 1.45,
        )
        body.setColorAt(0.00, QtGui.QColor(235, 240, 243, 255))
        body.setColorAt(0.18, QtGui.QColor(152, 163, 171, 255))
        body.setColorAt(0.42, QtGui.QColor(65, 74, 82, 255))
        body.setColorAt(0.66, QtGui.QColor(115, 126, 134, 255))
        body.setColorAt(0.84, QtGui.QColor(44, 52, 60, 255))
        body.setColorAt(1.00, QtGui.QColor(20, 26, 32, 255))

        painter.setBrush(QtGui.QBrush(body))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(210, 218, 224, 170),
                1.15,
            )
        )
        painter.drawPath(gear_path)

        # Inner recess gives the mechanism depth.
        inner_ring = QtGui.QRadialGradient(
            QtCore.QPointF(
                -radius * 0.12,
                -radius * 0.16,
            ),
            radius * 0.73,
        )
        inner_ring.setColorAt(0.00, QtGui.QColor(115, 124, 131, 255))
        inner_ring.setColorAt(0.40, QtGui.QColor(44, 51, 58, 255))
        inner_ring.setColorAt(0.78, QtGui.QColor(20, 26, 31, 255))
        inner_ring.setColorAt(1.00, QtGui.QColor(9, 13, 17, 255))

        painter.setBrush(QtGui.QBrush(inner_ring))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(155, 167, 175, 110),
                1.0,
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.67,
            radius * 0.67,
        )

        # Six solid spokes.
        spoke_fill = QtGui.QLinearGradient(
            -radius * 0.60,
            0.0,
            radius * 0.60,
            0.0,
        )
        spoke_fill.setColorAt(0.00, QtGui.QColor(55, 64, 71, 255))
        spoke_fill.setColorAt(0.50, QtGui.QColor(139, 150, 158, 255))
        spoke_fill.setColorAt(1.00, QtGui.QColor(43, 51, 58, 255))

        painter.setBrush(QtGui.QBrush(spoke_fill))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(194, 204, 210, 86),
                0.8,
            )
        )

        for spoke in range(6):
            painter.save()
            painter.rotate(spoke * 60.0)
            rect = QtCore.QRectF(
                radius * 0.18,
                -radius * 0.065,
                radius * 0.44,
                radius * 0.13,
            )
            painter.drawRoundedRect(
                rect,
                radius * 0.04,
                radius * 0.04,
            )
            painter.restore()

        # Bearing hub.
        hub = QtGui.QRadialGradient(
            QtCore.QPointF(
                -radius * 0.07,
                -radius * 0.09,
            ),
            radius * 0.34,
        )
        hub.setColorAt(0.00, QtGui.QColor(236, 241, 244, 255))
        hub.setColorAt(0.38, QtGui.QColor(134, 145, 153, 255))
        hub.setColorAt(0.72, QtGui.QColor(45, 53, 60, 255))
        hub.setColorAt(1.00, QtGui.QColor(16, 21, 26, 255))

        painter.setBrush(QtGui.QBrush(hub))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(217, 225, 230, 160),
                1.0,
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.30,
            radius * 0.30,
        )

        painter.setBrush(QtGui.QColor(9, 13, 17, 255))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(100, 116, 126, 150),
                1.0,
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(0.0, 0.0),
            radius * 0.13,
            radius * 0.13,
        )

        # Bolt heads around the hub.
        bolt_radius = radius * 0.035
        bolt_distance = radius * 0.23

        for bolt in range(6):
            angle = np.deg2rad(bolt * 60.0)
            bolt_center = QtCore.QPointF(
                np.cos(angle) * bolt_distance,
                np.sin(angle) * bolt_distance,
            )
            bolt_fill = QtGui.QRadialGradient(
                bolt_center
                + QtCore.QPointF(
                    -bolt_radius * 0.25,
                    -bolt_radius * 0.30,
                ),
                bolt_radius * 1.25,
            )
            bolt_fill.setColorAt(
                0.00,
                QtGui.QColor(220, 226, 230, 255),
            )
            bolt_fill.setColorAt(
                1.00,
                QtGui.QColor(58, 67, 74, 255),
            )

            painter.setBrush(QtGui.QBrush(bolt_fill))
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(25, 31, 36, 210),
                    0.8,
                )
            )
            painter.drawEllipse(
                bolt_center,
                bolt_radius,
                bolt_radius,
            )

        # Brushed-metal machining rings.
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        for fraction, alpha in (
            (0.39, 34),
            (0.47, 28),
            (0.56, 22),
            (0.73, 18),
        ):
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(226, 232, 235, alpha),
                    0.7,
                )
            )
            painter.drawEllipse(
                QtCore.QPointF(0.0, 0.0),
                radius * fraction,
                radius * fraction,
            )

        # Restrained cool highlight.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(0, 188, 205, 82),
                1.4,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            QtCore.QRectF(
                -radius * 0.88,
                -radius * 0.88,
                radius * 1.76,
                radius * 1.76,
            ),
            42 * 16,
            72 * 16,
        )

        # Deep crimson edge accent: red, not magenta.
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(126, 38, 45, 92),
                1.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            QtCore.QRectF(
                -radius * 0.83,
                -radius * 0.83,
                radius * 1.66,
                radius * 1.66,
            ),
            224 * 16,
            52 * 16,
        )

        painter.restore()
        painter.end()

    def showEvent(self, event):
        self.animation_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.animation_timer.stop()
        super().hideEvent(event)

class BCIBootScreen(QtWidgets.QWidget):
    """
    Full-surface dark boot identity for Beacon Computing Initiative.

    The complete widget paints one continuous background. The gear and all
    labels sit directly over that surface instead of living inside a separate
    animation rectangle.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent,
            True,
        )
        self.setAutoFillBackground(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(82, 44, 82, 42)
        layout.setSpacing(12)

        layout.addStretch(1)

        gear_row = QtWidgets.QHBoxLayout()
        gear_row.addStretch(1)

        self.gear = BCIMachinedGearWidget(self)
        gear_row.addWidget(self.gear)

        gear_row.addStretch(1)
        layout.addLayout(gear_row)

        self.organization_label = QtWidgets.QLabel(
            "BEACON COMPUTING INITIATIVE"
        )
        self.organization_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.organization_label.setStyleSheet(
            "font-family: 'DejaVu Sans Condensed';"
            "font-size: 36px;"
            "font-weight: 800;"
            "color: #edf3f6;"
            "letter-spacing: 3.0px;"
            "padding: 2px 8px 0 8px;"
            "background: transparent;"
            "border: none;"
        )

        self.organization_glow = QtWidgets.QGraphicsDropShadowEffect(
            self.organization_label
        )
        self.organization_glow.setBlurRadius(14.0)
        self.organization_glow.setOffset(0.0, 0.0)
        self.organization_glow.setColor(
            QtGui.QColor(0, 182, 198, 44)
        )
        self.organization_label.setGraphicsEffect(
            self.organization_glow
        )
        layout.addWidget(self.organization_label)

        self.product_label = QtWidgets.QLabel(
            "BCIWhisper  •  Acoustic Analysis & Signal Reconstruction"
        )
        self.product_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.product_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 15px;"
            "font-weight: 600;"
            "color: #80929e;"
            "letter-spacing: 0.9px;"
            "padding-bottom: 8px;"
            "background: transparent;"
            "border: none;"
        )
        layout.addWidget(self.product_label)

        self.status_panel = QtWidgets.QFrame()
        self.status_panel.setObjectName("bootStatusPanel")
        self.status_panel.setMaximumWidth(930)
        self.status_panel.setStyleSheet(
            "QFrame#bootStatusPanel {"
            "background: rgba(8, 13, 18, 185);"
            "border: 1px solid rgba(82, 102, 114, 72);"
            "border-radius: 12px;"
            "}"
        )

        panel_layout = QtWidgets.QVBoxLayout(self.status_panel)
        panel_layout.setContentsMargins(28, 20, 28, 20)
        panel_layout.setSpacing(10)

        self.stage_label = QtWidgets.QLabel(
            "INITIALIZING AUDIO SYSTEM"
        )
        self.stage_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.stage_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 21px;"
            "font-weight: 750;"
            "color: #e7edf1;"
            "letter-spacing: 0.8px;"
            "background: transparent;"
            "border: none;"
        )
        panel_layout.addWidget(self.stage_label)

        self.mic_label = QtWidgets.QLabel(
            "Microphone: resolving last-used input..."
        )
        self.mic_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.mic_label.setWordWrap(True)
        self.mic_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "font-weight: 600;"
            "color: #6bb8de;"
            "background: transparent;"
            "border: none;"
        )
        panel_layout.addWidget(self.mic_label)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(11)
        self.progress.setStyleSheet(
            "QProgressBar {"
            "background: rgba(3, 7, 10, 225);"
            "border: 1px solid rgba(120, 145, 158, 36);"
            "border-radius: 5px;"
            "}"
            "QProgressBar::chunk {"
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:0,"
            "stop:0 #00b7c9,"
            "stop:0.74 #5eb7c8,"
            "stop:1 #7e2730"
            ");"
            "border-radius: 4px;"
            "}"
        )
        panel_layout.addWidget(self.progress)

        # Script 56: the boot bar has its own presentation clock. Previously
        # the bar moved only when a calibration spectrum packet reached the GUI.
        # That made a healthy 60-second baseline look frozen whenever visual
        # packets were throttled, delayed, or temporarily starved by rendering.
        # This timer is display-only: it can advance only to 99%; the audio
        # worker's dedicated boot_complete signal is still required for 100%
        # and the transition into the analyzer.
        self._baseline_visual_started_at = None
        self._baseline_visual_duration = float(
            STARTUP_CALIBRATION_SECONDS
        )
        self._baseline_visual_timer = QtCore.QTimer(self)
        self._baseline_visual_timer.setInterval(
            BOOT_PROGRESS_INTERVAL_MS
        )
        self._baseline_visual_timer.timeout.connect(
            self._tick_baseline_visual
        )

        self.countdown_label = QtWidgets.QLabel(
            "Preparing room profile..."
        )
        self.countdown_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.countdown_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 15px;"
            "font-weight: 700;"
            "color: #82939e;"
            "letter-spacing: 0.3px;"
            "background: transparent;"
            "border: none;"
        )
        panel_layout.addWidget(self.countdown_label)

        self.metrics_label = QtWidgets.QLabel(
            "Noise floor: -- dBFS    Ambient peak: -- Hz    Valid audio: -- s"
        )
        self.metrics_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.metrics_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 13px;"
            "color: #94a0a8;"
            "background: transparent;"
            "border: none;"
        )
        panel_layout.addWidget(self.metrics_label)

        self.note_label = QtWidgets.QLabel(
            "Learning the room baseline before monitoring begins."
        )
        self.note_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.note_label.setWordWrap(True)
        self._note_normal_style = (
            "font-family: 'DejaVu Sans';"
            "font-size: 13px;"
            "color: #727f88;"
            "background: transparent;"
            "border: none;"
        )
        self._note_warning_style = (
            "font-family: 'DejaVu Sans';"
            "font-size: 13px;"
            "font-weight: 700;"
            "color: #8b989f;"
            "background: transparent;"
            "border: none;"
        )
        self._baseline_warning_active = False
        self.note_label.setStyleSheet(
            self._note_normal_style
        )
        panel_layout.addWidget(self.note_label)

        panel_row = QtWidgets.QHBoxLayout()
        panel_row.addStretch(1)
        panel_row.addWidget(self.status_panel, 1)
        panel_row.addStretch(1)
        layout.addLayout(panel_row)

        layout.addSpacing(8)

        self.footer_label = QtWidgets.QLabel(
            f"{BCI_PROJECT_VERSION}  •  Build {BCI_BUILD}  •  "
            f"Lead Developer: {BCI_LEAD_DEVELOPER}"
        )
        self.footer_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.footer_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 11px;"
            "font-weight: 600;"
            "color: #59666f;"
            "letter-spacing: 0.6px;"
            "background: transparent;"
            "border: none;"
        )
        layout.addWidget(self.footer_label)

        layout.addStretch(1)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.Antialiasing,
            True,
        )

        w = float(self.width())
        h = float(self.height())

        # The dark base covers the COMPLETE boot window.
        base = QtGui.QLinearGradient(
            0.0,
            0.0,
            w,
            h,
        )
        base.setColorAt(
            0.00,
            QtGui.QColor(4, 7, 10, 255),
        )
        base.setColorAt(
            0.46,
            QtGui.QColor(8, 13, 18, 255),
        )
        base.setColorAt(
            1.00,
            QtGui.QColor(2, 4, 7, 255),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(base),
        )

        # Restrained cyan ambience.
        cyan_glow = QtGui.QRadialGradient(
            QtCore.QPointF(w * 0.50, h * 0.23),
            min(w, h) * 0.58,
        )
        cyan_glow.setColorAt(
            0.00,
            QtGui.QColor(0, 111, 128, 24),
        )
        cyan_glow.setColorAt(
            0.55,
            QtGui.QColor(0, 68, 78, 8),
        )
        cyan_glow.setColorAt(
            1.00,
            QtGui.QColor(0, 0, 0, 0),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(cyan_glow),
        )

        # Very dark crimson ambience, intentionally far from magenta/pink.
        crimson_glow = QtGui.QRadialGradient(
            QtCore.QPointF(w * 0.79, h * 0.18),
            min(w, h) * 0.38,
        )
        crimson_glow.setColorAt(
            0.00,
            QtGui.QColor(103, 25, 31, 16),
        )
        crimson_glow.setColorAt(
            0.55,
            QtGui.QColor(76, 20, 25, 5),
        )
        crimson_glow.setColorAt(
            1.00,
            QtGui.QColor(0, 0, 0, 0),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(crimson_glow),
        )

        # Dark vignette keeps all four corners visually continuous.
        vignette = QtGui.QRadialGradient(
            QtCore.QPointF(w * 0.50, h * 0.46),
            max(w, h) * 0.68,
        )
        vignette.setColorAt(
            0.00,
            QtGui.QColor(0, 0, 0, 0),
        )
        vignette.setColorAt(
            0.66,
            QtGui.QColor(0, 0, 0, 20),
        )
        vignette.setColorAt(
            1.00,
            QtGui.QColor(0, 0, 0, 142),
        )
        painter.fillRect(
            self.rect(),
            QtGui.QBrush(vignette),
        )

        # Full-screen border aura keeps the boot page visually connected to
        # the glowing application shell used after calibration.
        border_rect = QtCore.QRectF(
            self.rect()
        ).adjusted(5.0, 5.0, -5.0, -5.0)

        for width, alpha in (
            (8.0, 22),
            (4.5, 42),
            (1.8, 112),
        ):
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(0, 185, 202, alpha),
                    width,
                    QtCore.Qt.PenStyle.SolidLine,
                )
            )
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                border_rect,
                13.0,
                13.0,
            )

        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(126, 38, 45, 54),
                1.0,
            )
        )
        painter.drawRoundedRect(
            border_rect.adjusted(2.0, 2.0, -2.0, -2.0),
            11.0,
            11.0,
        )

        painter.end()

    def wait_for_microphone(self, message="WAITING FOR LIVE MICROPHONE FRAMES"):
        """Hold boot at 0% until the worker proves frames are arriving."""
        self._baseline_visual_timer.stop()
        self._baseline_visual_started_at = None
        if self.progress.value() != 0:
            self.progress.setValue(0)
        if self.stage_label.text() != "WAITING FOR MICROPHONE":
            self.stage_label.setText("WAITING FOR MICROPHONE")
        text = str(message or "WAITING FOR LIVE MICROPHONE FRAMES")
        if self.countdown_label.text() != text:
            self.countdown_label.setText(text)

    def begin_baseline(self, duration=STARTUP_CALIBRATION_SECONDS):
        """Start/reset the visible baseline clock.

        This is intentionally independent from DSP cadence. It gives the user
        a continuously moving 60-second progress indicator while the worker
        performs the real calibration. Completion remains worker-authoritative.
        """
        self._baseline_visual_duration = max(
            0.1,
            float(duration),
        )
        self._baseline_visual_started_at = time.monotonic()

        if self.progress.value() != 0:
            self.progress.setValue(0)

        if self.stage_label.text() != "LEARNING ROOM PROFILE":
            self.stage_label.setText("LEARNING ROOM PROFILE")

        countdown_text = (
            f"  0.0% complete   •   "
            f"{self._baseline_visual_duration:4.1f} seconds remaining"
        )
        if self.countdown_label.text() != countdown_text:
            self.countdown_label.setText(countdown_text)

        if not self._baseline_visual_timer.isActive():
            self._baseline_visual_timer.start()

    def finish_baseline(self):
        """Finish the visible baseline only after worker confirmation."""
        self._baseline_visual_timer.stop()
        self._baseline_visual_started_at = None
        if self.progress.value() != 1000:
            self.progress.setValue(1000)

    def _sync_baseline_visual(self, progress, remaining):
        """Re-anchor the visual clock to authoritative worker progress."""
        progress = max(0.0, min(1.0, float(progress)))
        remaining = max(0.0, float(remaining))

        if progress >= 1.0:
            self.finish_baseline()
            return

        now = time.monotonic()
        inferred_duration = self._baseline_visual_duration
        if progress < 0.999 and remaining > 0.0:
            inferred_duration = max(
                0.1,
                remaining / max(1e-6, 1.0 - progress),
            )

        self._baseline_visual_duration = inferred_duration
        self._baseline_visual_started_at = (
            now - progress * inferred_duration
        )

        if not self._baseline_visual_timer.isActive():
            self._baseline_visual_timer.start()

    def _tick_baseline_visual(self):
        """Advance the boot progress bar at 10 Hz without driving DSP."""
        if self._baseline_visual_started_at is None:
            return

        duration = max(0.1, self._baseline_visual_duration)
        elapsed = max(
            0.0,
            time.monotonic() - self._baseline_visual_started_at,
        )

        # Never visually claim completion before the worker confirms it.
        progress = min(0.99, elapsed / duration)
        progress_value = int(progress * 1000.0)
        if self.progress.value() != progress_value:
            self.progress.setValue(progress_value)

        remaining = max(0.0, duration - elapsed)
        if elapsed < duration:
            countdown_text = (
                f"{progress * 100:5.1f}% complete"
                f"   •   {remaining:4.1f} seconds remaining"
            )
        else:
            countdown_text = (
                "99.0% complete   •   "
                "waiting for microphone baseline confirmation"
            )

        if self.countdown_label.text() != countdown_text:
            self.countdown_label.setText(countdown_text)

    def set_microphone(self, text):
        self.mic_label.setText(
            f"Microphone: {text}"
        )

    def set_device_status(
        self,
        message,
        success,
    ):
        color = (
            "#3f9d67"
            if success
            else "#a94249"
        )

        self.mic_label.setText(str(message))
        self.mic_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "font-weight: 600;"
            f"color: {color};"
            "background: transparent;"
            "border: none;"
        )

    def update_baseline(
        self,
        progress,
        remaining,
        noise_floor_db,
        ambient_peak_hz,
        valid_seconds=0.0,
        warning="",
    ):
        progress = max(
            0.0,
            min(1.0, float(progress)),
        )

        self._sync_baseline_visual(
            progress,
            remaining,
        )

        progress_value = int(progress * 1000.0)
        if progress >= 1.0:
            progress_value = 1000
        else:
            # A delayed worker packet must not make the visible bar jump
            # backwards. The next visual-timer tick remains synchronized to the
            # worker's monotonic baseline clock.
            progress_value = max(
                self.progress.value(),
                progress_value,
            )
        if self.progress.value() != progress_value:
            self.progress.setValue(progress_value)

        if progress >= 1.0:
            stage_text = "ROOM PROFILE READY"
            countdown_text = "Starting acoustic analyzer..."
        else:
            stage_text = "LEARNING ROOM PROFILE"
            countdown_text = (
                f"{progress * 100:5.1f}% complete"
                f"   •   {remaining:4.1f} seconds remaining"
            )

        if self.stage_label.text() != stage_text:
            self.stage_label.setText(stage_text)
        if self.countdown_label.text() != countdown_text:
            self.countdown_label.setText(countdown_text)

        if ambient_peak_hz > 0.0:
            peak_text = f"{ambient_peak_hz:.0f} Hz"
        else:
            peak_text = "learning..."

        metrics_text = (
            f"Noise floor: {noise_floor_db:.1f} dBFS    "
            f"Ambient peak: {peak_text}    "
            f"Valid audio: {valid_seconds:.1f} s"
        )
        if self.metrics_label.text() != metrics_text:
            self.metrics_label.setText(metrics_text)

        warning_text = str(warning) if warning else (
            "Learning the room baseline before monitoring begins."
        )
        warning_active = bool(warning)

        if self.note_label.text() != warning_text:
            self.note_label.setText(warning_text)

        if warning_active != self._baseline_warning_active:
            self._baseline_warning_active = warning_active
            self.note_label.setStyleSheet(
                self._note_warning_style
                if warning_active
                else self._note_normal_style
            )




# ==============================================================================
# Local transcription
# ==============================================================================

# ==============================================================================
# Automatic post-recording signal enhancement
# ==============================================================================

class PostProcessThread(QtCore.QThread):
    """
    BCI Adaptive Signal Reconstruction Engine.

    Design goals:
    - Never alter RAW source material.
    - Use the first-pass isolated WAV only as a reference.
    - Rebuild from RAW with bounded-memory chunked processing.
    - Blend the learned room spectrum with recording-local noise.
    - Use a time/frequency Wiener-like mask with foreground activity weighting.
    - Preserve likely harmonics.
    - Detect persistent 50/60-Hz-family hum before notching.
    - Apply conservative three-band dynamics.
    - Prefer FFmpeg EBU R128 loudnorm when available.
    - Reject the candidate if objective sanity metrics regress materially.
    - Replace the isolated WAV atomically only after quality control passes.
    """

    result_ready = QtCore.pyqtSignal(object)
    status_ready = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.running = True
        self.work_queue = queue.Queue(maxsize=12)

        self._lock = threading.Lock()
        self._condition = threading.Condition(
            self._lock
        )

        self._queued = set()
        self._active = set()
        self._cancelled = set()

    @staticmethod
    def _key(path):
        return str(
            Path(path).expanduser().resolve()
        )

    def submit(self, raw_path, isolated_path):
        raw = Path(str(raw_path)).expanduser()
        isolated = Path(str(isolated_path)).expanduser()

        if not raw.exists() or not isolated.exists():
            self.result_ready.emit(
                {
                    "raw_path": str(raw),
                    "isolated_path": str(isolated),
                    "error": (
                        "Post-processing source file is missing."
                    ),
                }
            )
            return

        key = self._key(isolated)

        with self._condition:
            if key in self._queued or key in self._active:
                return

            self._cancelled.discard(
                self._key(raw)
            )
            self._cancelled.discard(key)
            self._queued.add(key)

        try:
            self.work_queue.put_nowait(
                {
                    "raw_path": self._key(raw),
                    "isolated_path": key,
                }
            )

        except queue.Full:
            with self._condition:
                self._queued.discard(key)
                self._condition.notify_all()

            self.result_ready.emit(
                {
                    "raw_path": str(raw),
                    "isolated_path": str(isolated),
                    "error": (
                        "Post-processing queue is full."
                    ),
                }
            )

    def cancel_paths(self, paths):
        with self._condition:
            for path in paths:
                try:
                    self._cancelled.add(
                        self._key(path)
                    )
                except Exception:
                    pass

            self._condition.notify_all()

    def wait_for_paths_idle(
        self,
        paths,
        timeout=2.0,
    ):
        keys = {
            self._key(path)
            for path in paths
        }

        deadline = (
            time.monotonic()
            + max(
                0.0,
                float(timeout),
            )
        )

        with self._condition:
            while True:
                active = bool(
                    keys
                    & self._active
                )

                if not active:
                    return True

                remaining = (
                    deadline
                    - time.monotonic()
                )

                if remaining <= 0.0:
                    return False

                self._condition.wait(
                    timeout=min(
                        0.1,
                        remaining,
                    )
                )

    def _is_cancelled(self, *paths):
        with self._lock:
            return any(
                self._key(path)
                in self._cancelled
                for path in paths
            )

    def stop(self):
        self.running = False

        try:
            self.work_queue.put_nowait(None)
        except queue.Full:
            pass

        self.wait(5000)

    @staticmethod
    def _pcm_to_float(
        raw_bytes,
        channels,
    ):
        pcm = np.frombuffer(
            raw_bytes,
            dtype="<i2",
        ).astype(
            np.float32
        )

        if channels > 1:
            usable = (
                pcm.size
                - (
                    pcm.size
                    % channels
                )
            )

            pcm = pcm[
                :usable
            ].reshape(
                -1,
                channels,
            ).mean(
                axis=1
            )

        return (
            pcm
            / 32768.0
        ).astype(
            np.float32,
            copy=False,
        )

    @staticmethod
    def _open_pcm16(path):
        wf = wave.open(
            str(path),
            "rb",
        )

        if wf.getsampwidth() != 2:
            wf.close()
            raise RuntimeError(
                "Reconstruction requires 16-bit PCM WAV input."
            )

        return wf

    @staticmethod
    def _positions(
        total_frames,
        window_frames,
    ):
        if total_frames <= window_frames:
            return [0]

        count = min(
            POSTPROCESS_ANALYSIS_WINDOWS,
            max(
                4,
                int(
                    np.ceil(
                        total_frames
                        / max(
                            window_frames,
                            1,
                        )
                    )
                ),
            ),
        )

        return [
            int(value)
            for value in np.linspace(
                0,
                max(
                    0,
                    total_frames
                    - window_frames,
                ),
                num=count,
            )
        ]

    def _reference_spectra(
        self,
        audio_path,
    ):
        with self._open_pcm16(
            audio_path
        ) as wf:
            sample_rate = int(
                wf.getframerate()
            )
            channels = int(
                wf.getnchannels()
            )
            total_frames = int(
                wf.getnframes()
            )

            nfft = min(
                POSTPROCESS_ANALYSIS_FRAMES,
                max(
                    1024,
                    total_frames,
                ),
            )

            hann = np.hanning(
                nfft
            ).astype(
                np.float32
            )

            spectra = []

            for position in self._positions(
                total_frames,
                nfft,
            ):
                if self._is_cancelled(
                    audio_path
                ):
                    raise RuntimeError(
                        "Post-processing cancelled."
                    )

                wf.setpos(
                    min(
                        position,
                        max(
                            0,
                            total_frames - 1,
                        ),
                    )
                )

                block = self._pcm_to_float(
                    wf.readframes(
                        nfft
                    ),
                    channels,
                )

                if block.size < 256:
                    continue

                frame = np.zeros(
                    nfft,
                    dtype=np.float32,
                )

                count = min(
                    nfft,
                    block.size,
                )
                frame[
                    :count
                ] = block[
                    :count
                ]

                fft_values = np.fft.rfft(
                    frame * hann
                )

                spectra.append(
                    np.square(
                        np.abs(
                            fft_values
                        ).astype(
                            np.float64
                        )
                    )
                )

            if not spectra:
                raise RuntimeError(
                    "Not enough reference audio for reconstruction."
                )

            freqs = np.fft.rfftfreq(
                nfft,
                d=1.0
                / max(
                    sample_rate,
                    1,
                ),
            )

            return (
                sample_rate,
                freqs,
                np.stack(
                    spectra,
                    axis=0,
                ),
            )

    def _estimate_band_and_hum(
        self,
        isolated_path,
    ):
        (
            sample_rate,
            freqs,
            spectra,
        ) = self._reference_spectra(
            isolated_path
        )

        aggregate = np.median(
            spectra,
            axis=0,
        )

        usable_high = min(
            sample_rate
            * 0.5
            * 0.965,
            12000.0,
        )

        usable = (
            (freqs >= 70.0)
            & (freqs <= usable_high)
        )

        usable_freqs = freqs[
            usable
        ]
        usable_power = aggregate[
            usable
        ]

        floor = float(
            np.percentile(
                usable_power,
                20.0,
            )
        )

        signal_power = np.maximum(
            usable_power - floor,
            0.0,
        )

        if float(
            np.sum(
                signal_power
            )
        ) <= 1e-18:
            signal_power = np.maximum(
                usable_power,
                0.0,
            )

        cumulative = np.cumsum(
            signal_power
        )
        cumulative /= max(
            float(
                cumulative[-1]
            ),
            1e-20,
        )

        low_index = int(
            np.searchsorted(
                cumulative,
                0.035,
            )
        )
        high_index = int(
            np.searchsorted(
                cumulative,
                0.965,
            )
        )

        low_index = min(
            max(
                0,
                low_index,
            ),
            len(
                usable_freqs
            ) - 1,
        )
        high_index = min(
            max(
                low_index,
                high_index,
            ),
            len(
                usable_freqs
            ) - 1,
        )

        low_hz = max(
            60.0,
            float(
                usable_freqs[
                    low_index
                ]
            )
            - POSTPROCESS_BAND_MARGIN_HZ,
        )
        high_hz = min(
            usable_high,
            float(
                usable_freqs[
                    high_index
                ]
            )
            + POSTPROCESS_BAND_MARGIN_HZ,
        )

        if (
            high_hz - low_hz
            < POSTPROCESS_MIN_BANDWIDTH_HZ
        ):
            center = (
                low_hz
                + high_hz
            ) * 0.5

            half = (
                POSTPROCESS_MIN_BANDWIDTH_HZ
                * 0.5
            )

            low_hz = max(
                60.0,
                center - half,
            )
            high_hz = min(
                usable_high,
                center + half,
            )

        # Persistent-noise spectrum: low percentile over time. Hum should remain
        # while intermittent foreground content tends to disappear.
        persistent = np.percentile(
            spectra,
            25.0,
            axis=0,
        )

        hum_candidates = []

        for base_hz in (
            50.0,
            60.0,
        ):
            family = []
            family_score = 0.0

            harmonic = base_hz

            while (
                harmonic <= min(
                    360.0,
                    high_hz,
                )
            ):
                index = int(
                    np.argmin(
                        np.abs(
                            freqs
                            - harmonic
                        )
                    )
                )

                left = max(
                    0,
                    index - 8,
                )
                right = min(
                    len(freqs),
                    index + 9,
                )

                neighborhood = np.concatenate(
                    (
                        persistent[
                            left:
                            max(
                                left,
                                index - 2,
                            )
                        ],
                        persistent[
                            min(
                                right,
                                index + 3,
                            ):
                            right
                        ],
                    )
                )

                local_floor = (
                    float(
                        np.median(
                            neighborhood
                        )
                    )
                    if neighborhood.size
                    else 0.0
                )

                peak = float(
                    persistent[
                        index
                    ]
                )

                ratio_db = (
                    10.0
                    * np.log10(
                        (
                            peak + 1e-20
                        )
                        / (
                            local_floor
                            + 1e-20
                        )
                    )
                )

                if ratio_db >= 7.0:
                    family.append(
                        float(
                            harmonic
                        )
                    )
                    family_score += (
                        ratio_db
                    )

                harmonic += base_hz

            if len(family) >= 2:
                hum_candidates.append(
                    (
                        family_score,
                        family,
                    )
                )

        if hum_candidates:
            hum_candidates.sort(
                key=lambda item: item[0],
                reverse=True,
            )
            hum_hz = (
                hum_candidates[
                    0
                ][1]
            )
        else:
            hum_hz = []

        return {
            "sample_rate": int(
                sample_rate
            ),
            "low_hz": float(
                low_hz
            ),
            "high_hz": float(
                high_hz
            ),
            "hum_hz": hum_hz,
        }

    @staticmethod
    def _soft_band_mask(
        freqs,
        low_hz,
        high_hz,
    ):
        mask = np.ones_like(
            freqs,
            dtype=np.float64,
        )

        transition = max(
            80.0,
            POSTPROCESS_BAND_MARGIN_HZ,
        )

        below = (
            freqs < low_hz
        )
        above = (
            freqs > high_hz
        )

        mask[below] = np.clip(
            (
                freqs[below]
                - (
                    low_hz
                    - transition
                )
            )
            / transition,
            0.0,
            1.0,
        )

        mask[above] = np.clip(
            (
                (
                    high_hz
                    + transition
                )
                - freqs[above]
            )
            / transition,
            0.0,
            1.0,
        )

        return mask

    def _room_noise_for_bins(
        self,
        freqs,
        local_noise_power,
    ):
        if not ROOM_PROFILE_PATH.exists():
            return local_noise_power

        try:
            with np.load(
                str(
                    ROOM_PROFILE_PATH
                ),
                allow_pickle=False,
            ) as data:
                profile_db = np.asarray(
                    data["profile_db"],
                    dtype=np.float64,
                )

                profile_sr = int(
                    np.asarray(
                        data["sample_rate"]
                    ).reshape(-1)[0]
                )

                fft_size = int(
                    np.asarray(
                        data["fft_size"]
                    ).reshape(-1)[0]
                )

            profile_freqs = np.fft.rfftfreq(
                fft_size,
                d=1.0
                / max(
                    profile_sr,
                    1,
                ),
            )

            room_power = np.power(
                10.0,
                profile_db / 10.0,
            )

            room_interp = np.interp(
                freqs,
                profile_freqs,
                room_power,
                left=room_power[0],
                right=room_power[-1],
            )

            room_scale = (
                np.median(
                    local_noise_power
                )
                / max(
                    np.median(
                        room_interp
                    ),
                    1e-20,
                )
            )

            room_scaled = (
                room_interp
                * room_scale
            )

            blend = float(
                POSTPROCESS_ROOM_PROFILE_BLEND
            )

            return (
                (
                    1.0 - blend
                )
                * local_noise_power
                + blend
                * room_scaled
            )

        except Exception as exc:
            report_warning(
                "room-profile reconstruction",
                str(exc),
            )
            return local_noise_power

    @staticmethod
    def _foreground_probability(
        power,
        noise_power,
        freqs,
    ):
        eps = 1e-20

        total_power = np.sum(
            power,
            axis=0,
        ) + eps

        noise_total = np.sum(
            noise_power[
                :,
                None
            ],
            axis=0,
        ) + eps

        excess = np.maximum(
            power
            - noise_power[
                :,
                None
            ],
            0.0,
        )

        excess_total = np.sum(
            excess,
            axis=0,
        ) + eps

        snr_db = (
            10.0
            * np.log10(
                excess_total
                / noise_total
            )
        )

        voice_mask = (
            (freqs >= 150.0)
            & (freqs <= 4000.0)
        )

        voice_ratio = (
            np.sum(
                power[
                    voice_mask,
                    :
                ],
                axis=0,
            )
            / total_power
        )

        geometric = np.exp(
            np.mean(
                np.log(
                    power + eps
                ),
                axis=0,
            )
        )

        arithmetic = np.mean(
            power,
            axis=0,
        ) + eps

        flatness = (
            geometric
            / arithmetic
        )

        normalized = (
            power
            / total_power[
                None,
                :
            ]
        )

        flux = np.zeros(
            normalized.shape[1],
            dtype=np.float64,
        )

        if normalized.shape[1] > 1:
            delta = np.maximum(
                normalized[
                    :,
                    1:
                ]
                - normalized[
                    :,
                    :-1
                ],
                0.0,
            )

            flux[1:] = np.sqrt(
                np.sum(
                    np.square(
                        delta
                    ),
                    axis=0,
                )
            )

        snr_score = np.clip(
            (
                snr_db + 4.0
            ) / 18.0,
            0.0,
            1.0,
        )

        voice_score = np.clip(
            (
                voice_ratio - 0.18
            ) / 0.62,
            0.0,
            1.0,
        )

        tonality_score = np.clip(
            (
                0.70 - flatness
            ) / 0.62,
            0.0,
            1.0,
        )

        flux_score = np.clip(
            flux * 7.0,
            0.0,
            1.0,
        )

        probability = (
            0.46
            * snr_score
            + 0.28
            * voice_score
            + 0.18
            * tonality_score
            + 0.08
            * flux_score
        )

        return np.clip(
            probability,
            0.0,
            1.0,
        )

    @staticmethod
    def _smooth_mask(mask):
        result = np.asarray(
            mask,
            dtype=np.float64,
        ).copy()

        # Frequency smoothing without a SciPy ndimage dependency.
        padded = np.pad(
            result,
            (
                (2, 2),
                (0, 0),
            ),
            mode="edge",
        )

        result = (
            0.10
            * padded[
                0:-4,
                :
            ]
            + 0.20
            * padded[
                1:-3,
                :
            ]
            + 0.40
            * padded[
                2:-2,
                :
            ]
            + 0.20
            * padded[
                3:-1,
                :
            ]
            + 0.10
            * padded[
                4:,
                :
            ]
        )

        # Fast attack / slower release in time.
        for frame in range(
            1,
            result.shape[1],
        ):
            previous = result[
                :,
                frame - 1
            ]
            current = result[
                :,
                frame
            ]

            opening = (
                current > previous
            )

            result[
                :,
                frame
            ] = np.where(
                opening,
                0.62
                * current
                + 0.38
                * previous,
                0.20
                * current
                + 0.80
                * previous,
            )

        return result

    def _spectral_reconstruct(
        self,
        block,
        sample_rate,
        low_hz,
        high_hz,
    ):
        block = np.asarray(
            block,
            dtype=np.float32,
        )

        if block.size < 256:
            return block.copy(), {
                "foreground_probability": 0.0,
            }

        nfft = min(
            POSTPROCESS_STFT_NFFT,
            max(
                256,
                int(
                    2
                    ** np.floor(
                        np.log2(
                            block.size
                        )
                    )
                ),
            ),
        )

        hop = min(
            POSTPROCESS_STFT_HOP,
            max(
                64,
                nfft // 4,
            ),
        )

        noverlap = (
            nfft - hop
        )

        freqs, _, spectrum = stft(
            block,
            fs=sample_rate,
            window="hann",
            nperseg=nfft,
            noverlap=noverlap,
            nfft=nfft,
            boundary="zeros",
            padded=True,
        )

        power = np.square(
            np.abs(
                spectrum
            ).astype(
                np.float64
            )
        )

        local_noise = np.percentile(
            power,
            POSTPROCESS_NOISE_PERCENTILE,
            axis=1,
        )

        noise_power = self._room_noise_for_bins(
            freqs,
            local_noise,
        )

        foreground = self._foreground_probability(
            power,
            noise_power,
            freqs,
        )

        signal_power = np.maximum(
            power
            - (
                POSTPROCESS_WIENER_OVERSUBTRACT
                * noise_power[
                    :,
                    None
                ]
            ),
            0.0,
        )

        posterior_snr = (
            signal_power
            / (
                noise_power[
                    :,
                    None
                ]
                + 1e-20
            )
        )

        wiener = np.sqrt(
            posterior_snr
            / (
                1.0
                + posterior_snr
            )
        )

        frame_floor = (
            POSTPROCESS_SPECTRAL_FLOOR
            + 0.11
            * foreground[
                None,
                :
            ]
        )

        mask = (
            frame_floor
            + (
                1.0
                - frame_floor
            )
            * wiener
        )

        # Soft global occupied band.
        band_mask = self._soft_band_mask(
            freqs,
            low_hz,
            high_hz,
        )

        mask *= band_mask[
            :,
            None
        ]

        # Harmonic preservation. Local spectral peaks with meaningful SNR are
        # protected, particularly in the speech-relevant region.
        magnitude = np.abs(
            spectrum
        )

        harmonic = np.zeros_like(
            magnitude,
            dtype=bool,
        )

        if magnitude.shape[0] >= 3:
            center = magnitude[
                1:-1,
                :
            ]

            local_peak = (
                (center > magnitude[:-2, :])
                & (center >= magnitude[2:, :])
            )

            harmonic_snr = (
                power[
                    1:-1,
                    :
                ]
                > (
                    3.5
                    * noise_power[
                        1:-1,
                        None
                    ]
                )
            )

            frequency_ok = (
                (
                    freqs[
                        1:-1
                    ]
                    >= 90.0
                )
                & (
                    freqs[
                        1:-1
                    ]
                    <= 6500.0
                )
            )[
                :,
                None
            ]

            harmonic[
                1:-1,
                :
            ] = (
                local_peak
                & harmonic_snr
                & frequency_ok
            )

        protected = harmonic.copy()

        if protected.shape[0] > 2:
            protected[
                1:,
                :
            ] |= harmonic[
                :-1,
                :
            ]
            protected[
                :-1,
                :
            ] |= harmonic[
                1:,
                :
            ]

        harmonic_floor = (
            POSTPROCESS_HARMONIC_FLOOR
            * (
                0.70
                + 0.30
                * foreground[
                    None,
                    :
                ]
            )
        )

        mask = np.where(
            protected,
            np.maximum(
                mask,
                harmonic_floor,
            ),
            mask,
        )

        mask = self._smooth_mask(
            np.clip(
                mask,
                0.0,
                1.0,
            )
        )

        enhanced_spectrum = (
            spectrum
            * mask
        )

        _, reconstructed = istft(
            enhanced_spectrum,
            fs=sample_rate,
            window="hann",
            nperseg=nfft,
            noverlap=noverlap,
            nfft=nfft,
            input_onesided=True,
            boundary=True,
        )

        reconstructed = np.asarray(
            reconstructed,
            dtype=np.float32,
        )

        if reconstructed.size < block.size:
            reconstructed = np.pad(
                reconstructed,
                (
                    0,
                    block.size
                    - reconstructed.size,
                ),
                mode="constant",
            )

        reconstructed = reconstructed[
            :block.size
        ]

        return reconstructed, {
            "foreground_probability": float(
                np.mean(
                    foreground
                )
            ),
        }

    @staticmethod
    def _apply_hum_notches(
        block,
        sample_rate,
        hum_hz,
    ):
        output = np.asarray(
            block,
            dtype=np.float64,
        )

        nyquist = (
            sample_rate * 0.5
        )

        for frequency in hum_hz:
            if (
                frequency <= 0.0
                or frequency >= nyquist * 0.95
            ):
                continue

            b, a = iirnotch(
                frequency,
                Q=36.0,
                fs=sample_rate,
            )

            min_length = (
                3
                * max(
                    len(a),
                    len(b),
                )
            )

            if output.size > min_length:
                output = filtfilt(
                    b,
                    a,
                    output,
                )

        return output.astype(
            np.float32,
            copy=False,
        )

    @staticmethod
    def _compress_band(
        band,
        threshold_db,
        ratio,
    ):
        output = np.asarray(
            band,
            dtype=np.float32,
        ).copy()

        previous_gain = 1.0

        for start in range(
            0,
            len(output),
            POSTPROCESS_GATE_FRAME,
        ):
            end = min(
                len(output),
                start
                + POSTPROCESS_GATE_FRAME,
            )

            frame = output[
                start:end
            ]

            if frame.size == 0:
                continue

            rms = float(
                np.sqrt(
                    np.mean(
                        np.square(
                            frame,
                            dtype=np.float64,
                        )
                    )
                    + 1e-20
                )
            )

            level_db = (
                20.0
                * np.log10(
                    max(
                        rms,
                        1e-9,
                    )
                )
            )

            if level_db > threshold_db:
                compressed_db = (
                    threshold_db
                    + (
                        level_db
                        - threshold_db
                    )
                    / ratio
                )

                gain_db = (
                    compressed_db
                    - level_db
                )
            else:
                gain_db = 0.0

            desired_gain = (
                10.0
                ** (
                    gain_db
                    / 20.0
                )
            )

            # Moderate attack, smooth release.
            if desired_gain < previous_gain:
                current_gain = (
                    0.55
                    * desired_gain
                    + 0.45
                    * previous_gain
                )
            else:
                current_gain = (
                    0.10
                    * desired_gain
                    + 0.90
                    * previous_gain
                )

            ramp = np.linspace(
                previous_gain,
                current_gain,
                num=frame.size,
                dtype=np.float32,
            )

            output[
                start:end
            ] = (
                frame
                * ramp
            )

            previous_gain = (
                current_gain
            )

        return output

    def _multiband_dynamics(
        self,
        block,
        sample_rate,
    ):
        block = np.asarray(
            block,
            dtype=np.float32,
        )

        if block.size < 512:
            return block

        nyquist = (
            sample_rate * 0.5
        )

        low_edge = min(
            300.0,
            nyquist * 0.25,
        )
        high_edge = min(
            3000.0,
            nyquist * 0.75,
        )

        if high_edge <= low_edge * 1.5:
            return self._compress_band(
                block,
                -28.0,
                2.0,
            )

        low_sos = butter(
            4,
            low_edge,
            btype="lowpass",
            fs=sample_rate,
            output="sos",
        )

        high_sos = butter(
            4,
            high_edge,
            btype="highpass",
            fs=sample_rate,
            output="sos",
        )

        low = sosfiltfilt(
            low_sos,
            block,
        ).astype(
            np.float32
        )

        high = sosfiltfilt(
            high_sos,
            block,
        ).astype(
            np.float32
        )

        # Residual construction preserves the original sum exactly before
        # compression and avoids crossover holes.
        mid = (
            block
            - low
            - high
        ).astype(
            np.float32
        )

        low = self._compress_band(
            low,
            threshold_db=-24.0,
            ratio=2.0,
        )

        mid = self._compress_band(
            mid,
            threshold_db=-30.0,
            ratio=2.5,
        )

        high = self._compress_band(
            high,
            threshold_db=-28.0,
            ratio=1.7,
        )

        return (
            low
            + mid
            + high
        ).astype(
            np.float32
        )

    @staticmethod
    def _gate_block(
        block,
        noise_rms,
        active_rms,
    ):
        output = np.asarray(
            block,
            dtype=np.float32,
        ).copy()

        threshold = max(
            noise_rms * 1.70,
            active_rms * 0.030,
            1e-6,
        )

        previous_gain = 1.0

        for start in range(
            0,
            len(output),
            POSTPROCESS_GATE_FRAME,
        ):
            end = min(
                len(output),
                start
                + POSTPROCESS_GATE_FRAME,
            )

            frame = output[
                start:end
            ]

            if not frame.size:
                continue

            rms = float(
                np.sqrt(
                    np.mean(
                        np.square(
                            frame,
                            dtype=np.float64,
                        )
                    )
                    + 1e-20
                )
            )

            normalized = np.clip(
                (
                    rms - threshold
                )
                / max(
                    threshold * 4.0,
                    1e-6,
                ),
                0.0,
                1.0,
            )

            openness = (
                normalized
                * normalized
                * (
                    3.0
                    - 2.0
                    * normalized
                )
            )

            desired = (
                POSTPROCESS_GATE_FLOOR
                + (
                    1.0
                    - POSTPROCESS_GATE_FLOOR
                )
                * openness
            )

            if desired > previous_gain:
                current_gain = (
                    0.60
                    * desired
                    + 0.40
                    * previous_gain
                )
            else:
                current_gain = (
                    0.08
                    * desired
                    + 0.92
                    * previous_gain
                )

            ramp = np.linspace(
                previous_gain,
                current_gain,
                num=frame.size,
                dtype=np.float32,
            )

            output[
                start:end
            ] = frame * ramp
            previous_gain = current_gain

        return output

    @staticmethod
    def _soft_peak_manage(block):
        block = np.asarray(
            block,
            dtype=np.float32,
        )

        threshold = 0.82
        ceiling = (
            POSTPROCESS_PEAK_LIMIT
        )

        magnitude = np.abs(
            block
        )
        mask = (
            magnitude > threshold
        )

        if np.any(mask):
            span = max(
                ceiling - threshold,
                0.02,
            )

            excess = (
                magnitude[
                    mask
                ]
                - threshold
            )

            compressed = (
                threshold
                + span
                * np.tanh(
                    excess
                    / span
                )
            )

            block = block.copy()

            block[
                mask
            ] = (
                np.sign(
                    block[
                        mask
                    ]
                )
                * compressed
            )

        return np.clip(
            block,
            -ceiling,
            ceiling,
        )

    def _estimate_levels(
        self,
        raw_path,
        low_hz,
        high_hz,
    ):
        values = []

        with self._open_pcm16(
            raw_path
        ) as wf:
            sample_rate = int(
                wf.getframerate()
            )
            channels = int(
                wf.getnchannels()
            )
            total_frames = int(
                wf.getnframes()
            )

            window_frames = min(
                POSTPROCESS_ANALYSIS_FRAMES,
                max(
                    512,
                    total_frames,
                ),
            )

            sos = butter(
                5,
                [
                    low_hz,
                    high_hz,
                ],
                btype="bandpass",
                fs=sample_rate,
                output="sos",
            )

            for position in self._positions(
                total_frames,
                window_frames,
            ):
                wf.setpos(
                    min(
                        position,
                        max(
                            0,
                            total_frames - 1,
                        ),
                    )
                )

                block = self._pcm_to_float(
                    wf.readframes(
                        window_frames
                    ),
                    channels,
                )

                if block.size < 256:
                    continue

                try:
                    filtered = sosfiltfilt(
                        sos,
                        block,
                    )
                except Exception:
                    filtered = sosfilt(
                        sos,
                        block,
                    )

                for start in range(
                    0,
                    len(filtered),
                    POSTPROCESS_GATE_FRAME,
                ):
                    frame = filtered[
                        start:
                        start
                        + POSTPROCESS_GATE_FRAME
                    ]

                    if frame.size < 128:
                        continue

                    values.append(
                        float(
                            np.sqrt(
                                np.mean(
                                    np.square(
                                        frame,
                                        dtype=np.float64,
                                    )
                                )
                                + 1e-20
                            )
                        )
                    )

        if not values:
            return (
                1e-5,
                1e-4,
            )

        values = np.asarray(
            values,
            dtype=np.float64,
        )

        noise_rms = max(
            float(
                np.percentile(
                    values,
                    20.0,
                )
            ),
            1e-7,
        )

        active_rms = max(
            float(
                np.percentile(
                    values,
                    78.0,
                )
            ),
            noise_rms * 1.25,
            1e-6,
        )

        return (
            noise_rms,
            active_rms,
        )

    def _enhance_chunk(
        self,
        block,
        sample_rate,
        low_hz,
        high_hz,
        hum_hz,
        noise_rms,
        active_rms,
    ):
        working = np.asarray(
            block,
            dtype=np.float32,
        )

        working = self._apply_hum_notches(
            working,
            sample_rate,
            hum_hz,
        )

        nyquist = (
            sample_rate * 0.5
        )

        low_hz = max(
            30.0,
            min(
                low_hz,
                nyquist * 0.80,
            ),
        )

        high_hz = max(
            low_hz + 50.0,
            min(
                high_hz,
                nyquist * 0.965,
            ),
        )

        sos = butter(
            5,
            [
                low_hz,
                high_hz,
            ],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )

        try:
            working = sosfiltfilt(
                sos,
                working,
            ).astype(
                np.float32
            )
        except Exception:
            working = sosfilt(
                sos,
                working,
            ).astype(
                np.float32
            )

        working, spectral_meta = (
            self._spectral_reconstruct(
                working,
                sample_rate,
                low_hz,
                high_hz,
            )
        )

        working = self._gate_block(
            working,
            noise_rms,
            active_rms,
        )

        working = self._multiband_dynamics(
            working,
            sample_rate,
        )

        working, clarity_meta = (
            self._clarity_master(
                working,
                sample_rate,
                noise_rms,
                active_rms,
                spectral_meta.get(
                    "foreground_probability",
                    0.0,
                ),
            )
        )

        metadata = {
            **spectral_meta,
            **clarity_meta,
        }

        return (
            self._soft_peak_manage(
                working
            ),
            metadata,
        )

    def _write_reconstructed_candidate(
        self,
        raw_path,
        candidate_path,
        analysis,
        noise_rms,
        active_rms,
    ):
        foreground_scores = []
        clarity_strengths = []
        mud_cuts = []
        presence_boosts = []
        air_boosts = []
        deess_amounts = []

        with self._open_pcm16(
            raw_path
        ) as source:
            sample_rate = int(
                source.getframerate()
            )
            channels = int(
                source.getnchannels()
            )

            chunk_frames = max(
                POSTPROCESS_STFT_NFFT * 4,
                int(
                    sample_rate
                    * POSTPROCESS_CHUNK_SECONDS
                ),
            )

            overlap_frames = max(
                POSTPROCESS_STFT_NFFT,
                int(
                    sample_rate
                    * POSTPROCESS_CHUNK_OVERLAP_SECONDS
                ),
            )

            overlap_frames = min(
                overlap_frames,
                chunk_frames // 3,
            )

            previous_raw_tail = np.zeros(
                0,
                dtype=np.float32,
            )
            previous_output_tail = None

            with wave.open(
                str(candidate_path),
                "wb",
            ) as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(
                    sample_rate
                )

                while self.running:
                    if self._is_cancelled(
                        raw_path
                    ):
                        raise RuntimeError(
                            "Post-processing cancelled."
                        )

                    raw_bytes = source.readframes(
                        chunk_frames
                    )

                    if not raw_bytes:
                        break

                    new_audio = self._pcm_to_float(
                        raw_bytes,
                        channels,
                    )

                    if previous_raw_tail.size:
                        process_input = np.concatenate(
                            (
                                previous_raw_tail,
                                new_audio,
                            )
                        )
                    else:
                        process_input = new_audio

                    enhanced, meta = self._enhance_chunk(
                        process_input,
                        sample_rate,
                        analysis["low_hz"],
                        analysis["high_hz"],
                        analysis["hum_hz"],
                        noise_rms,
                        active_rms,
                    )

                    foreground_scores.append(
                        float(
                            meta.get(
                                "foreground_probability",
                                0.0,
                            )
                        )
                    )

                    clarity_strengths.append(
                        float(
                            meta.get(
                                "clarity_strength",
                                0.0,
                            )
                        )
                    )
                    mud_cuts.append(
                        float(
                            meta.get(
                                "mud_cut_db",
                                0.0,
                            )
                        )
                    )
                    presence_boosts.append(
                        float(
                            meta.get(
                                "presence_boost_db",
                                0.0,
                            )
                        )
                    )
                    air_boosts.append(
                        float(
                            meta.get(
                                "air_boost_db",
                                0.0,
                            )
                        )
                    )
                    deess_amounts.append(
                        float(
                            meta.get(
                                "deess_db",
                                0.0,
                            )
                        )
                    )

                    if previous_raw_tail.size:
                        current_overlap = min(
                            overlap_frames,
                            enhanced.size,
                            (
                                previous_output_tail.size
                                if previous_output_tail
                                is not None
                                else 0
                            ),
                        )

                        if current_overlap > 0:
                            fade = np.linspace(
                                0.0,
                                1.0,
                                num=current_overlap,
                                dtype=np.float32,
                            )

                            blended = (
                                previous_output_tail[
                                    -current_overlap:
                                ]
                                * (
                                    1.0 - fade
                                )
                                + enhanced[
                                    :current_overlap
                                ]
                                * fade
                            )

                            pcm = np.clip(
                                blended,
                                -1.0,
                                1.0,
                            )

                            target.writeframesraw(
                                (
                                    pcm
                                    * 32767.0
                                ).astype(
                                    "<i2"
                                ).tobytes()
                            )

                            body_start = current_overlap
                        else:
                            body_start = 0
                    else:
                        body_start = 0

                    # Hold the final overlap so the next chunk can crossfade.
                    if enhanced.size > overlap_frames:
                        body_end = (
                            enhanced.size
                            - overlap_frames
                        )

                        body = enhanced[
                            body_start:
                            body_end
                        ]

                        if body.size:
                            target.writeframesraw(
                                (
                                    np.clip(
                                        body,
                                        -1.0,
                                        1.0,
                                    )
                                    * 32767.0
                                ).astype(
                                    "<i2"
                                ).tobytes()
                            )

                        previous_output_tail = enhanced[
                            body_end:
                        ].copy()
                    else:
                        previous_output_tail = enhanced.copy()

                    previous_raw_tail = new_audio[
                        -min(
                            overlap_frames,
                            new_audio.size,
                        ):
                    ].copy()

                if previous_output_tail is not None:
                    target.writeframesraw(
                        (
                            np.clip(
                                previous_output_tail,
                                -1.0,
                                1.0,
                            )
                            * 32767.0
                        ).astype(
                            "<i2"
                        ).tobytes()
                    )

        return {
            "foreground_probability": (
                float(
                    np.mean(
                        foreground_scores
                    )
                )
                if foreground_scores
                else 0.0
            ),
        }

    @staticmethod
    def _quality_metrics(path):
        rms_values = []
        speech_ratios = []
        clipping_samples = 0
        total_samples = 0
        peaks = []

        with wave.open(
            str(path),
            "rb",
        ) as wf:
            if wf.getsampwidth() != 2:
                raise RuntimeError(
                    "Quality analysis requires 16-bit PCM WAV."
                )

            sample_rate = int(
                wf.getframerate()
            )
            channels = int(
                wf.getnchannels()
            )
            total_frames = int(
                wf.getnframes()
            )

            window_frames = min(
                POSTPROCESS_ANALYSIS_FRAMES,
                max(
                    512,
                    total_frames,
                ),
            )

            positions = (
                PostProcessThread._positions(
                    total_frames,
                    window_frames,
                )
            )

            for position in positions:
                wf.setpos(
                    min(
                        position,
                        max(
                            0,
                            total_frames - 1,
                        ),
                    )
                )

                block = (
                    PostProcessThread._pcm_to_float(
                        wf.readframes(
                            window_frames
                        ),
                        channels,
                    )
                )

                if block.size < 256:
                    continue

                total_samples += int(
                    block.size
                )

                clipping_samples += int(
                    np.count_nonzero(
                        np.abs(
                            block
                        )
                        >= 0.995
                    )
                )

                peaks.append(
                    float(
                        np.max(
                            np.abs(
                                block
                            )
                        )
                    )
                )

                for start in range(
                    0,
                    block.size,
                    POSTPROCESS_GATE_FRAME,
                ):
                    frame = block[
                        start:
                        start
                        + POSTPROCESS_GATE_FRAME
                    ]

                    if frame.size < 128:
                        continue

                    rms_values.append(
                        float(
                            np.sqrt(
                                np.mean(
                                    np.square(
                                        frame,
                                        dtype=np.float64,
                                    )
                                )
                                + 1e-20
                            )
                        )
                    )

                nfft = min(
                    4096,
                    int(
                        2
                        ** np.floor(
                            np.log2(
                                block.size
                            )
                        )
                    ),
                )

                nfft = max(
                    256,
                    nfft,
                )

                spectrum = np.square(
                    np.abs(
                        np.fft.rfft(
                            block[
                                :nfft
                            ]
                            * np.hanning(
                                nfft
                            )
                        )
                    )
                )

                freqs = np.fft.rfftfreq(
                    nfft,
                    d=1.0
                    / sample_rate,
                )

                broad = (
                    (freqs >= 70.0)
                    & (freqs <= 8000.0)
                )
                speech = (
                    (freqs >= 150.0)
                    & (freqs <= 4000.0)
                )

                broad_power = float(
                    np.sum(
                        spectrum[
                            broad
                        ]
                    )
                )

                speech_power = float(
                    np.sum(
                        spectrum[
                            speech
                        ]
                    )
                )

                speech_ratios.append(
                    speech_power
                    / max(
                        broad_power,
                        1e-20,
                    )
                )

        if rms_values:
            rms_array = np.asarray(
                rms_values,
                dtype=np.float64,
            )

            noise_rms = max(
                float(
                    np.percentile(
                        rms_array,
                        20.0,
                    )
                ),
                1e-9,
            )

            active_rms = max(
                float(
                    np.percentile(
                        rms_array,
                        80.0,
                    )
                ),
                noise_rms,
            )
        else:
            noise_rms = 1e-9
            active_rms = 1e-9

        snr_proxy_db = (
            20.0
            * np.log10(
                active_rms
                / noise_rms
            )
        )

        speech_ratio = (
            float(
                np.mean(
                    speech_ratios
                )
            )
            if speech_ratios
            else 0.0
        )

        clip_fraction = (
            clipping_samples
            / max(
                total_samples,
                1,
            )
        )

        peak = max(
            peaks
            or [0.0]
        )

        score = (
            snr_proxy_db
            + 6.0
            * speech_ratio
            - 60.0
            * clip_fraction
        )

        return {
            "noise_rms": float(
                noise_rms
            ),
            "active_rms": float(
                active_rms
            ),
            "snr_proxy_db": float(
                snr_proxy_db
            ),
            "speech_band_ratio": float(
                speech_ratio
            ),
            "clip_fraction": float(
                clip_fraction
            ),
            "peak": float(
                peak
            ),
            "score": float(
                score
            ),
        }

    @staticmethod
    def _ffmpeg_loudnorm(
        input_path,
        output_path,
    ):
        ffmpeg = shutil.which(
            "ffmpeg"
        )

        if not ffmpeg:
            return False

        target_i = (
            POSTPROCESS_TARGET_LUFS
        )
        target_tp = (
            POSTPROCESS_TRUE_PEAK_DBTP
        )
        target_lra = (
            POSTPROCESS_LRA
        )

        first_filter = (
            f"loudnorm=I={target_i}:"
            f"TP={target_tp}:"
            f"LRA={target_lra}:"
            "print_format=json"
        )

        first = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-y",
                "-i",
                str(input_path),
                "-af",
                first_filter,
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )

        if first.returncode != 0:
            return False

        stderr = first.stderr
        start = stderr.rfind(
            "{"
        )
        end = stderr.rfind(
            "}"
        )

        if (
            start < 0
            or end <= start
        ):
            return False

        try:
            measured = json.loads(
                stderr[
                    start:
                    end + 1
                ]
            )
        except Exception:
            return False

        required = (
            "input_i",
            "input_tp",
            "input_lra",
            "input_thresh",
            "target_offset",
        )

        if not all(
            key in measured
            for key in required
        ):
            return False

        second_filter = (
            f"loudnorm=I={target_i}:"
            f"TP={target_tp}:"
            f"LRA={target_lra}:"
            f"measured_I={measured['input_i']}:"
            f"measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:"
            "linear=true:"
            "print_format=summary"
        )

        second = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-y",
                "-i",
                str(input_path),
                "-af",
                second_filter,
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )

        return (
            second.returncode == 0
            and Path(
                output_path
            ).exists()
        )

    def _internal_normalize(
        self,
        input_path,
        output_path,
    ):
        metrics = self._quality_metrics(
            input_path
        )

        target_rms = (
            10.0
            ** (
                POSTPROCESS_TARGET_RMS_DBFS
                / 20.0
            )
        )

        gain = (
            target_rms
            / max(
                metrics[
                    "active_rms"
                ],
                1e-8,
            )
        )

        gain = min(
            gain,
            10.0
            ** (
                POSTPROCESS_MAX_GAIN_DB
                / 20.0
            ),
        )

        with self._open_pcm16(
            input_path
        ) as source:
            sample_rate = int(
                source.getframerate()
            )
            channels = int(
                source.getnchannels()
            )

            with wave.open(
                str(output_path),
                "wb",
            ) as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(
                    sample_rate
                )

                while True:
                    raw_bytes = source.readframes(
                        65536
                    )

                    if not raw_bytes:
                        break

                    block = self._pcm_to_float(
                        raw_bytes,
                        channels,
                    )

                    block = (
                        block
                        * gain
                    )

                    block = self._soft_peak_manage(
                        block
                    )

                    # Approximate true-peak safeguard using 4x oversampling.
                    if block.size >= 32:
                        oversampled = resample_poly(
                            block,
                            4,
                            1,
                        )

                        true_peak = float(
                            np.max(
                                np.abs(
                                    oversampled
                                )
                            )
                        )

                        ceiling = (
                            10.0
                            ** (
                                POSTPROCESS_TRUE_PEAK_DBTP
                                / 20.0
                            )
                        )

                        if true_peak > ceiling:
                            block = (
                                block
                                * (
                                    ceiling
                                    / max(
                                        true_peak,
                                        1e-9,
                                    )
                                )
                            )

                    target.writeframesraw(
                        (
                            np.clip(
                                block,
                                -1.0,
                                1.0,
                            )
                            * 32767.0
                        ).astype(
                            "<i2"
                        ).tobytes()
                    )

        gain_db = (
            20.0
            * np.log10(
                max(
                    gain,
                    1e-12,
                )
            )
        )

        return float(
            gain_db
        )

    @staticmethod
    def _quality_gate(
        original,
        candidate,
    ):
        reasons = []

        if (
            candidate[
                "clip_fraction"
            ]
            > POSTPROCESS_MAX_CLIP_FRACTION
        ):
            reasons.append(
                "candidate clipping exceeds tolerance"
            )

        if (
            candidate[
                "active_rms"
            ]
            < original[
                "active_rms"
            ]
            * 0.35
        ):
            reasons.append(
                "candidate foreground level collapsed"
            )

        if (
            candidate[
                "snr_proxy_db"
            ]
            < original[
                "snr_proxy_db"
            ]
            - POSTPROCESS_MAX_SNR_REGRESSION_DB
        ):
            reasons.append(
                "candidate SNR proxy regressed"
            )

        if (
            candidate[
                "speech_band_ratio"
            ]
            < original[
                "speech_band_ratio"
            ]
            - POSTPROCESS_MAX_SPEECH_BAND_REGRESSION
        ):
            reasons.append(
                "candidate speech-band energy regressed"
            )

        original_presence = float(
            original.get(
                "presence_ratio",
                0.0,
            )
        )
        candidate_presence = float(
            candidate.get(
                "presence_ratio",
                0.0,
            )
        )

        if (
            candidate_presence
            < original_presence - 0.08
        ):
            reasons.append(
                "candidate intelligibility/presence regressed"
            )

        # Prevent an over-bright candidate from passing merely because it is louder.
        if (
            candidate_presence
            > max(
                0.72,
                original_presence + 0.35,
            )
        ):
            reasons.append(
                "candidate presence became excessively dominant"
            )

        original_air = float(
            original.get(
                "air_ratio",
                0.0,
            )
        )
        candidate_air = float(
            candidate.get(
                "air_ratio",
                0.0,
            )
        )

        if (
            candidate_air
            > max(
                0.42,
                original_air + 0.25,
            )
        ):
            reasons.append(
                "candidate upper-band energy became excessively bright"
            )

        if (
            candidate[
                "score"
            ]
            < original[
                "score"
            ]
            - 0.75
        ):
            reasons.append(
                "candidate composite quality score regressed"
            )

        return (
            not reasons,
            reasons,
        )

    @staticmethod
    def _write_enhancement_metadata(
        isolated_path,
        payload,
    ):
        metadata_path = Path(
            isolated_path
        ).with_suffix(
            ".enhancement.json"
        )

        temp_path = Path(
            str(metadata_path)
            + ".tmp"
        )

        temp_path.write_text(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(
            str(temp_path),
            str(metadata_path),
        )

    def _process(
        self,
        raw_path,
        isolated_path,
    ):
        raw_path = Path(
            raw_path
        )
        isolated_path = Path(
            isolated_path
        )

        analysis = self._estimate_band_and_hum(
            isolated_path
        )

        noise_rms, active_rms = (
            self._estimate_levels(
                raw_path,
                analysis[
                    "low_hz"
                ],
                analysis[
                    "high_hz"
                ],
            )
        )

        original_metrics = (
            self._quality_metrics(
                isolated_path
            )
        )
        original_metrics.update(
            self._clarity_metrics(
                isolated_path
            )
        )

        reconstruction_path = Path(
            str(isolated_path)
            + ".reconstruct.tmp.wav"
        )

        loudnorm_path = Path(
            str(isolated_path)
            + ".loudnorm.tmp.wav"
        )

        foreground_meta = {}

        try:
            foreground_meta = (
                self._write_reconstructed_candidate(
                    raw_path,
                    reconstruction_path,
                    analysis,
                    noise_rms,
                    active_rms,
                )
            )

            loudness_backend = (
                "internal"
            )
            gain_db = 0.0
            final_candidate = (
                reconstruction_path
            )

            if self._ffmpeg_loudnorm(
                reconstruction_path,
                loudnorm_path,
            ):
                loudness_backend = (
                    "ffmpeg-loudnorm"
                )
                final_candidate = (
                    loudnorm_path
                )
            else:
                normalized_path = (
                    loudnorm_path
                )

                gain_db = (
                    self._internal_normalize(
                        reconstruction_path,
                        normalized_path,
                    )
                )

                final_candidate = (
                    normalized_path
                )

            candidate_metrics = (
                self._quality_metrics(
                    final_candidate
                )
            )
            candidate_metrics.update(
                self._clarity_metrics(
                    final_candidate
                )
            )

            accepted, rejection_reasons = (
                self._quality_gate(
                    original_metrics,
                    candidate_metrics,
                )
            )

            if self._is_cancelled(
                raw_path,
                isolated_path,
            ):
                raise RuntimeError(
                    "Post-processing cancelled."
                )

            result = {
                "raw_path": str(
                    raw_path.resolve()
                ),
                "isolated_path": str(
                    isolated_path.resolve()
                ),
                "low_hz": float(
                    analysis[
                        "low_hz"
                    ]
                ),
                "high_hz": float(
                    analysis[
                        "high_hz"
                    ]
                ),
                "hum_hz": [
                    float(value)
                    for value in analysis[
                        "hum_hz"
                    ]
                ],
                "foreground_probability": float(
                    foreground_meta.get(
                        "foreground_probability",
                        0.0,
                    )
                ),
                "clarity_strength": float(
                    foreground_meta.get(
                        "clarity_strength",
                        0.0,
                    )
                ),
                "mud_cut_db": float(
                    foreground_meta.get(
                        "mud_cut_db",
                        0.0,
                    )
                ),
                "presence_boost_db": float(
                    foreground_meta.get(
                        "presence_boost_db",
                        0.0,
                    )
                ),
                "air_boost_db": float(
                    foreground_meta.get(
                        "air_boost_db",
                        0.0,
                    )
                ),
                "deess_db": float(
                    foreground_meta.get(
                        "deess_db",
                        0.0,
                    )
                ),
                "target_lufs": float(
                    POSTPROCESS_TARGET_LUFS
                ),
                "true_peak_dbtp": float(
                    POSTPROCESS_TRUE_PEAK_DBTP
                ),
                "gain_db": float(
                    gain_db
                ),
                "loudness_backend": (
                    loudness_backend
                ),
                "original_metrics": (
                    original_metrics
                ),
                "candidate_metrics": (
                    candidate_metrics
                ),
                "accepted": bool(
                    accepted
                ),
                "rejection_reasons": (
                    rejection_reasons
                ),
                "enhanced": bool(
                    accepted
                ),
            }

            if accepted:
                os.replace(
                    str(final_candidate),
                    str(isolated_path),
                )

            self._write_enhancement_metadata(
                isolated_path,
                {
                    "project_version": (
                        BCI_PROJECT_VERSION
                    ),
                    "script_tally": (
                        BCI_SCRIPT_TALLY
                    ),
                    "build": BCI_BUILD,
                    "processed_at": (
                        datetime.now().isoformat()
                    ),
                    **result,
                },
            )

            return result

        finally:
            for path in (
                reconstruction_path,
                loudnorm_path,
            ):
                if path.exists():
                    try:
                        path.unlink()
                    except Exception:
                        pass

    def run(self):
        while self.running:
            try:
                job = self.work_queue.get(
                    timeout=0.25
                )
            except queue.Empty:
                continue

            if job is None:
                break

            raw_path = Path(
                job["raw_path"]
            )
            isolated_path = Path(
                job["isolated_path"]
            )
            key = self._key(
                isolated_path
            )

            with self._condition:
                self._queued.discard(
                    key
                )
                self._active.add(
                    key
                )

            try:
                if self._is_cancelled(
                    raw_path,
                    isolated_path,
                ):
                    continue

                self.status_ready.emit(
                    "RECONSTRUCTING: "
                    f"{isolated_path.name}"
                )

                result = self._process(
                    raw_path,
                    isolated_path,
                )

                self.result_ready.emit(
                    result
                )

            except Exception as exc:
                if "cancelled" not in str(
                    exc
                ).lower():
                    report_exception(
                        f"signal reconstruction {isolated_path}",
                        exc,
                    )

                    self.result_ready.emit(
                        {
                            "raw_path": str(
                                raw_path
                            ),
                            "isolated_path": str(
                                isolated_path
                            ),
                            "error": str(
                                exc
                            ),
                        }
                    )

            finally:
                with self._condition:
                    self._active.discard(
                        key
                    )
                    self._condition.notify_all()

        self.status_ready.emit(
            "RECONSTRUCTION WORKER STOPPED"
        )

    @staticmethod
    def _safe_band_component(
        block,
        sample_rate,
        low_hz,
        high_hz,
    ):
        block = np.asarray(
            block,
            dtype=np.float32,
        )

        if block.size < 256:
            return np.zeros_like(
                block
            )

        nyquist = (
            sample_rate * 0.5
        )

        low_hz = max(
            20.0,
            float(low_hz),
        )
        high_hz = min(
            float(high_hz),
            nyquist * 0.96,
        )

        if high_hz <= low_hz * 1.03:
            return np.zeros_like(
                block
            )

        sos = butter(
            3,
            [
                low_hz,
                high_hz,
            ],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )

        try:
            return sosfiltfilt(
                sos,
                block,
            ).astype(
                np.float32
            )
        except Exception:
            return sosfilt(
                sos,
                block,
            ).astype(
                np.float32
            )

    def _clarity_master(
        self,
        block,
        sample_rate,
        noise_rms,
        active_rms,
        foreground_probability,
    ):
        """
        Production clarity stage.

        - Reduces low-mid mud.
        - Adds intelligibility/presence.
        - Adds a small air lift only when SNR supports it.
        - Applies adaptive de-essing if upper-frequency energy becomes dominant.
        """
        block = np.asarray(
            block,
            dtype=np.float32,
        )

        if block.size < 256:
            return block, {
                "clarity_strength": 0.0,
                "mud_cut_db": 0.0,
                "presence_boost_db": 0.0,
                "air_boost_db": 0.0,
                "deess_db": 0.0,
            }

        snr_db = (
            20.0
            * np.log10(
                max(
                    active_rms,
                    1e-9,
                )
                / max(
                    noise_rms,
                    1e-9,
                )
            )
        )

        snr_strength = np.clip(
            (
                snr_db - 3.0
            )
            / 18.0,
            0.20,
            1.0,
        )

        foreground_strength = np.clip(
            0.45
            + 0.55
            * float(
                foreground_probability
            ),
            0.45,
            1.0,
        )

        clarity_strength = float(
            np.clip(
                snr_strength
                * foreground_strength,
                0.20,
                1.0,
            )
        )

        mud = self._safe_band_component(
            block,
            sample_rate,
            POSTPROCESS_MUD_LOW_HZ,
            POSTPROCESS_MUD_HIGH_HZ,
        )

        presence = self._safe_band_component(
            block,
            sample_rate,
            POSTPROCESS_PRESENCE_LOW_HZ,
            POSTPROCESS_PRESENCE_HIGH_HZ,
        )

        air = self._safe_band_component(
            block,
            sample_rate,
            POSTPROCESS_AIR_LOW_HZ,
            POSTPROCESS_AIR_HIGH_HZ,
        )

        sibilance = self._safe_band_component(
            block,
            sample_rate,
            POSTPROCESS_DEESS_LOW_HZ,
            POSTPROCESS_DEESS_HIGH_HZ,
        )

        mud_cut_db = (
            POSTPROCESS_MUD_CUT_DB
            * (
                0.55
                + 0.45
                * clarity_strength
            )
        )

        presence_boost_db = (
            POSTPROCESS_PRESENCE_BOOST_DB
            * (
                0.45
                + 0.55
                * clarity_strength
            )
        )

        # Air is the most noise-sensitive enhancement, so it is strongly tied to
        # SNR and foreground probability.
        air_boost_db = (
            POSTPROCESS_AIR_BOOST_DB
            * clarity_strength
            * snr_strength
        )

        mud_gain = (
            10.0
            ** (
                -mud_cut_db
                / 20.0
            )
        )

        presence_gain = (
            10.0
            ** (
                presence_boost_db
                / 20.0
            )
        )

        air_gain = (
            10.0
            ** (
                air_boost_db
                / 20.0
            )
        )

        enhanced = (
            block
            - mud
            * (
                1.0
                - mud_gain
            )
            + presence
            * (
                presence_gain
                - 1.0
            )
            + air
            * (
                air_gain
                - 1.0
            )
        ).astype(
            np.float32
        )

        full_rms = float(
            np.sqrt(
                np.mean(
                    np.square(
                        enhanced,
                        dtype=np.float64,
                    )
                )
                + 1e-20
            )
        )

        sib_rms = float(
            np.sqrt(
                np.mean(
                    np.square(
                        sibilance,
                        dtype=np.float64,
                    )
                )
                + 1e-20
            )
        )

        sib_ratio = (
            sib_rms
            / max(
                full_rms,
                1e-9,
            )
        )

        if (
            sib_ratio
            > POSTPROCESS_DEESS_RATIO_TRIGGER
        ):
            excess = (
                sib_ratio
                - POSTPROCESS_DEESS_RATIO_TRIGGER
            )

            deess_fraction = np.clip(
                excess
                / 0.30,
                0.0,
                1.0,
            )

            deess_db = float(
                POSTPROCESS_DEESS_MAX_DB
                * deess_fraction
            )

            deess_gain = (
                10.0
                ** (
                    -deess_db
                    / 20.0
                )
            )

            enhanced = (
                enhanced
                - sibilance
                * (
                    1.0
                    - deess_gain
                )
            ).astype(
                np.float32
            )
        else:
            deess_db = 0.0

        return enhanced, {
            "clarity_strength": float(
                clarity_strength
            ),
            "mud_cut_db": float(
                mud_cut_db
            ),
            "presence_boost_db": float(
                presence_boost_db
            ),
            "air_boost_db": float(
                air_boost_db
            ),
            "deess_db": float(
                deess_db
            ),
        }

    def _clarity_metrics(
        self,
        audio_path,
    ):
        sample_rate, freqs, spectra = (
            self._reference_spectra(
                audio_path
            )
        )

        aggregate = np.median(
            spectra,
            axis=0,
        )

        broad = (
            (freqs >= 100.0)
            & (freqs <= min(
                9000.0,
                sample_rate * 0.48,
            ))
        )

        mud = (
            (freqs >= POSTPROCESS_MUD_LOW_HZ)
            & (freqs <= POSTPROCESS_MUD_HIGH_HZ)
        )

        presence = (
            (freqs >= POSTPROCESS_PRESENCE_LOW_HZ)
            & (freqs <= POSTPROCESS_PRESENCE_HIGH_HZ)
        )

        air = (
            (freqs >= POSTPROCESS_AIR_LOW_HZ)
            & (freqs <= min(
                POSTPROCESS_AIR_HIGH_HZ,
                sample_rate * 0.48,
            ))
        )

        broad_power = float(
            np.sum(
                aggregate[
                    broad
                ]
            )
        )

        denominator = max(
            broad_power,
            1e-20,
        )

        return {
            "mud_ratio": float(
                np.sum(
                    aggregate[
                        mud
                    ]
                )
                / denominator
            ),
            "presence_ratio": float(
                np.sum(
                    aggregate[
                        presence
                    ]
                )
                / denominator
            ),
            "air_ratio": float(
                np.sum(
                    aggregate[
                        air
                    ]
                )
                / denominator
            ),
        }


class TranscriptionThread(QtCore.QThread):
    """Background local speech-to-text worker."""

    result_ready = QtCore.pyqtSignal(object)
    status_ready = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.running = True
        self.work_queue = queue.Queue(maxsize=16)
        self._queued_paths = set()
        self._cancelled_paths = set()
        self._queue_lock = threading.Lock()

        self._faster_model = None
        self._openai_model = None

    def submit(self, audio_path, reason="manual"):
        path = Path(str(audio_path)).expanduser()

        if not path.exists():
            self.result_ready.emit(
                {
                    "audio_path": str(path),
                    "error": "Audio file does not exist.",
                    "reason": reason,
                }
            )
            return

        key = str(path.resolve())

        with self._queue_lock:
            if key in self._queued_paths:
                return

            self._cancelled_paths.discard(
                key
            )
            self._queued_paths.add(key)

        try:
            self.work_queue.put_nowait(
                {
                    "audio_path": key,
                    "reason": reason,
                }
            )
        except queue.Full:
            with self._queue_lock:
                self._queued_paths.discard(key)

            self.result_ready.emit(
                {
                    "audio_path": key,
                    "error": "Transcription queue is full.",
                    "reason": reason,
                }
            )

    def stop(self):
        self.running = False
        try:
            self.work_queue.put_nowait(None)
        except queue.Full:
            pass
        self.wait(3000)

    @staticmethod
    def transcript_path(audio_path):
        return Path(str(audio_path)).with_suffix(".txt")

    @staticmethod
    def _format_timestamp(seconds):
        seconds = max(0.0, float(seconds))
        minutes = int(seconds // 60.0)
        secs = seconds - minutes * 60.0
        return f"{minutes:02d}:{secs:05.2f}"

    def _write_transcript(
        self,
        audio_path,
        backend,
        text,
        segments,
    ):
        transcript_path = self.transcript_path(audio_path)

        lines = [
            "BCIWhisper Local Transcription",
            f"Project Version: {BCI_PROJECT_VERSION}",
            f"Script Revision: {BCI_SCRIPT_REVISION}",
            f"Script Tally: {BCI_SCRIPT_TALLY}",
            f"Build: {BCI_BUILD}",
            f"Backend: {backend}",
            f"Audio: {Path(audio_path).name}",
            "",
        ]

        if segments:
            for segment in segments:
                body = str(
                    segment.get("text", "")
                ).strip()

                if not body:
                    continue

                start = self._format_timestamp(
                    segment.get("start", 0.0)
                )
                end = self._format_timestamp(
                    segment.get("end", 0.0)
                )
                lines.append(
                    f"[{start} --> {end}] {body}"
                )
        elif text.strip():
            lines.append(text.strip())

        transcript_path.write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )

        return transcript_path

    def _transcribe_faster_whisper(self, audio_path):
        from faster_whisper import WhisperModel

        if self._faster_model is None:
            self.status_ready.emit(
                f"Loading Faster-Whisper fallback: {FASTER_WHISPER_MODEL}"
            )
            self._faster_model = WhisperModel(
                FASTER_WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
            )

        segments_iter, info = self._faster_model.transcribe(
            str(audio_path),
            language=(
                TRANSCRIPTION_LANGUAGE
                if TRANSCRIPTION_LANGUAGE
                else None
            ),
            vad_filter=False,
            beam_size=5,
        )

        segments = []
        text_parts = []

        for segment in segments_iter:
            body = str(segment.text).strip()
            if not body:
                continue

            segments.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": body,
                }
            )
            text_parts.append(body)

        return {
            "backend": "faster-whisper",
            "text": " ".join(text_parts).strip(),
            "segments": segments,
            "language": getattr(
                info,
                "language",
                TRANSCRIPTION_LANGUAGE,
            ),
        }

    def _transcribe_openai_whisper(self, audio_path):
        import whisper

        if self._openai_model is None:
            self.status_ready.emit(
                f"Loading OpenAI Whisper model: {OPENAI_WHISPER_MODEL}"
            )

            download_root = Path(OPENAI_WHISPER_DOWNLOAD_ROOT).expanduser()
            download_root.mkdir(parents=True, exist_ok=True)

            # OPENAI_WHISPER_MODEL may be either a model name such as
            # "small.en" or a direct path to a local OpenAI Whisper .pt
            # checkpoint. Named models are cached under the BCI model tree.
            self._openai_model = whisper.load_model(
                OPENAI_WHISPER_MODEL,
                device=OPENAI_WHISPER_DEVICE,
                download_root=str(download_root),
            )

        result = self._openai_model.transcribe(
            str(audio_path),
            language=(
                TRANSCRIPTION_LANGUAGE
                if TRANSCRIPTION_LANGUAGE
                else None
            ),
            fp16=False,
        )

        segments = []
        for segment in result.get("segments", []):
            body = str(
                segment.get("text", "")
            ).strip()

            if body:
                segments.append(
                    {
                        "start": float(
                            segment.get("start", 0.0)
                        ),
                        "end": float(
                            segment.get("end", 0.0)
                        ),
                        "text": body,
                    }
                )

        return {
            "backend": "openai-whisper",
            "text": str(
                result.get("text", "")
            ).strip(),
            "segments": segments,
            "language": result.get(
                "language",
                TRANSCRIPTION_LANGUAGE,
            ),
        }

    def _find_whisper_cpp_model(self):
        candidates = []

        if WHISPER_CPP_MODEL:
            candidates.append(
                Path(WHISPER_CPP_MODEL).expanduser()
            )

        candidates.extend(
            [
                APP_DIR / "models" / "ggml-base.en.bin",
                APP_DIR / "ggml-base.en.bin",
                Path.home()
                / ".cache"
                / "whisper"
                / "ggml-base.en.bin",
            ]
        )

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None

    def _transcribe_whisper_cpp(self, audio_path):
        executable = (
            shutil.which("whisper-cli")
            or shutil.which("main")
        )

        if not executable:
            raise RuntimeError(
                "whisper-cli was not found."
            )

        model = self._find_whisper_cpp_model()

        if model is None:
            raise RuntimeError(
                "whisper.cpp model not found. "
                "Set BCI_WHISPER_CPP_MODEL to a local ggml model."
            )

        output_base = Path(audio_path).with_suffix("")

        command = [
            executable,
            "-m",
            str(model),
            "-f",
            str(audio_path),
            "-otxt",
            "-of",
            str(output_base),
        ]

        if TRANSCRIPTION_LANGUAGE:
            command.extend(
                [
                    "-l",
                    TRANSCRIPTION_LANGUAGE,
                ]
            )

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or (
                    "whisper-cli exited with "
                    f"status {completed.returncode}"
                )
            )

        generated = Path(
            str(output_base) + ".txt"
        )

        if not generated.exists():
            raise RuntimeError(
                "whisper-cli finished but produced no transcript."
            )

        return {
            "backend": "whisper.cpp",
            "text": generated.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip(),
            "segments": [],
            "language": TRANSCRIPTION_LANGUAGE,
        }

    def _transcribe(self, audio_path):
        failures = []

        for name, function in (
            ("openai-whisper", self._transcribe_openai_whisper),
            ("faster-whisper", self._transcribe_faster_whisper),
            ("whisper.cpp", self._transcribe_whisper_cpp),
        ):
            try:
                return function(audio_path)
            except Exception as exc:
                failures.append(
                    f"{name}: {exc}"
                )
                report_warning(
                    "transcription backend",
                    failures[-1],
                )

        raise RuntimeError(
            "No usable local transcription backend. "
            + " | ".join(failures)
        )

    def run(self):
        while self.running:
            try:
                job = self.work_queue.get(
                    timeout=0.25
                )
            except queue.Empty:
                continue

            if job is None:
                break

            audio_path = Path(
                job["audio_path"]
            )
            reason = str(
                job.get("reason", "manual")
            )
            key = str(audio_path.resolve())

            try:
                if self._is_cancelled_path(
                    audio_path
                ):
                    continue

                self.status_ready.emit(
                    f"TRANSCRIBING: {audio_path.name}"
                )

                result = self._transcribe(audio_path)

                if self._is_cancelled_path(
                    audio_path
                ):
                    continue

                transcript_path = self._write_transcript(
                    audio_path,
                    result["backend"],
                    result["text"],
                    result["segments"],
                )

                result.update(
                    {
                        "audio_path": key,
                        "transcript_path": str(
                            transcript_path.resolve()
                        ),
                        "reason": reason,
                    }
                )

                self.result_ready.emit(result)

            except Exception as exc:
                report_exception(
                    f"transcription {audio_path}",
                    exc,
                )

                self.result_ready.emit(
                    {
                        "audio_path": key,
                        "error": str(exc),
                        "reason": reason,
                    }
                )

            finally:
                with self._queue_lock:
                    self._queued_paths.discard(key)

        self.status_ready.emit(
            "TRANSCRIPTION WORKER STOPPED"
        )

    def cancel_paths(self, paths):
        with self._queue_lock:
            for path in paths:
                try:
                    self._cancelled_paths.add(
                        str(
                            Path(
                                path
                            ).expanduser().resolve()
                        )
                    )
                except Exception:
                    pass

    def _is_cancelled_path(self, path):
        try:
            key = str(
                Path(path).expanduser().resolve()
            )
        except Exception:
            return False

        with self._queue_lock:
            return (
                key
                in self._cancelled_paths
            )


# ==============================================================================
# Recording playback
# ==============================================================================

class AudioPlaybackThread(QtCore.QThread):
    progress = QtCore.pyqtSignal(float, float)
    playback_status = QtCore.pyqtSignal(str)
    playback_finished = QtCore.pyqtSignal()

    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.filename = filename
        self._stop_requested = False
        self._paused = False
        self._state_lock = threading.Lock()

    def set_paused(self, paused):
        with self._state_lock:
            self._paused = bool(paused)

        self.playback_status.emit(
            "PAUSED" if paused else "PLAYING"
        )

    def stop_playback(self):
        with self._state_lock:
            self._stop_requested = True
            self._paused = False

    def run(self):
        try:
            with wave.open(self.filename, "rb") as wf:
                channels = int(wf.getnchannels())
                sample_width = int(wf.getsampwidth())
                sample_rate = int(wf.getframerate())
                total_frames = int(wf.getnframes())

                if sample_width != 2:
                    raise RuntimeError(
                        "Playback currently supports 16-bit WAV recordings"
                    )

                total_seconds = (
                    total_frames / sample_rate
                    if sample_rate > 0
                    else 0.0
                )

                self.playback_status.emit("PLAYING")

                with sd.RawOutputStream(
                    samplerate=sample_rate,
                    channels=channels,
                    dtype="int16",
                    blocksize=2048,
                ) as stream:
                    while True:
                        with self._state_lock:
                            should_stop = self._stop_requested
                            paused = self._paused

                        if should_stop:
                            self.playback_status.emit("STOPPED")
                            break

                        if paused:
                            time.sleep(0.05)
                            continue

                        data = wf.readframes(2048)
                        if not data:
                            self.playback_status.emit("FINISHED")
                            break

                        stream.write(data)

                        current_seconds = (
                            wf.tell() / sample_rate
                            if sample_rate > 0
                            else 0.0
                        )
                        self.progress.emit(
                            current_seconds,
                            total_seconds,
                        )

        except Exception as exc:
            report_exception(
                f"playback {self.filename}",
                exc,
            )
            self.playback_status.emit(
                f"PLAYBACK ERROR: {exc}"
            )

        finally:
            self.playback_finished.emit()


# ==============================================================================
# Main GUI
# ==============================================================================

class BCIAuraFrame(QtWidgets.QFrame):
    """Animated full-project border aura for the primary application shell."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self.setObjectName("bciAuraFrame")
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(AURA_FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self):
        self._phase = (self._phase + 0.055) % (2.0 * np.pi)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.Antialiasing,
            True,
        )

        rect = QtCore.QRectF(self.rect()).adjusted(
            4.5, 4.5, -4.5, -4.5
        )
        pulse = 0.5 + 0.5 * np.sin(self._phase)

        # Wide diffuse cyan aura.
        for width, alpha in (
            (9.0, int(20 + pulse * 14)),
            (5.0, int(34 + pulse * 18)),
            (2.0, int(92 + pulse * 36)),
        ):
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(0, 190, 207, alpha),
                    width,
                    QtCore.Qt.PenStyle.SolidLine,
                )
            )
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 12.0, 12.0)

        # A small crimson counter-accent keeps the shell from reading as neon blue.
        crimson = QtGui.QPen(
            QtGui.QColor(
                126,
                38,
                45,
                int(34 + (1.0 - pulse) * 24),
            ),
            1.2,
            QtCore.Qt.PenStyle.SolidLine,
        )
        painter.setPen(crimson)
        painter.drawRoundedRect(
            rect.adjusted(2.0, 2.0, -2.0, -2.0),
            10.0,
            10.0,
        )
        painter.end()


class MasterWaveformWidget(QtWidgets.QWidget):
    """Simple interactive waveform: drag to select a time range."""

    selectionChanged = QtCore.pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks = np.zeros((0, 2), dtype=np.float32)
        self._duration = 0.0
        self._selection_start = None
        self._selection_end = None
        self._dragging = False
        self.setMinimumHeight(230)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

    @property
    def duration(self):
        return float(self._duration)

    def selection(self):
        if self._selection_start is None or self._selection_end is None:
            return None
        start = min(self._selection_start, self._selection_end)
        end = max(self._selection_start, self._selection_end)
        if end - start < 0.01:
            return None
        return float(start), float(end)

    def clear_selection(self):
        self._selection_start = None
        self._selection_end = None
        self._dragging = False
        self.selectionChanged.emit(0.0, 0.0)
        self.update()

    def set_audio_file(self, path):
        path = Path(path)
        peaks = []
        duration = 0.0

        with wave.open(str(path), "rb") as wf:
            channels = int(wf.getnchannels())
            sample_width = int(wf.getsampwidth())
            sample_rate = int(wf.getframerate())
            frames = int(wf.getnframes())

            if sample_width != 2:
                raise RuntimeError(
                    "Mastering waveform supports 16-bit PCM WAV files."
                )

            duration = frames / sample_rate if sample_rate > 0 else 0.0
            target_bins = 2200
            frames_per_bin = max(1, frames // target_bins)

            remaining = frames
            carry = np.zeros(0, dtype=np.float32)

            while remaining > 0:
                count = min(65536, remaining)
                data = wf.readframes(count)
                if not data:
                    break
                remaining -= count

                samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
                if channels > 1:
                    usable = (samples.size // channels) * channels
                    samples = samples[:usable].reshape(-1, channels).mean(axis=1)
                samples /= 32768.0

                if carry.size:
                    samples = np.concatenate((carry, samples))
                    carry = np.zeros(0, dtype=np.float32)

                complete = samples.size // frames_per_bin
                if complete:
                    body = samples[:complete * frames_per_bin]
                    body = body.reshape(complete, frames_per_bin)
                    local_min = np.min(body, axis=1)
                    local_max = np.max(body, axis=1)
                    peaks.extend(zip(local_min.tolist(), local_max.tolist()))
                    samples = samples[complete * frames_per_bin:]

                carry = samples

            if carry.size:
                peaks.append(
                    (float(np.min(carry)), float(np.max(carry)))
                )

        self._peaks = np.asarray(peaks, dtype=np.float32)
        self._duration = float(duration)
        self.clear_selection()
        self.update()

    def _x_to_seconds(self, x):
        usable = max(1.0, float(self.width() - 24))
        ratio = np.clip((float(x) - 12.0) / usable, 0.0, 1.0)
        return float(ratio * self._duration)

    def _seconds_to_x(self, seconds):
        usable = max(1.0, float(self.width() - 24))
        ratio = (
            float(seconds) / self._duration
            if self._duration > 0.0
            else 0.0
        )
        return 12.0 + np.clip(ratio, 0.0, 1.0) * usable

    def mousePressEvent(self, event):
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._duration > 0.0
        ):
            value = self._x_to_seconds(event.position().x())
            self._selection_start = value
            self._selection_end = value
            self._dragging = True
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._selection_end = self._x_to_seconds(event.position().x())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._dragging
        ):
            self._selection_end = self._x_to_seconds(event.position().x())
            self._dragging = False
            selection = self.selection()
            if selection is None:
                self.clear_selection()
            else:
                self.selectionChanged.emit(*selection)
                self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.clear_selection()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.Antialiasing,
            True,
        )

        rect = QtCore.QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(
            QtGui.QPen(QtGui.QColor(36, 67, 76, 210), 1.0)
        )
        painter.setBrush(QtGui.QColor(5, 9, 13, 245))
        painter.drawRoundedRect(rect, 9.0, 9.0)

        plot = rect.adjusted(12.0, 18.0, -12.0, -28.0)
        mid = plot.center().y()

        painter.setPen(
            QtGui.QPen(QtGui.QColor(50, 73, 83, 100), 1.0)
        )
        painter.drawLine(
            QtCore.QPointF(plot.left(), mid),
            QtCore.QPointF(plot.right(), mid),
        )

        if self._peaks.size:
            width = max(1, int(plot.width()))
            source_bins = self._peaks.shape[0]
            indices = np.linspace(
                0,
                source_bins - 1,
                width,
                dtype=np.int64,
            )
            visible = self._peaks[indices]
            path = QtGui.QPainterPath()
            x0 = plot.left()
            amplitude = plot.height() * 0.46

            for i, (low, high) in enumerate(visible):
                x = x0 + i
                y1 = mid - float(high) * amplitude
                y2 = mid - float(low) * amplitude
                path.moveTo(x, y1)
                path.lineTo(x, y2)

            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(70, 203, 218, 220),
                    1.0,
                )
            )
            painter.drawPath(path)

        selection = self.selection()
        if selection is not None:
            x1 = self._seconds_to_x(selection[0])
            x2 = self._seconds_to_x(selection[1])
            selection_rect = QtCore.QRectF(
                x1,
                plot.top(),
                max(1.0, x2 - x1),
                plot.height(),
            )
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(112, 196, 211, 185),
                    1.0,
                )
            )
            painter.setBrush(
                QtGui.QColor(0, 157, 177, 48)
            )
            painter.drawRect(selection_rect)

        painter.setPen(QtGui.QColor(127, 146, 158, 220))
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(
            QtCore.QRectF(
                plot.left(),
                plot.bottom() + 5.0,
                plot.width(),
                18.0,
            ),
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "0:00",
        )
        painter.drawText(
            QtCore.QRectF(
                plot.left(),
                plot.bottom() + 5.0,
                plot.width(),
                18.0,
            ),
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"{int(self._duration // 60):d}:{int(self._duration % 60):02d}",
        )
        painter.end()


class BCIMasterDSP:
    """Pure NumPy/SciPy mastering helpers used by the manual editor."""

    @staticmethod
    def read_wav(path):
        path = Path(path)
        with wave.open(str(path), "rb") as wf:
            channels = int(wf.getnchannels())
            width = int(wf.getsampwidth())
            sample_rate = int(wf.getframerate())
            frames = int(wf.getnframes())
            if width != 2:
                raise RuntimeError(
                    "Mastering currently supports 16-bit PCM WAV files."
                )
            data = wf.readframes(frames)

        samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
        if channels > 1:
            usable = (samples.size // channels) * channels
            samples = samples[:usable].reshape(-1, channels).mean(axis=1)
        samples /= 32768.0
        return sample_rate, samples.astype(np.float32, copy=False)

    @staticmethod
    def write_wav(path, sample_rate, audio):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(str(path) + ".tmp")
        pcm = (
            np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
            * 32767.0
        ).astype("<i2")

        with wave.open(str(temp), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm.tobytes())

        os.replace(str(temp), str(path))

    @staticmethod
    def _bounds(audio, sample_rate, operation):
        start = operation.get("start")
        end = operation.get("end")
        if start is None or end is None:
            return 0, len(audio)

        i0 = int(np.clip(float(start) * sample_rate, 0, len(audio)))
        i1 = int(np.clip(float(end) * sample_rate, 0, len(audio)))
        if i1 < i0:
            i0, i1 = i1, i0
        return i0, i1

    @staticmethod
    def _strength(name):
        key = str(name or "Normal").lower()
        if key.startswith("light"):
            return 0
        if key.startswith("strong"):
            return 2
        return 1

    @staticmethod
    def _soft_peak(audio, ceiling=0.891):
        audio = np.asarray(audio, dtype=np.float32)
        if not audio.size:
            return audio
        peak = float(np.max(np.abs(audio)))
        if peak > ceiling:
            audio = audio * (ceiling / max(peak, 1e-9))
        return audio.astype(np.float32, copy=False)

    @staticmethod
    def _band_component(audio, sample_rate, low_hz, high_hz):
        nyquist = sample_rate * 0.5
        low = max(20.0, min(float(low_hz), nyquist * 0.90))
        high = max(low + 10.0, min(float(high_hz), nyquist * 0.95))
        if high <= low or len(audio) < 128:
            return np.zeros_like(audio, dtype=np.float32)

        sos = butter(
            3,
            [low, high],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )
        try:
            return sosfiltfilt(sos, audio).astype(np.float32)
        except Exception:
            return sosfilt(sos, audio).astype(np.float32)

    @classmethod
    def noise_reduce(cls, audio, sample_rate, strength):
        if len(audio) < 512:
            return audio
        level = cls._strength(strength)
        oversub = (0.80, 1.05, 1.28)[level]
        floor = (0.28, 0.16, 0.10)[level]

        nfft = min(2048, 2 ** int(np.floor(np.log2(max(256, len(audio))))))
        hop = max(64, nfft // 4)
        freqs, _, spectrum = stft(
            audio,
            fs=sample_rate,
            window="hann",
            nperseg=nfft,
            noverlap=nfft - hop,
            nfft=nfft,
            boundary="zeros",
            padded=True,
        )
        power = np.abs(spectrum).astype(np.float64) ** 2
        noise = np.percentile(power, 20.0, axis=1)
        signal_power = np.maximum(
            power - oversub * noise[:, None],
            0.0,
        )
        mask = np.sqrt(
            signal_power / (power + 1e-20)
        )
        mask = floor + (1.0 - floor) * np.clip(mask, 0.0, 1.0)

        # Mild frequency and time smoothing avoids watery artifacts.
        if mask.shape[0] >= 5:
            kernel = np.array([1, 2, 3, 2, 1], dtype=np.float64)
            kernel /= np.sum(kernel)
            for frame in range(mask.shape[1]):
                mask[:, frame] = np.convolve(
                    mask[:, frame],
                    kernel,
                    mode="same",
                )
        if mask.shape[1] >= 2:
            for frame in range(1, mask.shape[1]):
                mask[:, frame] = (
                    0.64 * mask[:, frame]
                    + 0.36 * mask[:, frame - 1]
                )

        _, result = istft(
            spectrum * mask,
            fs=sample_rate,
            window="hann",
            nperseg=nfft,
            noverlap=nfft - hop,
            nfft=nfft,
            input_onesided=True,
            boundary=True,
        )
        result = np.asarray(result[:len(audio)], dtype=np.float32)
        if len(result) < len(audio):
            result = np.pad(result, (0, len(audio) - len(result)))
        return result.astype(np.float32, copy=False)

    @classmethod
    def voice_clear(cls, audio, sample_rate, strength):
        level = cls._strength(strength)
        mud_db = (1.0, 1.8, 2.6)[level]
        presence_db = (1.2, 2.4, 3.4)[level]
        air_db = (0.3, 0.7, 1.0)[level]

        mud = cls._band_component(audio, sample_rate, 180.0, 500.0)
        presence = cls._band_component(audio, sample_rate, 1400.0, 4300.0)
        air = cls._band_component(audio, sample_rate, 4800.0, 8500.0)

        mud_gain = 10.0 ** (-mud_db / 20.0)
        presence_gain = 10.0 ** (presence_db / 20.0)
        air_gain = 10.0 ** (air_db / 20.0)

        result = (
            audio
            - mud * (1.0 - mud_gain)
            + presence * (presence_gain - 1.0)
            + air * (air_gain - 1.0)
        )
        return cls._soft_peak(result)

    @classmethod
    def remove_hum(cls, audio, sample_rate):
        if len(audio) < 2048:
            return audio

        sample = audio
        if len(sample) > sample_rate * 60:
            stride = max(1, len(sample) // (sample_rate * 60))
            sample = sample[::stride]

        window = np.hanning(len(sample))
        spectrum = np.abs(np.fft.rfft(sample * window)) + 1e-12
        freqs = np.fft.rfftfreq(len(sample), 1.0 / sample_rate)

        def family_score(base):
            scores = []
            for harmonic in range(1, 7):
                target = base * harmonic
                if target >= sample_rate * 0.45:
                    break
                idx = int(np.argmin(np.abs(freqs - target)))
                lo = max(0, idx - 8)
                hi = min(len(spectrum), idx + 9)
                local = spectrum[lo:hi]
                baseline = float(np.median(local)) if local.size else 1e-12
                db = 20.0 * np.log10(
                    max(float(spectrum[idx]), 1e-12)
                    / max(baseline, 1e-12)
                )
                scores.append(db)
            useful = [value for value in scores if value > 4.5]
            return (sum(useful), len(useful))

        candidates = []
        for base in (50.0, 60.0):
            score, count = family_score(base)
            if count >= 2:
                candidates.append((score, base))

        if not candidates:
            return audio

        _, base = max(candidates)
        result = np.asarray(audio, dtype=np.float64)
        for harmonic in range(1, 7):
            frequency = base * harmonic
            if frequency >= sample_rate * 0.45:
                break
            b, a = iirnotch(
                frequency,
                Q=36.0,
                fs=sample_rate,
            )
            if len(result) > 32:
                result = filtfilt(b, a, result)

        return result.astype(np.float32)

    @classmethod
    def even_volume(cls, audio, sample_rate, strength):
        level = cls._strength(strength)
        threshold = (-20.0, -24.0, -28.0)[level]
        ratio = (1.7, 2.4, 3.2)[level]
        frame_size = max(256, int(sample_rate * 0.025))
        result = np.asarray(audio, dtype=np.float32).copy()
        previous_gain = 1.0

        for start in range(0, len(result), frame_size):
            end = min(len(result), start + frame_size)
            frame = result[start:end]
            if not len(frame):
                continue
            rms = float(
                np.sqrt(np.mean(frame.astype(np.float64) ** 2) + 1e-20)
            )
            db = 20.0 * np.log10(max(rms, 1e-9))
            if db > threshold:
                compressed = threshold + (db - threshold) / ratio
                gain_db = compressed - db
            else:
                gain_db = 0.0
            desired = 10.0 ** (gain_db / 20.0)
            current = (
                0.55 * desired + 0.45 * previous_gain
                if desired < previous_gain
                else 0.10 * desired + 0.90 * previous_gain
            )
            ramp = np.linspace(
                previous_gain,
                current,
                len(frame),
                dtype=np.float32,
            )
            result[start:end] = frame * ramp
            previous_gain = current

        return result

    @classmethod
    def make_louder(cls, audio, sample_rate, strength):
        level = cls._strength(strength)
        target_rms_db = (-20.0, -17.0, -14.5)[level]
        max_gain_db = (12.0, 18.0, 24.0)[level]
        frame_size = max(512, int(sample_rate * 0.10))
        rms_values = []
        for start in range(0, len(audio), frame_size):
            frame = audio[start:start + frame_size]
            if not len(frame):
                continue
            rms_values.append(
                float(
                    np.sqrt(
                        np.mean(frame.astype(np.float64) ** 2)
                        + 1e-20
                    )
                )
            )

        if not rms_values:
            return audio

        active = float(np.percentile(rms_values, 75.0))
        target = 10.0 ** (target_rms_db / 20.0)
        gain = target / max(active, 1e-8)
        gain = min(gain, 10.0 ** (max_gain_db / 20.0))
        result = np.asarray(audio, dtype=np.float32) * gain
        return cls._soft_peak(result)

    @staticmethod
    def fade(audio, sample_rate, direction, seconds=None):
        result = np.asarray(audio, dtype=np.float32).copy()
        if not len(result):
            return result
        duration = (
            float(seconds)
            if seconds is not None
            else min(1.0, len(result) / sample_rate)
        )
        count = int(np.clip(duration * sample_rate, 1, len(result)))
        if direction == "in":
            result[:count] *= np.linspace(
                0.0, 1.0, count, dtype=np.float32
            )
        else:
            result[-count:] *= np.linspace(
                1.0, 0.0, count, dtype=np.float32
            )
        return result

    @staticmethod
    def trim_quiet_ends(audio, sample_rate):
        if len(audio) < sample_rate // 2:
            return audio
        frame = max(256, int(sample_rate * 0.05))
        rms = []
        starts = []
        for start in range(0, len(audio), frame):
            chunk = audio[start:start + frame]
            if not len(chunk):
                continue
            starts.append(start)
            rms.append(
                float(
                    np.sqrt(
                        np.mean(chunk.astype(np.float64) ** 2)
                        + 1e-20
                    )
                )
            )
        if not rms:
            return audio
        noise = float(np.percentile(rms, 15.0))
        threshold = max(noise * 2.2, 0.0018)
        active = [i for i, value in enumerate(rms) if value >= threshold]
        if not active:
            return audio
        pad = int(sample_rate * 0.15)
        first = max(0, starts[active[0]] - pad)
        last_start = starts[active[-1]]
        last = min(len(audio), last_start + frame + pad)
        return audio[first:last].copy()

    @classmethod
    def _process_region(cls, audio, sample_rate, operation, processor):
        i0, i1 = cls._bounds(audio, sample_rate, operation)
        if i1 <= i0:
            return audio
        region = audio[i0:i1]
        processed = np.asarray(processor(region), dtype=np.float32)
        if processed.shape != region.shape:
            raise RuntimeError(
                "An effect changed the selected region length unexpectedly."
            )

        # Tiny edge crossfade prevents clicks on selected-region effects.
        result = np.asarray(audio, dtype=np.float32).copy()
        blend = min(int(sample_rate * 0.012), len(region) // 2)
        if blend > 1:
            weight = np.ones(len(region), dtype=np.float32)
            weight[:blend] = np.linspace(0.0, 1.0, blend)
            weight[-blend:] = np.linspace(1.0, 0.0, blend)
            processed = region * (1.0 - weight) + processed * weight
        result[i0:i1] = processed
        return result

    @classmethod
    def apply_operations(cls, source_audio, sample_rate, operations, cancel=None):
        audio = np.asarray(source_audio, dtype=np.float32).copy()

        for operation in operations:
            if cancel is not None and cancel():
                raise RuntimeError("Mastering render cancelled.")

            kind = operation.get("kind")
            strength = operation.get("strength", "Normal")

            if kind == "cut":
                i0, i1 = cls._bounds(audio, sample_rate, operation)
                if i1 > i0:
                    audio = np.concatenate((audio[:i0], audio[i1:]))
            elif kind == "keep":
                i0, i1 = cls._bounds(audio, sample_rate, operation)
                if i1 > i0:
                    audio = audio[i0:i1].copy()
            elif kind == "trim":
                audio = cls.trim_quiet_ends(audio, sample_rate)
            elif kind == "fade_in":
                i0, i1 = cls._bounds(audio, sample_rate, operation)
                if operation.get("start") is None:
                    audio = cls.fade(audio, sample_rate, "in", 1.0)
                elif i1 > i0:
                    region = cls.fade(audio[i0:i1], sample_rate, "in")
                    audio = audio.copy()
                    audio[i0:i1] = region
            elif kind == "fade_out":
                i0, i1 = cls._bounds(audio, sample_rate, operation)
                if operation.get("start") is None:
                    audio = cls.fade(audio, sample_rate, "out", 1.0)
                elif i1 > i0:
                    region = cls.fade(audio[i0:i1], sample_rate, "out")
                    audio = audio.copy()
                    audio[i0:i1] = region
            elif kind == "noise":
                audio = cls._process_region(
                    audio,
                    sample_rate,
                    operation,
                    lambda region: cls.noise_reduce(
                        region, sample_rate, strength
                    ),
                )
            elif kind == "voice":
                audio = cls._process_region(
                    audio,
                    sample_rate,
                    operation,
                    lambda region: cls.voice_clear(
                        region, sample_rate, strength
                    ),
                )
            elif kind == "hum":
                audio = cls._process_region(
                    audio,
                    sample_rate,
                    operation,
                    lambda region: cls.remove_hum(region, sample_rate),
                )
            elif kind == "even":
                audio = cls._process_region(
                    audio,
                    sample_rate,
                    operation,
                    lambda region: cls.even_volume(
                        region, sample_rate, strength
                    ),
                )
            elif kind == "louder":
                audio = cls._process_region(
                    audio,
                    sample_rate,
                    operation,
                    lambda region: cls.make_louder(
                        region, sample_rate, strength
                    ),
                )
            elif kind == "auto":
                audio = cls.noise_reduce(audio, sample_rate, "Normal")
                audio = cls.remove_hum(audio, sample_rate)
                audio = cls.voice_clear(audio, sample_rate, "Normal")
                audio = cls.even_volume(audio, sample_rate, "Normal")
                audio = cls.make_louder(audio, sample_rate, "Normal")

            audio = np.nan_to_num(
                audio,
                nan=0.0,
                posinf=0.0,
                neginf=0.0,
            ).astype(np.float32, copy=False)

        return cls._soft_peak(audio)

    @staticmethod
    def metrics(audio, sample_rate):
        audio = np.asarray(audio, dtype=np.float32)
        if not len(audio):
            return {
                "duration": 0.0,
                "peak_dbfs": -120.0,
                "rms_dbfs": -120.0,
                "clip_fraction": 0.0,
            }
        peak = float(np.max(np.abs(audio)))
        rms = float(
            np.sqrt(np.mean(audio.astype(np.float64) ** 2) + 1e-20)
        )
        return {
            "duration": float(len(audio) / sample_rate),
            "peak_dbfs": float(20.0 * np.log10(max(peak, 1e-9))),
            "rms_dbfs": float(20.0 * np.log10(max(rms, 1e-9))),
            "clip_fraction": float(np.mean(np.abs(audio) >= 0.995)),
        }


class MasterRenderThread(QtCore.QThread):
    """Renders a non-destructive mastering edit list off the GUI thread."""

    result_ready = QtCore.pyqtSignal(object)
    status_ready = QtCore.pyqtSignal(str)

    def __init__(
        self,
        source_path,
        operations,
        output_path,
        mode,
        revision,
        parent=None,
    ):
        super().__init__(parent)
        self.source_path = Path(source_path)
        self.operations = [dict(item) for item in operations]
        self.output_path = Path(output_path)
        self.mode = str(mode)
        self.revision = int(revision)

    def run(self):
        try:
            self.status_ready.emit(
                "Rendering edited audio..."
            )
            sample_rate, source_audio = BCIMasterDSP.read_wav(
                self.source_path
            )
            source_metrics = BCIMasterDSP.metrics(
                source_audio,
                sample_rate,
            )
            result_audio = BCIMasterDSP.apply_operations(
                source_audio,
                sample_rate,
                self.operations,
                cancel=self.isInterruptionRequested,
            )

            if result_audio.size < max(1, sample_rate // 20):
                raise RuntimeError(
                    "The edit removed all usable audio."
                )

            BCIMasterDSP.write_wav(
                self.output_path,
                sample_rate,
                result_audio,
            )
            final_metrics = BCIMasterDSP.metrics(
                result_audio,
                sample_rate,
            )

            self.result_ready.emit(
                {
                    "ok": True,
                    "mode": self.mode,
                    "revision": self.revision,
                    "source_path": str(self.source_path),
                    "output_path": str(self.output_path),
                    "operations": len(self.operations),
                    "source_metrics": source_metrics,
                    "final_metrics": final_metrics,
                }
            )
        except Exception as exc:
            report_exception(
                f"manual mastering {self.source_path}",
                exc,
            )
            self.result_ready.emit(
                {
                    "ok": False,
                    "mode": self.mode,
                    "revision": self.revision,
                    "source_path": str(self.source_path),
                    "output_path": str(self.output_path),
                    "error": str(exc),
                }
            )

class BCIAdaptiveFrame(QtWidgets.QGraphicsView):
    """Scale the complete BCI interface to the available window area.

    BCIWhisper has a deliberately dense fixed-proportion workstation layout.
    Rather than allowing the desktop window to clip the bottom/right side on
    smaller displays, this view keeps one logical design canvas and applies a
    uniform presentation transform. Every control remains part of the same
    frame; resizing or maximizing the window simply recalculates the scale.
    """

    BASE_CANVAS = QtCore.QSize(1380, 900)
    VIEW_PADDING = 8

    def __init__(self, content_widget, parent=None):
        super().__init__(parent)

        self._content_widget = content_widget
        self._scene = QtWidgets.QGraphicsScene(self)
        self._proxy = self._scene.addWidget(content_widget)
        self._fit_pending = False

        self.setScene(self._scene)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setBackgroundBrush(QtGui.QColor("#05080d"))
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing
            | QtGui.QPainter.RenderHint.TextAntialiasing
        )
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate
        )
        self.setOptimizationFlag(
            QtWidgets.QGraphicsView.OptimizationFlag.DontSavePainterState,
            True,
        )
        self.setOptimizationFlag(
            QtWidgets.QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing,
            True,
        )

        # Keep a real desktop-sized layout canvas. The graphics view handles
        # shrinking/enlarging that canvas; Qt layouts inside it never have to
        # discard controls merely because the outer window is smaller.
        content_widget.resize(self.BASE_CANVAS)
        self.refresh_design_canvas()

    def refresh_design_canvas(self):
        """Re-evaluate the logical canvas, then fit it into the viewport."""

        self._content_widget.ensurePolished()

        size_hint = self._content_widget.sizeHint()
        minimum_hint = self._content_widget.minimumSizeHint()

        logical = QtCore.QSize(self.BASE_CANVAS)
        if size_hint.isValid():
            logical = logical.expandedTo(size_hint)
        if minimum_hint.isValid():
            logical = logical.expandedTo(minimum_hint)

        self._content_widget.resize(logical)
        self._proxy.resize(
            QtCore.QSizeF(
                float(logical.width()),
                float(logical.height()),
            )
        )
        self._scene.setSceneRect(self._proxy.sceneBoundingRect())
        self._schedule_fit()

    def _schedule_fit(self):
        if self._fit_pending:
            return
        self._fit_pending = True
        QtCore.QTimer.singleShot(0, self._fit_to_viewport)

    def _fit_to_viewport(self):
        self._fit_pending = False

        viewport_size = self.viewport().size()
        bounds = self._proxy.boundingRect()
        if (
            viewport_size.width() <= 0
            or viewport_size.height() <= 0
            or bounds.width() <= 0.0
            or bounds.height() <= 0.0
        ):
            return

        available_w = max(
            1.0,
            float(viewport_size.width() - (self.VIEW_PADDING * 2)),
        )
        available_h = max(
            1.0,
            float(viewport_size.height() - (self.VIEW_PADDING * 2)),
        )

        scale = min(
            available_w / float(bounds.width()),
            available_h / float(bounds.height()),
        )
        scale = max(0.10, scale)

        transform = QtGui.QTransform()
        transform.scale(scale, scale)
        self.setTransform(transform)
        self.centerOn(self._proxy)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_fit()


class BCIAudioBoundaryThread(QtCore.QThread):
    """Qt bridge to the isolated PortAudio input process.

    Boundary invariants:
      * the GUI thread never calls PortAudio input enumeration/open APIs;
      * the DSP QThread never calls them either;
      * exactly one child process owns input discovery + InputStream;
      * a native hang is recovered by terminating that process;
      * PCM crosses into the DSP ring as bounded messages;
      * device snapshots are immutable transaction results.
    """

    snapshot_ready = QtCore.pyqtSignal(dict)
    probe_error = QtCore.pyqtSignal(str)
    device_status = QtCore.pyqtSignal(str, bool)

    def __init__(self, audio_thread, initial_selection=None, parent=None):
        super().__init__(parent)
        self.setObjectName("BCI-AudioBoundary")
        self.audio_thread = audio_thread
        self._commands = queue.Queue(maxsize=64)
        self._stop_requested = threading.Event()
        self._initial_selection = dict(initial_selection or {})
        self._selection_lock = threading.Lock()
        self._last_requested_selection = {
            "mode": str(self._initial_selection.get("mode", "auto") or "auto"),
            "device_name": str(self._initial_selection.get("device_name", "") or ""),
            "device_id": int(self._initial_selection.get("device_id", -1)),
        }
        self._supervisor = None

    def _enqueue(self, command):
        try:
            self._commands.put_nowait(dict(command))
        except queue.Full:
            try:
                self._commands.get_nowait()
            except Exception:
                pass
            try:
                self._commands.put_nowait(dict(command))
            except Exception:
                pass

    def set_selection(self, mode="auto", device_name="", device_id=-1):
        selection = {
            "mode": str(mode or "auto"),
            "device_name": str(device_name or ""),
            "device_id": int(device_id),
        }
        with self._selection_lock:
            if selection == self._last_requested_selection:
                return
            self._last_requested_selection = dict(selection)
        command = {"type": "select"}
        command.update(selection)
        self._enqueue(command)

    def request_probe(self):
        self._enqueue({"type": "refresh"})

    def request_reopen(self):
        self._enqueue({"type": "reopen"})

    def stop(self, wait_ms=10000):
        self._stop_requested.set()
        self.requestInterruption()
        self._enqueue({"type": "shutdown"})
        if self.isRunning():
            self.wait(int(wait_ms))

    def _handle_event(self, event):
        kind = str(event.get("type", ""))

        if kind == "snapshot":
            snapshot = dict(event.get("snapshot", {}) or {})
            self.audio_thread.offer_hardware_snapshot(snapshot)
            self.snapshot_ready.emit(snapshot)
            return

        if kind == "stream_opened":
            self.audio_thread.offer_hardware_session(event)
            return

        if kind == "status":
            self.device_status.emit(
                str(event.get("message", "Audio boundary status")),
                bool(event.get("success", True)),
            )
            return

        if kind == "stream_closed":
            reason = str(event.get("reason", "boundary_reopen") or "boundary_reopen")
            if reason == "boundary_reopen":
                self.audio_thread.invalidate_hardware_session(reason)
            return

        if kind in ("waiting", "open_error", "stream_lost", "process_error"):
            message = str(
                event.get("message")
                or event.get("reason")
                or "Audio boundary unavailable"
            )
            self.audio_thread.invalidate_hardware_session(message)
            self.device_status.emit(message, False)
            if kind in ("open_error", "process_error"):
                self.probe_error.emit(message)
            return

        if kind == "route_changed":
            self.device_status.emit(
                str(event.get("message", "System audio route changed")),
                True,
            )
            return

        if kind == "callback_drop":
            dropped = int(event.get("dropped", 0) or 0)
            if dropped > 0:
                self.device_status.emit(
                    f"Audio boundary dropped {dropped} stale callback block(s)",
                    False,
                )
            return

    def run(self):
        supervisor = BCIAudioCaptureSupervisor(
            block_size=BLOCK_SIZE,
            watchdog_seconds=AUDIO_BOUNDARY_WATCHDOG_SECONDS,
        )
        self._supervisor = supervisor
        supervisor.start(self._initial_selection)

        try:
            while not self.isInterruptionRequested():
                if self._stop_requested.is_set():
                    break

                # Serialize all operator/probe/reopen intents into the one child.
                for _ in range(16):
                    try:
                        command = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    except Exception:
                        break
                    if command.get("type") == "shutdown":
                        self._stop_requested.set()
                        break
                    supervisor.send(command)

                if self._stop_requested.is_set():
                    break

                polled = supervisor.poll(max_events=64, max_audio=64)
                for event in polled.events:
                    self._handle_event(event)

                for packet in polled.audio:
                    self.audio_thread.accept_capture_packet(packet)

                expired, reason = supervisor.watchdog_expired()
                if expired:
                    self.audio_thread.invalidate_hardware_session(reason)
                    self.probe_error.emit(
                        f"Audio boundary watchdog: {reason}; restarting process"
                    )
                    self.device_status.emit(
                        "Audio hardware process stalled; restarting isolated capture...",
                        False,
                    )
                    supervisor.restart(reason)

                self.msleep(10)

        except Exception as exc:
            self.audio_thread.invalidate_hardware_session(str(exc))
            self.probe_error.emit(f"Audio boundary thread failure: {exc}")

        finally:
            supervisor.stop()
            self._supervisor = None



class BCIWindow(QtWidgets.QMainWindow):
    @property
    def boot_in_progress(self):
        return self.app_state.boot_in_progress

    @property
    def analysis_started(self):
        return self.app_state.analysis_started

    @property
    def _main_display_entered(self):
        return self.app_state.main_display_entered

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Beacon Computing Initiative (BCI) — "
            f"Advanced Acoustic Suite // {BCI_PROJECT_VERSION} "
            f"// Build {BCI_BUILD}"
        )

        if LOGO_ASSET.exists():
            self.setWindowIcon(
                QtGui.QIcon(str(LOGO_ASSET))
            )

        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(1380, max(720, available.width() - 32))
            target_height = min(900, max(520, available.height() - 48))
            self.resize(target_width, target_height)
        else:
            self.resize(1380, 900)

        self.setMinimumSize(640, 480)
        self.setStyleSheet(
            "QMainWindow {"
            "background-color: #05080d;"
            "}"
            "QWidget {"
            "color: #dce6ec;"
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "}"
            "QPushButton {"
            "background: #111820;"
            "border: 1px solid #294a55;"
            "border-radius: 5px;"
            "padding: 6px 10px;"
            "color: #c9d5dc;"
            "}"
            "QPushButton:hover {"
            "border-color: #4d8f9c;"
            "background: #142029;"
            "}"
            "QPushButton:pressed {"
            "background: #0b141b;"
            "}"
            "QComboBox, QSlider, QPlainTextEdit, QTableWidget {"
            "selection-background-color: #164652;"
            "selection-color: #edf3f6;"
            "}"
        )

        self.settings = QtCore.QSettings(
            "CJB-DEV-2026",
            "BCIWhisper",
        )

        # Script 57.7: one application state machine owns boot/analyzer/recovery
        # state.  The GUI no longer maintains three independently mutable flags.
        self.app_state = BCIApplicationStateMachine()
        self._last_signal_active = False
        self._last_status_text = None
        self._last_status_style = None

        # Script 57.2: keep the boot/analyzer page switch OUTSIDE the
        # QGraphicsProxyWidget.  In 57.1 the QStackedWidget itself was embedded
        # in BCIAdaptiveFrame's graphics scene.  Qt could commit currentIndex=1
        # while the proxy continued presenting the last boot-page backing store.
        # The root stack is now a normal central widget; only the dense analyzer
        # workspace is graphics-scaled.  This makes the boot -> analyzer handoff
        # a native QWidget visibility transition rather than a proxied child
        # transition.
        self.page_stack = QtWidgets.QStackedWidget()
        self.page_stack.setObjectName("BCIPageStack")
        self.setCentralWidget(self.page_stack)

        self.boot_screen = BCIBootScreen()
        self.boot_screen.setObjectName("BCIBootPage")
        self.page_stack.addWidget(self.boot_screen)

        central_widget = QtWidgets.QWidget()
        self.analysis_page = central_widget
        self.analysis_page.setObjectName("BCIAnalyzerCanvas")
        self.adaptive_frame = BCIAdaptiveFrame(self.analysis_page)
        self.adaptive_frame.setObjectName("BCIAnalyzerFrame")
        self.page_stack.addWidget(self.adaptive_frame)
        self.page_stack.setCurrentWidget(self.boot_screen)

        central_layout = QtWidgets.QVBoxLayout(self.analysis_page)
        central_layout.setContentsMargins(8, 8, 8, 8)

        self.main_tabs = QtWidgets.QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.main_tabs.setStyleSheet(
            "QTabWidget::pane {"
            "border: 1px solid rgba(0, 176, 194, 105);"
            "border-radius: 7px;"
            "background: #0b1016;"
            "}"
            "QTabBar::tab {"
            "font-family: 'DejaVu Sans';"
            "font-size: 15px;"
            "font-weight: bold;"
            "letter-spacing: 0.7px;"
            "padding: 10px 20px;"
            "min-width: 128px;"
            "background: #111820;"
            "color: #81909a;"
            "border: 1px solid #23313a;"
            "}"
            "QTabBar::tab:selected {"
            "color: #dce8ee;"
            "background: #0d151c;"
            "border-color: #357684;"
            "}"
        )

        self.app_aura_frame = BCIAuraFrame()
        aura_layout = QtWidgets.QVBoxLayout(
            self.app_aura_frame
        )
        aura_layout.setContentsMargins(8, 8, 8, 8)
        aura_layout.addWidget(self.main_tabs)
        central_layout.addWidget(self.app_aura_frame)

        self.monitor_tab = QtWidgets.QWidget()
        self.recordings_tab = QtWidgets.QWidget()
        self.transcripts_tab = QtWidgets.QWidget()
        self.mastering_tab = QtWidgets.QWidget()

        self.main_tabs.addTab(
            self.monitor_tab,
            "MONITOR",
        )
        self.main_tabs.addTab(
            self.recordings_tab,
            "RECORDINGS",
        )
        self.main_tabs.addTab(
            self.transcripts_tab,
            "TRANSCRIPTS",
        )
        self.main_tabs.addTab(
            self.mastering_tab,
            "MASTERING",
        )

        main_layout = QtWidgets.QHBoxLayout(
            self.monitor_tab
        )

        self._build_recordings_tab()
        self._build_transcripts_tab()
        self._build_mastering_tab()

        # ----------------------------------------------------------------------
        # Control panel
        # ----------------------------------------------------------------------

        control_panel = QtWidgets.QWidget()
        control_panel.setFixedWidth(390)
        control_panel.setStyleSheet(
            "background-color: #21262d;"
            "border-radius: 6px;"
            "padding: 8px;"
        )

        control_layout = QtWidgets.QVBoxLayout(control_panel)

        title = QtWidgets.QLabel("ADVANCED SIGNAL TUNING")
        title.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-weight: bold;"
            "color: #6bb8c7;"
            "font-size: 14px;"
            "letter-spacing: 0.6px;"
        )
        control_layout.addWidget(title)

        advanced_note = QtWidgets.QLabel(
            "These controls are optional. The microphone and input volume "
            "are now always visible on the main display."
        )
        advanced_note.setWordWrap(True)
        advanced_note.setStyleSheet(
            "font-size: 12px;"
            "color: #87959e;"
        )
        control_layout.addWidget(advanced_note)
        control_layout.addSpacing(8)

        self.lowcut_value = QtWidgets.QLabel()
        control_layout.addWidget(
            QtWidgets.QLabel("Lowcut Filter:")
        )
        control_layout.addWidget(self.lowcut_value)

        self.lowcut_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.lowcut_slider.setRange(20, 2000)
        self.lowcut_slider.setValue(int(DEFAULT_LOWCUT))
        control_layout.addWidget(self.lowcut_slider)

        self.highcut_value = QtWidgets.QLabel()
        control_layout.addWidget(
            QtWidgets.QLabel("Highcut Filter:")
        )
        control_layout.addWidget(self.highcut_value)

        self.highcut_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.highcut_slider.setRange(500, 20000)
        self.highcut_slider.setValue(int(DEFAULT_HIGHCUT))
        control_layout.addWidget(self.highcut_slider)

        self.sens_value = QtWidgets.QLabel()
        control_layout.addWidget(
            QtWidgets.QLabel("Trigger Sensitivity:")
        )
        control_layout.addWidget(self.sens_value)

        self.sens_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.sens_slider.setRange(5, 25)
        self.sens_slider.setValue(
            int(DEFAULT_SENSITIVITY * 10)
        )
        control_layout.addWidget(self.sens_slider)

        help_label = QtWidgets.QLabel(
            "BCI boot restores the last microphone and learns the room for 60 seconds.\n"
            "Triggering and recording begin only after the room profile is established.\n"
            "Lowcut/Highcut define the broad listening band.\n"
            "Trigger Sensitivity controls how easily a signal starts recording.\n"
            "The main display follows Ubuntu's default microphone in AUTO mode and also lists USB camera / Bluetooth inputs.\n"
            "Changing these signal controls automatically refreshes the ambient calibration."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet(
            "font-size: 12px;"
            "color: #b1bac4;"
        )
        control_layout.addWidget(help_label)

        control_layout.addStretch()
        main_layout.addWidget(control_panel)

        # ----------------------------------------------------------------------
        # Spectrum area
        # ----------------------------------------------------------------------

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)

        header_row = QtWidgets.QHBoxLayout()

        header = QtWidgets.QLabel(
            "BEACON COMPUTING INITIATIVE // "
            "ACOUSTIC RADAR TELEMETRY"
        )
        header.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 20px;"
            "font-weight: bold;"
            "color: #71c7ff;"
            "letter-spacing: 1.2px;"
        )
        header_row.addWidget(header)

        header_row.addStretch()

        self.monitor_version_badge = QtWidgets.QLabel(
            f"{BCI_PROJECT_VERSION}  •  Script {BCI_SCRIPT_REVISION}"
        )
        self.monitor_version_badge.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "font-weight: bold;"
            "color: #9aa7b2;"
            "background: #0d1117;"
            "border: 1px solid #30363d;"
            "border-radius: 4px;"
            "padding: 5px 8px;"
        )
        header_row.addWidget(
            self.monitor_version_badge
        )

        right_layout.addLayout(
            header_row
        )

        # ------------------------------------------------------------------
        # Live input controls — simple wording and always visible.
        # ------------------------------------------------------------------
        self.live_input_frame = QtWidgets.QFrame()
        self.live_input_frame.setObjectName("liveInputFrame")
        self.live_input_frame.setStyleSheet(
            "QFrame#liveInputFrame {"
            "background: rgba(8, 14, 19, 225);"
            "border: 1px solid rgba(0, 184, 201, 105);"
            "border-radius: 9px;"
            "}"
            "QComboBox {"
            "background: #0d151b;"
            "border: 1px solid #314954;"
            "border-radius: 5px;"
            "padding: 6px 30px 6px 9px;"
            "color: #dce6ec;"
            "selection-background-color: #234852;"
            "selection-color: #f2f6f8;"
            "}"
            "QComboBox:hover {"
            "border-color: #4e7d88;"
            "}"
            "QComboBox:focus {"
            "border-color: #5c909b;"
            "}"
            "QComboBox::drop-down {"
            "subcontrol-origin: padding;"
            "subcontrol-position: top right;"
            "width: 26px;"
            "background: #111c23;"
            "border-left: 1px solid #314954;"
            "border-top-right-radius: 5px;"
            "border-bottom-right-radius: 5px;"
            "}"
            "QComboBox QAbstractItemView {"
            "background-color: #0a1117;"
            "color: #dce6ec;"
            "border: 1px solid #314954;"
            "selection-background-color: #234852;"
            "selection-color: #f2f6f8;"
            "outline: 0;"
            "padding: 4px;"
            "}"
            "QSlider::groove:horizontal {"
            "height: 7px;"
            "background: #16232b;"
            "border-radius: 3px;"
            "}"
            "QSlider::sub-page:horizontal {"
            "background: #2d8794;"
            "border-radius: 3px;"
            "}"
            "QSlider::handle:horizontal {"
            "background: #d8e2e7;"
            "border: 1px solid #5e747e;"
            "width: 17px;"
            "margin: -6px 0;"
            "border-radius: 8px;"
            "}"
        )

        live_input_layout = QtWidgets.QVBoxLayout(
            self.live_input_frame
        )
        live_input_layout.setContentsMargins(14, 11, 14, 11)
        live_input_layout.setSpacing(8)

        live_title_row = QtWidgets.QHBoxLayout()

        live_title = QtWidgets.QLabel("LIVE AUDIO INPUT")
        live_title.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 13px;"
            "font-weight: 800;"
            "color: #a9cbd2;"
            "letter-spacing: 1.0px;"
            "background: transparent;"
            "border: none;"
        )
        live_title_row.addWidget(live_title)
        live_title_row.addStretch()

        self.input_volume_value = QtWidgets.QLabel("100%")
        self.input_volume_value.setMinimumWidth(52)
        self.input_volume_value.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.input_volume_value.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 14px;"
            "font-weight: 800;"
            "color: #dce6ec;"
            "background: transparent;"
            "border: none;"
        )
        live_title_row.addWidget(self.input_volume_value)
        live_input_layout.addLayout(live_title_row)

        device_row = QtWidgets.QHBoxLayout()

        device_label = QtWidgets.QLabel("Audio Input")
        device_label.setFixedWidth(92)
        device_label.setStyleSheet(
            "color: #9aa8b1;"
            "font-weight: 700;"
            "background: transparent;"
            "border: none;"
        )
        device_row.addWidget(device_label)

        self.mic_combo = QtWidgets.QComboBox()
        self.mic_combo.setToolTip(
            "Choose System Default, a USB microphone, or a paired Bluetooth microphone."
        )
        self.mic_combo.setMaxVisibleItems(12)

        # Force a dark popup independently of the host desktop theme.
        mic_popup = self.mic_combo.view()
        mic_popup.setStyleSheet(
            "QAbstractItemView {"
            "background: #0a1117;"
            "color: #dce6ec;"
            "border: 1px solid #314954;"
            "outline: 0;"
            "padding: 3px;"
            "selection-background-color: #234852;"
            "selection-color: #f2f6f8;"
            "}"
            "QAbstractItemView::item {"
            "min-height: 28px;"
            "padding: 4px 8px;"
            "border: none;"
            "}"
            "QAbstractItemView::item:hover {"
            "background: #172a32;"
            "color: #f2f6f8;"
            "}"
            "QScrollBar:vertical {"
            "background: #0a1117;"
            "width: 10px;"
            "margin: 0;"
            "}"
            "QScrollBar::handle:vertical {"
            "background: #35515b;"
            "border-radius: 5px;"
            "min-height: 28px;"
            "}"
            "QScrollBar::add-line:vertical,"
            "QScrollBar::sub-line:vertical {"
            "height: 0px;"
            "}"
        )

        popup_palette = mic_popup.palette()
        popup_palette.setColor(
            QtGui.QPalette.ColorRole.Base,
            QtGui.QColor("#0a1117"),
        )
        popup_palette.setColor(
            QtGui.QPalette.ColorRole.Text,
            QtGui.QColor("#dce6ec"),
        )
        popup_palette.setColor(
            QtGui.QPalette.ColorRole.Highlight,
            QtGui.QColor("#234852"),
        )
        popup_palette.setColor(
            QtGui.QPalette.ColorRole.HighlightedText,
            QtGui.QColor("#f2f6f8"),
        )
        mic_popup.setPalette(popup_palette)

        device_row.addWidget(self.mic_combo, 1)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.setToolTip(
            "Refresh System Default, USB inputs, and paired Bluetooth devices."
        )
        self.refresh_button.setMaximumWidth(92)
        device_row.addWidget(self.refresh_button)
        live_input_layout.addLayout(device_row)

        volume_row = QtWidgets.QHBoxLayout()

        volume_label = QtWidgets.QLabel("Input Volume")
        volume_label.setFixedWidth(92)
        volume_label.setStyleSheet(
            "color: #9aa8b1;"
            "font-weight: 700;"
            "background: transparent;"
            "border: none;"
        )
        volume_row.addWidget(volume_label)

        self.input_volume_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.input_volume_slider.setRange(25, 200)

        saved_input_volume = self.settings.value(
            "input_volume_percent",
            100,
            type=int,
        )
        saved_input_volume = max(
            25,
            min(
                200,
                int(saved_input_volume),
            ),
        )
        self.input_volume_slider.setValue(saved_input_volume)
        self.input_volume_slider.setToolTip(
            "Changes the live recording level inside BCIWhisper. "
            "100% is the normal BCI input level."
        )
        volume_row.addWidget(self.input_volume_slider, 1)
        live_input_layout.addLayout(volume_row)

        self.input_volume_help = QtWidgets.QLabel(
            "100% = normal input level  •  Lower if the signal clips  •  "
            "Raise if the recording is too quiet"
        )
        self.input_volume_help.setWordWrap(True)
        self.input_volume_help.setStyleSheet(
            "font-size: 11px;"
            "color: #71818a;"
            "background: transparent;"
            "border: none;"
        )
        live_input_layout.addWidget(self.input_volume_help)

        self.device_status_label = QtWidgets.QLabel(
            "Audio input not opened yet."
        )
        self.device_status_label.setWordWrap(True)
        self.device_status_label.setStyleSheet(
            "font-size: 11px;"
            "color: #84939c;"
            "background: transparent;"
            "border: none;"
        )
        live_input_layout.addWidget(self.device_status_label)

        self.short_event_status_label = QtWidgets.QLabel(
            f"Save rule: keep recordings only after "
            f"{MIN_SAVED_LOCK_SECONDS:.0f}s of confirmed signal lock. "
            "Shorter detections are logged automatically."
        )
        self.short_event_status_label.setWordWrap(True)
        self.short_event_status_label.setStyleSheet(
            "font-size: 11px;"
            "color: #71818a;"
            "background: transparent;"
            "border: none;"
        )
        self.short_event_status_label.setToolTip(
            f"Short-event history: {SHORT_EVENT_LOG}"
        )
        live_input_layout.addWidget(
            self.short_event_status_label
        )

        live_broadcast_row = QtWidgets.QHBoxLayout()

        self.go_live_button = QtWidgets.QPushButton(
            "GO LIVE"
        )
        self.go_live_button.setCheckable(
            True
        )
        self.go_live_button.setMinimumHeight(
            34
        )
        self.go_live_button.setStyleSheet(
            "QPushButton {"
            "background: #0d171d;"
            "border: 1px solid #365a64;"
            "border-radius: 6px;"
            "padding: 7px 14px;"
            "font-weight: 800;"
            "letter-spacing: 0.8px;"
            "color: #b8cbd1;"
            "}"
            "QPushButton:hover {"
            "background: #112129;"
            "border-color: #4c7d88;"
            "}"
            "QPushButton:checked {"
            "background: #291216;"
            "border-color: #7e2730;"
            "color: #e8d7da;"
            "}"
        )
        live_broadcast_row.addWidget(
            self.go_live_button
        )

        self.live_status_label = QtWidgets.QLabel(
            "OFFLINE"
        )
        self.live_status_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "font-weight: 800;"
            "color: #6f7e86;"
            "background: transparent;"
            "border: none;"
        )
        live_broadcast_row.addWidget(
            self.live_status_label
        )

        live_broadcast_row.addStretch()

        self.live_clients_label = QtWidgets.QLabel(
            "0 listeners"
        )
        self.live_clients_label.setStyleSheet(
            "font-size: 11px;"
            "color: #71818a;"
            "background: transparent;"
            "border: none;"
        )
        live_broadcast_row.addWidget(
            self.live_clients_label
        )

        live_input_layout.addLayout(
            live_broadcast_row
        )

        self.live_url_label = QtWidgets.QLabel(
            "Go Live is off. No streaming server is running."
        )
        self.live_url_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.live_url_label.setWordWrap(
            True
        )
        self.live_url_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 11px;"
            "color: #71818a;"
            "background: transparent;"
            "border: none;"
        )
        live_input_layout.addWidget(
            self.live_url_label
        )

        right_layout.addWidget(self.live_input_frame)

        self.status_label = QtWidgets.QLabel(
            "STATUS: STARTING AUDIO ENGINE..."
        )
        self.status_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 15px;"
            "font-weight: bold;"
            "color: #d7e0e7;"
            "padding: 7px;"
        )
        right_layout.addWidget(self.status_label)

        self.runtime_error_label = QtWidgets.QLabel()
        self.runtime_error_label.setWordWrap(True)
        self.runtime_error_label.setVisible(False)
        self.runtime_error_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "font-weight: bold;"
            "color: #ff8580;"
            "letter-spacing: 0.5px;"
            "background: #2d1717;"
            "border: 1px solid #f85149;"
            "border-radius: 5px;"
            "padding: 7px;"
        )
        right_layout.addWidget(
            self.runtime_error_label
        )

        broad_title = QtWidgets.QLabel("BROAD LISTENING SPECTRUM")
        broad_title.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "font-weight: bold;"
            "color: #d7e0e7;"
            "letter-spacing: 0.5px;"
        )
        right_layout.addWidget(broad_title)

        self.spectrum_widget = SpectrumWidget()
        self.spectrum_widget.setMinimumHeight(220)
        right_layout.addWidget(self.spectrum_widget)

        isolated_header_row = QtWidgets.QHBoxLayout()

        isolated_title = QtWidgets.QLabel(
            "ISOLATED LOCKED SIGNAL // DEDICATED ANALYSIS THREAD"
        )
        isolated_title.setStyleSheet(
            "font-size: 13px;"
            "font-weight: bold;"
            "color: #ff7b72;"
        )
        isolated_header_row.addWidget(isolated_title)

        isolated_header_row.addStretch()

        self.classification_label = QtWidgets.QLabel(
            "CLASSIFICATION: WAITING"
        )
        self.classification_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 13px;"
            "font-weight: bold;"
            "color: #d7e0e7;"
            "padding: 4px 8px;"
            "border: 1px solid #30363d;"
            "border-radius: 4px;"
        )
        isolated_header_row.addWidget(
            self.classification_label
        )

        right_layout.addLayout(isolated_header_row)

        self.isolated_widget = SpectrumWidget(isolated_only=True)
        self.isolated_widget.setMinimumHeight(220)
        right_layout.addWidget(self.isolated_widget)

        transcript_header = QtWidgets.QLabel(
            "TRANSCRIPTION // LOCAL ASR"
        )
        transcript_header.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "font-weight: bold;"
            "color: #00eeff;"
            "letter-spacing: 0.6px;"
        )
        right_layout.addWidget(transcript_header)

        self.analysis_transcript = QtWidgets.QPlainTextEdit()
        self.analysis_transcript.setReadOnly(True)
        self.analysis_transcript.setMaximumHeight(115)
        self.analysis_transcript.setPlaceholderText(
            "Completed locked recordings will be transcribed locally "
            "when a Whisper backend is available."
        )
        self.analysis_transcript.setStyleSheet(
            "QPlainTextEdit {"
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 13px;"
            "color: #dce8ee;"
            "background: #090d12;"
            "border: 1px solid #30363d;"
            "border-radius: 5px;"
            "padding: 6px;"
            "}"
        )
        right_layout.addWidget(self.analysis_transcript)

        footer = QtWidgets.QLabel(
            "Developer Seal: CJB-DEV-2026 | "
            f"Lead Developer: {BCI_LEAD_DEVELOPER} | "
            f"Project: {BCI_PROJECT_VERSION} | "
            f"Script: {BCI_SCRIPT_TALLY} | "
            f"Build: {BCI_BUILD} | "
            "Use the RECORDINGS tab to browse and play Raw + Isolated WAV clips."
        )
        footer.setStyleSheet(
            "font-size: 12px;"
            "color: #8b949e;"
        )
        right_layout.addWidget(footer)

        main_layout.addWidget(right_panel)

        # ----------------------------------------------------------------------
        # Worker
        # ----------------------------------------------------------------------

        self.audio_thread = AudioProcessorThread()

        # v6 broadcast foundation. The bus/controller are platform-neutral and
        # remain independent from the legacy local HTTP/MP3 broadcaster.
        self.broadcast_bus = BroadcastBus(
            audio_capacity=24,
            telemetry_capacity=8,
        )
        self.go_live_controller = GoLiveController()

        self.live_broadcaster = BCILiveBroadcastServer(
            self
        )
        self.live_broadcaster.status_changed.connect(
            self.handle_live_status
        )
        self.live_broadcaster.client_count_changed.connect(
            self.handle_live_client_count
        )
        self.live_broadcaster.stream_error.connect(
            self.handle_live_error
        )
        self.audio_thread.live_audio_block.connect(
            self.handle_live_audio_block
        )
        self.go_live_button.toggled.connect(
            self.set_go_live
        )

        self.postprocess_thread = PostProcessThread(self)
        self.postprocess_thread.result_ready.connect(
            self.handle_postprocess_result
        )
        self.postprocess_thread.status_ready.connect(
            self.handle_postprocess_status
        )

        self.transcription_thread = TranscriptionThread(self)
        self.transcription_thread.result_ready.connect(
            self.handle_transcription_result
        )
        self.transcription_thread.status_ready.connect(
            self.handle_transcription_status
        )
        self.transcription_thread.result_ready.connect(
            self.handle_transcripts_tab_result
        )
        self.transcription_thread.status_ready.connect(
            self.handle_transcripts_tab_status
        )

        self.isolated_analysis_thread = (
            IsolatedSpectrumThread(self)
        )
        self.isolated_analysis_thread.result_ready.connect(
            self.handle_isolated_analysis
        )

        self.audio_thread.isolated_block_ready.connect(
            self.isolated_analysis_thread.submit
        )
        self.audio_thread.baseline_started.connect(
            self.handle_baseline_started
        )
        self.audio_thread.baseline_interrupted.connect(
            self.handle_baseline_interrupted
        )
        self.audio_thread.boot_complete.connect(
            self.handle_boot_complete
        )

        self.audio_thread.spectrum_ready.connect(
            self.handle_audio_data
        )
        self.audio_thread.device_status.connect(
            self.handle_device_status
        )
        self.audio_thread.error_event.connect(
            self.handle_runtime_error
        )
        self.audio_thread.recording_saved.connect(
            self.handle_recording_saved
        )
        self.audio_thread.short_event_logged.connect(
            self.handle_short_event_logged
        )

        self.playback_thread = None

        # Coalesce slider drags so a single drag causes one recalibration,
        # rather than restarting calibration for every intermediate tick.
        self._param_debounce = QtCore.QTimer(
            self
        )
        self._param_debounce.setSingleShot(
            True
        )
        self._param_debounce.setInterval(
            300
        )
        self._param_debounce.timeout.connect(
            self.apply_params_now
        )

        self.refresh_recordings()

        saved_device_id = self.settings.value(
            "last_input_device_id",
            -999,
            type=int,
        )
        saved_device_name = self.settings.value(
            "last_input_device_name",
            "",
            type=str,
        )
        saved_selection_mode = self.settings.value(
            "input_selection_mode",
            "auto",
            type=str,
        )

        # Script 57: never enumerate PortAudio, PipeWire/Pulse or BlueZ on
        # the GUI thread. Populate an immediately usable System Default entry,
        # then let the background probe publish a complete cached snapshot.
        self._cached_audio_devices = []
        self._cached_paired_bluetooth = []
        self._audio_device_snapshot = None
        self._system_default_signature = None
        self._audio_probe_initialized = False
        self._saved_device_id = saved_device_id
        self._saved_device_name = saved_device_name
        self._saved_selection_mode = saved_selection_mode

        self.populate_audio_devices(
            preserve_device_id=saved_device_id,
            preserve_device_name=saved_device_name,
            selection_mode=saved_selection_mode,
        )

        # Script 57.7: one process owns PortAudio input discovery/open/capture.
        # Qt and the DSP worker interact only with this supervisor boundary.
        initial_boundary_selection = {
            "mode": str(saved_selection_mode or "auto"),
            "device_name": (
                str(saved_device_name or "")
                if str(saved_selection_mode or "auto").lower() == "explicit"
                else ""
            ),
            "device_id": int(saved_device_id),
        }
        self.audio_boundary_thread = BCIAudioBoundaryThread(
            self.audio_thread,
            initial_selection=initial_boundary_selection,
            parent=self,
        )
        self.audio_thread.attach_hardware_boundary(
            self.audio_boundary_thread
        )
        self.audio_boundary_thread.snapshot_ready.connect(
            self.handle_audio_probe_snapshot
        )
        self.audio_boundary_thread.probe_error.connect(
            self.handle_audio_probe_error
        )
        self.audio_boundary_thread.device_status.connect(
            self.handle_device_status
        )
        self.audio_boundary_thread.start(
            QtCore.QThread.Priority.NormalPriority
        )
        self.app_state.mark_waiting_for_audio(
            "isolated audio boundary started"
        )

        self.mic_combo.currentIndexChanged.connect(
            self.on_device_changed
        )
        self.refresh_button.clicked.connect(
            self.refresh_audio_devices
        )

        self.lowcut_slider.valueChanged.connect(
            self.on_param_changed
        )
        self.highcut_slider.valueChanged.connect(
            self.on_param_changed
        )
        self.input_volume_slider.valueChanged.connect(
            self.on_input_volume_changed
        )
        self.sens_slider.valueChanged.connect(
            self.on_param_changed
        )

        self.update_parameter_labels()
        self.apply_params_now()

        # Script 57.3: do not start a cosmetic 60-second clock merely because
        # the application launched. The worker starts it only after the first
        # complete microphone block proves that capture is actually alive.
        self.boot_screen.wait_for_microphone(
            "Opening microphone and waiting for live audio frames..."
        )

        # Start analysis first so the very first locked audio block has a
        # consumer ready before recording begins.
        # Script 49 explicit worker scheduling. Keep GUI painting/events on the
        # Qt main thread while prioritizing realtime capture/analysis over
        # background post-processing and transcription.
        self.postprocess_thread.start(
            QtCore.QThread.Priority.NormalPriority
        )
        self.transcription_thread.start(
            QtCore.QThread.Priority.LowPriority
        )
        self.isolated_analysis_thread.start(
            QtCore.QThread.Priority.HighPriority
        )
        self.audio_thread.start(
            QtCore.QThread.Priority.HighPriority
        )

    # --------------------------------------------------------------------------
    # Recording library / playback
    # --------------------------------------------------------------------------

        # Re-measure after every tab/control has been constructed. This captures
        # the true minimum layout requirement and lets BCIAdaptiveFrame keep the
        # entire application visible as one uniformly scaled frame.
        QtCore.QTimer.singleShot(
            0,
            self.adaptive_frame.refresh_design_canvas,
        )

    def _build_transcripts_tab(self):
        """Build the dedicated local-transcription workspace."""

        root = QtWidgets.QVBoxLayout(self.transcripts_tab)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # --------------------------------------------------------------
        # Header / backend state
        # --------------------------------------------------------------

        header_row = QtWidgets.QHBoxLayout()

        title = QtWidgets.QLabel(
            "LOCAL TRANSCRIPTION WORKSPACE"
        )
        title.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 18px;"
            "font-weight: bold;"
            "color: #71c7ff;"
            "letter-spacing: 1px;"
        )
        header_row.addWidget(title)

        header_row.addStretch()

        self.transcripts_backend_label = QtWidgets.QLabel()
        self.transcripts_backend_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "color: #9fb2bd;"
            "background: #090d12;"
            "border: 1px solid #30363d;"
            "border-radius: 5px;"
            "padding: 6px 9px;"
        )
        header_row.addWidget(
            self.transcripts_backend_label
        )

        root.addLayout(header_row)

        model_path = Path(
            FASTER_WHISPER_MODEL
        ).expanduser()

        if model_path.exists():
            model_state = "MODEL READY"
            model_color = "#58d68d"
        else:
            model_state = "MODEL MISSING"
            model_color = "#ff7b72"

        self.transcripts_backend_label.setText(
            "FASTER-WHISPER / CPU INT8  •  "
            + model_state
        )
        self.transcripts_backend_label.setStyleSheet(
            self.transcripts_backend_label.styleSheet()
            + f"color: {model_color};"
        )
        self.transcripts_backend_label.setToolTip(
            str(model_path)
        )

        description = QtWidgets.QLabel(
            "Browse retained recordings, inspect existing transcript "
            "sidecars, and submit audio to the existing BCIWhisper "
            "local transcription worker."
        )
        description.setWordWrap(True)
        description.setStyleSheet(
            "font-size: 12px;"
            "color: #9aa7b2;"
        )
        root.addWidget(description)

        # --------------------------------------------------------------
        # Library
        # --------------------------------------------------------------

        self.transcripts_table = QtWidgets.QTableWidget(
            0,
            4,
        )
        self.transcripts_table.setHorizontalHeaderLabels(
            [
                "RECORDED",
                "TYPE",
                "TRANSCRIPT",
                "SOURCE",
            ]
        )
        self.transcripts_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.transcripts_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.transcripts_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.transcripts_table.setAlternatingRowColors(True)

        header = self.transcripts_table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            1,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            2,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QtWidgets.QHeaderView.ResizeMode.Stretch,
        )

        self.transcripts_table.currentCellChanged.connect(
            lambda *_: self.update_transcript_selection()
        )

        root.addWidget(
            self.transcripts_table,
            2,
        )

        # --------------------------------------------------------------
        # Controls
        # --------------------------------------------------------------

        controls = QtWidgets.QHBoxLayout()

        self.transcripts_transcribe_button = QtWidgets.QPushButton(
            "TRANSCRIBE SELECTED"
        )
        self.transcripts_refresh_button = QtWidgets.QPushButton(
            "REFRESH"
        )
        self.transcripts_open_button = QtWidgets.QPushButton(
            "OPEN TRANSCRIPT"
        )
        self.transcripts_folder_button = QtWidgets.QPushButton(
            "OPEN FOLDER"
        )

        self.transcripts_transcribe_button.clicked.connect(
            self.transcribe_selected_transcript_audio
        )
        self.transcripts_refresh_button.clicked.connect(
            self.refresh_transcripts
        )
        self.transcripts_open_button.clicked.connect(
            self.open_selected_transcript
        )
        self.transcripts_folder_button.clicked.connect(
            self.open_transcripts_folder
        )

        controls.addWidget(
            self.transcripts_transcribe_button
        )
        controls.addWidget(
            self.transcripts_refresh_button
        )
        controls.addWidget(
            self.transcripts_open_button
        )
        controls.addWidget(
            self.transcripts_folder_button
        )
        controls.addStretch()

        root.addLayout(controls)

        # --------------------------------------------------------------
        # State + transcript viewer
        # --------------------------------------------------------------

        self.transcripts_status_label = QtWidgets.QLabel(
            "TRANSCRIPTION: READY"
        )
        self.transcripts_status_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "font-weight: bold;"
            "color: #71c7ff;"
            "padding: 4px;"
        )
        root.addWidget(
            self.transcripts_status_label
        )

        self.transcripts_view = QtWidgets.QPlainTextEdit()
        self.transcripts_view.setReadOnly(True)
        self.transcripts_view.setPlaceholderText(
            "Select a recording to view its transcript."
        )
        self.transcripts_view.setStyleSheet(
            "QPlainTextEdit {"
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 13px;"
            "color: #dce8ee;"
            "background: #090d12;"
            "border: 1px solid #30363d;"
            "border-radius: 5px;"
            "padding: 8px;"
            "}"
        )

        root.addWidget(
            self.transcripts_view,
            3,
        )

        QtCore.QTimer.singleShot(
            0,
            self.refresh_transcripts,
        )


    def selected_transcript_audio_path(self):
        row = self.transcripts_table.currentRow()

        if row < 0:
            return None

        item = self.transcripts_table.item(
            row,
            3,
        )

        if item is None:
            return None

        stored = item.data(
            QtCore.Qt.ItemDataRole.UserRole
        )

        if not stored:
            return None

        path = Path(
            str(stored)
        )

        if not path.exists():
            return None

        return path



    def refresh_transcripts(self):
        """
        Refresh TRANSCRIPTS using one logical row per capture.

        The isolated WAV is preferred for manual transcription.
        RAW remains preserved as the fallback source.
        """

        log_path = Path(LOG_DIR)
        log_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        previous = None

        if hasattr(
            self,
            "transcripts_table",
        ):
            previous = self.selected_transcript_audio_path()

        def logical_key(audio_path):
            stem = audio_path.stem

            if stem.endswith("_raw"):
                return stem[:-4]

            if stem.endswith("_isolated"):
                return stem[:-9]

            return stem

        groups = {}

        for audio_path in log_path.glob("*.wav"):
            key = logical_key(audio_path)

            entry = groups.setdefault(
                key,
                {
                    "raw": None,
                    "isolated": None,
                    "other": [],
                },
            )

            if audio_path.stem.endswith("_raw"):
                entry["raw"] = audio_path

            elif audio_path.stem.endswith("_isolated"):
                entry["isolated"] = audio_path

            else:
                entry["other"].append(audio_path)

        logical_rows = []

        for key, entry in groups.items():
            preferred = (
                entry["isolated"]
                if (
                    entry["isolated"] is not None
                    and entry["isolated"].exists()
                )
                else entry["raw"]
                if (
                    entry["raw"] is not None
                    and entry["raw"].exists()
                )
                else (
                    entry["other"][0]
                    if entry["other"]
                    else None
                )
            )

            if preferred is None:
                continue

            try:
                modified = max(
                    p.stat().st_mtime
                    for p in (
                        entry["raw"],
                        entry["isolated"],
                        *entry["other"],
                    )
                    if p is not None and p.exists()
                )
            except Exception:
                modified = preferred.stat().st_mtime

            logical_rows.append(
                {
                    "key": key,
                    "preferred": preferred,
                    "raw": entry["raw"],
                    "isolated": entry["isolated"],
                    "modified": modified,
                }
            )

        logical_rows.sort(
            key=lambda item: item["modified"],
            reverse=True,
        )

        self.transcripts_table.setRowCount(
            len(logical_rows)
        )

        restore_row = -1
        ready_count = 0

        previous_key = (
            logical_key(previous)
            if previous is not None
            else None
        )

        for row, logical in enumerate(logical_rows):
            preferred = logical["preferred"]

            transcript_path = self._transcript_for_audio(
                preferred
            )

            if transcript_path is not None:
                ready_count += 1

            if (
                logical["raw"] is not None
                and logical["isolated"] is not None
            ):
                kind = "RAW + ISOLATED"

            elif logical["isolated"] is not None:
                kind = "ISOLATED"

            elif logical["raw"] is not None:
                kind = "RAW"

            else:
                kind = "WAV"

            recorded = datetime.fromtimestamp(
                logical["modified"]
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            values = [
                recorded,
                kind,
                (
                    "READY"
                    if transcript_path is not None
                    else "—"
                ),
                logical["key"],
            ]

            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(
                    str(value)
                )

                if column == 3:
                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole,
                        str(preferred.resolve()),
                    )

                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole + 1,
                        (
                            str(logical["raw"].resolve())
                            if logical["raw"] is not None
                            else ""
                        ),
                    )

                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole + 2,
                        (
                            str(logical["isolated"].resolve())
                            if logical["isolated"] is not None
                            else ""
                        ),
                    )

                if (
                    column == 2
                    and transcript_path is not None
                ):
                    item.setForeground(
                        QtGui.QColor("#58d68d")
                    )

                self.transcripts_table.setItem(
                    row,
                    column,
                    item,
                )

            if (
                previous_key is not None
                and logical["key"] == previous_key
            ):
                restore_row = row

        self.transcripts_status_label.setText(
            "TRANSCRIPTION LIBRARY: "
            f"{ready_count}/{len(logical_rows)} READY"
        )

        if restore_row >= 0:
            self.transcripts_table.selectRow(
                restore_row
            )

        elif logical_rows:
            self.transcripts_table.selectRow(0)

        else:
            self.transcripts_view.setPlainText(
                "No retained recordings were found."
            )

    def update_transcript_selection(self):
        audio_path = self.selected_transcript_audio_path()

        if audio_path is None:
            self.transcripts_view.clear()
            return

        transcript_path = self._transcript_for_audio(
            audio_path
        )

        if transcript_path is None:
            self.transcripts_view.setPlainText(
                "NO TRANSCRIPT\n\n"
                f"Source: {audio_path.name}\n\n"
                "Click TRANSCRIBE SELECTED to queue this recording."
            )
            return

        try:
            text = transcript_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            text = (
                "TRANSCRIPT READ ERROR\n\n"
                + str(exc)
            )

        self.transcripts_view.setPlainText(
            text
        )


    def transcribe_selected_transcript_audio(self):
        audio_path = self.selected_transcript_audio_path()

        if audio_path is None:
            self.transcripts_status_label.setText(
                "TRANSCRIPTION: SELECT A RECORDING"
            )
            return

        preferred = audio_path

        if audio_path.stem.endswith("_raw"):
            isolated = audio_path.with_name(
                audio_path.stem[:-4]
                + "_isolated.wav"
            )

            if isolated.exists():
                preferred = isolated

        self.transcripts_status_label.setText(
            f"TRANSCRIPTION QUEUED: {preferred.name}"
        )
        self.transcripts_view.setPlainText(
            "Queued for local transcription:\n\n"
            + preferred.name
        )

        self.transcription_thread.submit(
            preferred,
            reason="transcripts-tab",
        )


    def open_selected_transcript(self):
        audio_path = self.selected_transcript_audio_path()

        if audio_path is None:
            self.transcripts_status_label.setText(
                "TRANSCRIPTION: SELECT A RECORDING"
            )
            return

        transcript_path = self._transcript_for_audio(
            audio_path
        )

        if transcript_path is None:
            self.transcripts_status_label.setText(
                "TRANSCRIPTION: NO TRANSCRIPT FOR SELECTION"
            )
            return

        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(
                str(transcript_path.resolve())
            )
        )


    def open_transcripts_folder(self):
        path = Path(LOG_DIR).resolve()
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(
                str(path)
            )
        )


    @guarded_slot("transcripts tab status")
    def handle_transcripts_tab_status(self, message):
        if not hasattr(
            self,
            "transcripts_status_label",
        ):
            return

        message = str(message)

        if (
            message.startswith("TRANSCRIBING")
            or message.startswith("Loading")
        ):
            self.transcripts_status_label.setText(
                message
            )


    @guarded_slot("transcripts tab result")
    def handle_transcripts_tab_result(self, result):
        if not hasattr(
            self,
            "transcripts_status_label",
        ):
            return

        error = result.get(
            "error"
        )

        if error:
            self.transcripts_status_label.setText(
                "TRANSCRIPTION FAILED"
            )
            self.transcripts_view.setPlainText(
                "TRANSCRIPTION UNAVAILABLE\n\n"
                + str(error)
            )
            return

        backend = str(
            result.get(
                "backend",
                "unknown",
            )
        )
        language = str(
            result.get(
                "language",
                TRANSCRIPTION_LANGUAGE,
            )
        )

        self.transcripts_status_label.setText(
            "TRANSCRIPTION COMPLETE  •  "
            f"{backend}  •  {language}"
        )

        self.refresh_transcripts()
        self.update_transcript_selection()


    def _build_mastering_tab(self):
        self.mastering_source_path = None
        self.mastering_preview_path = None
        self.mastering_operations = []
        self.mastering_redo = []
        self.mastering_revision = 0
        self.mastering_render_thread = None
        self.mastering_playback_thread = None
        self.mastering_preview_pending = False
        self.mastering_save_pending = False
        self.mastering_compare_original = False

        root = QtWidgets.QVBoxLayout(self.mastering_tab)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        header = QtWidgets.QHBoxLayout()

        title = QtWidgets.QLabel("MASTERING WORKSPACE")
        title.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 20px;"
            "font-weight: 800;"
            "color: #dce8ee;"
            "letter-spacing: 1.0px;"
        )
        header.addWidget(title)

        header.addStretch()

        self.mastering_source_combo = QtWidgets.QComboBox()
        self.mastering_source_combo.setMinimumWidth(420)
        header.addWidget(self.mastering_source_combo)

        self.mastering_load_button = QtWidgets.QPushButton(
            "Load Recording"
        )
        header.addWidget(self.mastering_load_button)

        self.mastering_use_selected_button = QtWidgets.QPushButton(
            "Use Selected Recording"
        )
        header.addWidget(self.mastering_use_selected_button)

        root.addLayout(header)

        helper = QtWidgets.QLabel(
            "Drag across the waveform to select an area. "
            "Effects use the selected area when one is highlighted; "
            "otherwise they affect the whole recording."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet(
            "color: #82939e;"
            "font-size: 13px;"
            "padding: 2px 4px;"
        )
        root.addWidget(helper)

        self.mastering_waveform = MasterWaveformWidget()
        root.addWidget(self.mastering_waveform)

        self.mastering_selection_label = QtWidgets.QLabel(
            "Selection: none — whole recording"
        )
        self.mastering_selection_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "color: #94a5ae;"
        )
        root.addWidget(self.mastering_selection_label)

        transport = QtWidgets.QHBoxLayout()

        self.master_play_original_button = QtWidgets.QPushButton(
            "▶ Original"
        )
        self.master_play_edited_button = QtWidgets.QPushButton(
            "▶ Edited"
        )
        self.master_compare_button = QtWidgets.QPushButton(
            "Compare A/B"
        )
        self.master_stop_button = QtWidgets.QPushButton(
            "■ Stop"
        )
        self.master_clear_selection_button = QtWidgets.QPushButton(
            "Clear Selection"
        )

        for button in (
            self.master_play_original_button,
            self.master_play_edited_button,
            self.master_compare_button,
            self.master_stop_button,
            self.master_clear_selection_button,
        ):
            transport.addWidget(button)

        transport.addStretch()
        root.addLayout(transport)

        body = QtWidgets.QHBoxLayout()

        edit_box = QtWidgets.QGroupBox("EDIT")
        edit_layout = QtWidgets.QGridLayout(edit_box)

        self.master_cut_button = QtWidgets.QPushButton("Cut Selected")
        self.master_keep_button = QtWidgets.QPushButton("Keep Selected")
        self.master_trim_button = QtWidgets.QPushButton("Trim Quiet Ends")
        self.master_fade_in_button = QtWidgets.QPushButton("Fade In")
        self.master_fade_out_button = QtWidgets.QPushButton("Fade Out")
        self.master_undo_button = QtWidgets.QPushButton("↶ Undo")
        self.master_redo_button = QtWidgets.QPushButton("↷ Redo")

        edit_layout.addWidget(self.master_cut_button, 0, 0)
        edit_layout.addWidget(self.master_keep_button, 0, 1)
        edit_layout.addWidget(self.master_trim_button, 1, 0, 1, 2)
        edit_layout.addWidget(self.master_fade_in_button, 2, 0)
        edit_layout.addWidget(self.master_fade_out_button, 2, 1)
        edit_layout.addWidget(self.master_undo_button, 3, 0)
        edit_layout.addWidget(self.master_redo_button, 3, 1)

        body.addWidget(edit_box, 1)

        improve_box = QtWidgets.QGroupBox("IMPROVE")
        improve_layout = QtWidgets.QGridLayout(improve_box)

        self.master_strength_combo = QtWidgets.QComboBox()
        self.master_strength_combo.addItems(
            ["Light", "Normal", "Strong"]
        )
        self.master_strength_combo.setCurrentText("Normal")

        improve_layout.addWidget(
            QtWidgets.QLabel("Strength"),
            0,
            0,
        )
        improve_layout.addWidget(
            self.master_strength_combo,
            0,
            1,
        )

        self.master_auto_button = QtWidgets.QPushButton("✨ Auto Fix")
        self.master_louder_button = QtWidgets.QPushButton("Make Louder")
        self.master_noise_button = QtWidgets.QPushButton(
            "Reduce Background Noise"
        )
        self.master_voice_button = QtWidgets.QPushButton(
            "Make Voice Clearer"
        )
        self.master_hum_button = QtWidgets.QPushButton(
            "Remove Buzz / Hum"
        )
        self.master_even_button = QtWidgets.QPushButton(
            "Even Out Volume"
        )

        self.master_auto_button.setStyleSheet(
            "font-size: 15px;"
            "font-weight: 800;"
            "padding: 9px;"
            "border: 1px solid #357684;"
            "border-radius: 5px;"
            "background: #10242c;"
            "color: #dce8ee;"
        )

        improve_layout.addWidget(self.master_auto_button, 1, 0, 1, 2)
        improve_layout.addWidget(self.master_louder_button, 2, 0)
        improve_layout.addWidget(self.master_noise_button, 2, 1)
        improve_layout.addWidget(self.master_voice_button, 3, 0)
        improve_layout.addWidget(self.master_hum_button, 3, 1)
        improve_layout.addWidget(self.master_even_button, 4, 0, 1, 2)

        body.addWidget(improve_box, 2)

        finish_box = QtWidgets.QGroupBox("FINISH")
        finish_layout = QtWidgets.QVBoxLayout(finish_box)

        self.master_auto_preview_check = QtWidgets.QCheckBox(
            "Preview changes automatically"
        )
        self.master_auto_preview_check.setChecked(True)
        finish_layout.addWidget(self.master_auto_preview_check)

        self.master_preview_button = QtWidgets.QPushButton(
            "Preview Changes"
        )
        self.master_save_button = QtWidgets.QPushButton(
            "SAVE MASTER"
        )

        self.master_save_button.setStyleSheet(
            "font-size: 15px;"
            "font-weight: 800;"
            "padding: 10px;"
            "border: 1px solid #7e2730;"
            "border-radius: 5px;"
            "background: #1a1115;"
            "color: #e4eaee;"
        )

        finish_layout.addWidget(self.master_preview_button)
        finish_layout.addWidget(self.master_save_button)
        finish_layout.addStretch()

        body.addWidget(finish_box, 1)
        root.addLayout(body)

        self.mastering_status_label = QtWidgets.QLabel(
            "Load a recording to begin."
        )
        self.mastering_status_label.setWordWrap(True)
        self.mastering_status_label.setStyleSheet(
            "font-size: 13px;"
            "font-weight: 650;"
            "color: #8fa0aa;"
            "padding: 7px;"
            "background: #090e13;"
            "border: 1px solid #24343d;"
            "border-radius: 5px;"
        )
        root.addWidget(self.mastering_status_label)

        self.mastering_operations_view = QtWidgets.QPlainTextEdit()
        self.mastering_operations_view.setReadOnly(True)
        self.mastering_operations_view.setMaximumHeight(118)
        self.mastering_operations_view.setPlaceholderText(
            "Edits and processing steps appear here."
        )
        self.mastering_operations_view.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "color: #a8b7c0;"
            "background: #070b0f;"
            "border: 1px solid #24343d;"
            "border-radius: 5px;"
        )
        root.addWidget(self.mastering_operations_view)

        # Keep wording simple; technical DSP details stay under the hood.
        edit_box.setStyleSheet(
            "QGroupBox {"
            "border: 1px solid #294a55;"
            "border-radius: 7px;"
            "margin-top: 9px;"
            "padding-top: 8px;"
            "color: #a9bac3;"
            "font-weight: 700;"
            "}"
        )
        improve_box.setStyleSheet(edit_box.styleSheet())
        finish_box.setStyleSheet(edit_box.styleSheet())

        self.mastering_waveform.selectionChanged.connect(
            self._master_selection_changed
        )
        self.mastering_load_button.clicked.connect(
            self._master_load_combo_source
        )
        self.mastering_use_selected_button.clicked.connect(
            self._master_load_recordings_selection
        )
        self.master_clear_selection_button.clicked.connect(
            self.mastering_waveform.clear_selection
        )

        self.master_cut_button.clicked.connect(
            lambda: self._master_add_operation("cut", require_selection=True)
        )
        self.master_keep_button.clicked.connect(
            lambda: self._master_add_operation("keep", require_selection=True)
        )
        self.master_trim_button.clicked.connect(
            lambda: self._master_add_operation("trim")
        )
        self.master_fade_in_button.clicked.connect(
            lambda: self._master_add_operation("fade_in")
        )
        self.master_fade_out_button.clicked.connect(
            lambda: self._master_add_operation("fade_out")
        )
        self.master_undo_button.clicked.connect(self._master_undo)
        self.master_redo_button.clicked.connect(self._master_redo)

        self.master_auto_button.clicked.connect(
            lambda: self._master_add_operation("auto")
        )
        self.master_louder_button.clicked.connect(
            lambda: self._master_add_operation("louder")
        )
        self.master_noise_button.clicked.connect(
            lambda: self._master_add_operation("noise")
        )
        self.master_voice_button.clicked.connect(
            lambda: self._master_add_operation("voice")
        )
        self.master_hum_button.clicked.connect(
            lambda: self._master_add_operation("hum")
        )
        self.master_even_button.clicked.connect(
            lambda: self._master_add_operation("even")
        )

        self.master_preview_button.clicked.connect(
            lambda: self._master_start_render("preview")
        )
        self.master_save_button.clicked.connect(
            lambda: self._master_start_render("save")
        )

        self.master_play_original_button.clicked.connect(
            lambda: self._master_play("original")
        )
        self.master_play_edited_button.clicked.connect(
            lambda: self._master_play("edited")
        )
        self.master_compare_button.clicked.connect(
            self._master_compare
        )
        self.master_stop_button.clicked.connect(
            lambda: self.stop_mastering_playback(wait=False)
        )

        self.refresh_mastering_sources()
        self._master_refresh_controls()


    def refresh_mastering_sources(self):
        if not hasattr(self, "mastering_source_combo"):
            return

        current = self.mastering_source_combo.currentData()
        files = sorted(
            Path(LOG_DIR).glob("*.wav"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        self.mastering_source_combo.blockSignals(True)
        self.mastering_source_combo.clear()

        current_index = -1
        for index, path in enumerate(files):
            meta = self._recording_metadata(path)
            self.mastering_source_combo.addItem(
                f"[{meta['version']}] {path.name}",
                str(path),
            )
            if current and str(path) == str(current):
                current_index = index

        if current_index >= 0:
            self.mastering_source_combo.setCurrentIndex(current_index)

        self.mastering_source_combo.blockSignals(False)


    def _master_load_combo_source(self):
        value = self.mastering_source_combo.currentData()
        if not value:
            self.mastering_status_label.setText(
                "Choose a recording first."
            )
            return
        self._master_load_source(Path(str(value)))


    def _master_load_recordings_selection(self):
        path = self.selected_recording_path()
        if path is None:
            self.mastering_status_label.setText(
                "Select one recording in the Recordings tab first."
            )
            return
        self._master_load_source(path)
        self.main_tabs.setCurrentWidget(self.mastering_tab)


    def _master_load_source(self, path):
        path = Path(path)
        if not path.exists():
            self.mastering_status_label.setText(
                "That recording no longer exists."
            )
            return

        self.stop_mastering_playback(wait=True)
        self.mastering_source_path = path
        self.mastering_preview_path = None
        self.mastering_operations = []
        self.mastering_redo = []
        self.mastering_revision += 1

        try:
            self.mastering_waveform.set_audio_file(path)
        except Exception as exc:
            self.mastering_status_label.setText(
                f"Unable to load waveform: {exc}"
            )
            return

        self.mastering_status_label.setText(
            f"Loaded {path.name}. Drag across the waveform to select an area, "
            "or leave it unselected to edit the whole recording."
        )
        self._master_update_operations_view()
        self._master_refresh_controls()


    def _master_selection_changed(self, start, end):
        if end > start:
            self.mastering_selection_label.setText(
                f"Selection: {self._format_seconds(start)} – "
                f"{self._format_seconds(end)} "
                f"({end - start:.1f} seconds)"
            )
        else:
            self.mastering_selection_label.setText(
                "Selection: none — whole recording"
            )


    def _master_current_scope(self):
        selection = self.mastering_waveform.selection()
        if selection is None:
            return None, None
        return float(selection[0]), float(selection[1])


    def _master_add_operation(self, kind, require_selection=False):
        if self.mastering_source_path is None:
            self.mastering_status_label.setText(
                "Load a recording first."
            )
            return

        start, end = self._master_current_scope()
        if require_selection and (start is None or end is None):
            self.mastering_status_label.setText(
                "Drag across the waveform to select the part you want to edit."
            )
            return

        operation = {
            "kind": str(kind),
            "strength": self.master_strength_combo.currentText(),
            "start": start,
            "end": end,
        }

        # Auto Fix intentionally works on the whole recording.
        if kind in ("auto", "trim"):
            operation["start"] = None
            operation["end"] = None

        self.mastering_operations.append(operation)
        self.mastering_redo.clear()
        self.mastering_revision += 1

        self._master_update_operations_view()
        self._master_refresh_controls()

        if self.master_auto_preview_check.isChecked():
            self._master_start_render("preview")


    def _master_operation_text(self, operation):
        names = {
            "cut": "Cut selected audio",
            "keep": "Keep selected audio",
            "trim": "Trim quiet ends",
            "fade_in": "Fade in",
            "fade_out": "Fade out",
            "auto": "Auto Fix",
            "louder": "Make louder",
            "noise": "Reduce background noise",
            "voice": "Make voice clearer",
            "hum": "Remove buzz / hum",
            "even": "Even out volume",
        }

        label = names.get(
            operation.get("kind"),
            str(operation.get("kind")),
        )

        if operation.get("kind") in (
            "louder",
            "noise",
            "voice",
            "even",
        ):
            label += f" ({operation.get('strength', 'Normal')})"

        if (
            operation.get("start") is not None
            and operation.get("end") is not None
        ):
            label += (
                f"  [{self._format_seconds(operation['start'])} – "
                f"{self._format_seconds(operation['end'])}]"
            )

        return label


    def _master_update_operations_view(self):
        if not self.mastering_operations:
            self.mastering_operations_view.setPlainText(
                "No edits yet. The original recording is unchanged."
            )
            return

        lines = [
            f"{index + 1}. {self._master_operation_text(operation)}"
            for index, operation in enumerate(self.mastering_operations)
        ]
        self.mastering_operations_view.setPlainText(
            "\n".join(lines)
        )


    def _master_undo(self):
        if not self.mastering_operations:
            return
        self.mastering_redo.append(
            self.mastering_operations.pop()
        )
        self.mastering_revision += 1
        self._master_update_operations_view()
        self._master_refresh_controls()
        if self.master_auto_preview_check.isChecked():
            self._master_start_render("preview")


    def _master_redo(self):
        if not self.mastering_redo:
            return
        self.mastering_operations.append(
            self.mastering_redo.pop()
        )
        self.mastering_revision += 1
        self._master_update_operations_view()
        self._master_refresh_controls()
        if self.master_auto_preview_check.isChecked():
            self._master_start_render("preview")


    def _master_refresh_controls(self):
        loaded = self.mastering_source_path is not None
        has_ops = bool(self.mastering_operations)

        self.master_undo_button.setEnabled(has_ops)
        self.master_redo_button.setEnabled(bool(self.mastering_redo))
        self.master_preview_button.setEnabled(loaded)
        self.master_save_button.setEnabled(loaded and has_ops)
        self.master_play_original_button.setEnabled(loaded)
        self.master_play_edited_button.setEnabled(
            self.mastering_preview_path is not None
            and Path(self.mastering_preview_path).exists()
        )


    def _master_preview_output(self):
        MASTER_PREVIEW_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )
        return MASTER_PREVIEW_DIR / MASTER_DEFAULT_PREVIEW_NAME


    def _master_output_path(self):
        source = Path(self.mastering_source_path)
        stem = source.stem

        for suffix in (
            "_raw",
            "_isolated",
            "_master",
        ):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break

        candidate = source.with_name(
            stem + "_master.wav"
        )

        if candidate.resolve() == source.resolve() or candidate.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            candidate = source.with_name(
                stem + f"_master_{stamp}.wav"
            )

        return candidate


    def _master_start_render(self, mode):
        if self.mastering_source_path is None:
            self.mastering_status_label.setText(
                "Load a recording first."
            )
            return

        if mode == "save" and not self.mastering_operations:
            self.mastering_status_label.setText(
                "Add at least one edit or improvement before saving a master."
            )
            return

        if (
            self.mastering_render_thread is not None
            and self.mastering_render_thread.isRunning()
        ):
            if mode == "save":
                self.mastering_save_pending = True
            else:
                self.mastering_preview_pending = True
            self.mastering_status_label.setText(
                "Processing is already running. Your latest changes are queued."
            )
            return

        if mode == "save":
            output_path = self._master_output_path()
        else:
            output_path = self._master_preview_output()

        self.mastering_status_label.setText(
            "Processing audio..."
        )

        thread = MasterRenderThread(
            self.mastering_source_path,
            self.mastering_operations,
            output_path,
            mode,
            self.mastering_revision,
            self,
        )
        thread.status_ready.connect(
            self.mastering_status_label.setText
        )
        thread.result_ready.connect(
            self._master_render_finished
        )
        self.mastering_render_thread = thread
        thread.start()


    def _master_render_finished(self, result):
        mode = result.get("mode", "preview")
        revision = int(result.get("revision", -1))

        if not result.get("ok"):
            self.mastering_status_label.setText(
                "Processing failed: "
                + str(result.get("error", "unknown error"))
            )
        elif revision != self.mastering_revision and mode == "preview":
            self.mastering_status_label.setText(
                "A newer edit is waiting to be previewed."
            )
            self.mastering_preview_pending = True
        else:
            output_path = Path(result["output_path"])
            final_metrics = result.get("final_metrics", {})

            if mode == "preview":
                self.mastering_preview_path = output_path
                try:
                    self.mastering_waveform.set_audio_file(
                        output_path
                    )
                except Exception as exc:
                    report_exception(
                        "refresh mastering waveform",
                        exc,
                    )

                self.mastering_status_label.setText(
                    "Preview ready. "
                    f"Peak {float(final_metrics.get('peak_dbfs', -120.0)):.1f} dBFS, "
                    f"average {float(final_metrics.get('rms_dbfs', -120.0)):.1f} dBFS. "
                    "Use Original / Edited or Compare A/B to listen."
                )
            else:
                self.mastering_status_label.setText(
                    f"Master saved: {output_path.name}"
                )

                mastering_metadata = output_path.with_suffix(
                    ".mastering.json"
                )
                mastering_metadata.write_text(
                    json.dumps(
                        {
                            "project_version": BCI_PROJECT_VERSION,
                            "script_tally": BCI_SCRIPT_TALLY,
                            "build": BCI_BUILD,
                            "created_at": datetime.utcnow().isoformat() + "Z",
                            "source": str(self.mastering_source_path),
                            "master": str(output_path),
                            "operations": self.mastering_operations,
                            "metrics": final_metrics,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                TELEMETRY_DAEMON.log_event(
                    "MANUAL_MASTER_SAVED",
                    json.dumps(
                        {
                            "project_version": BCI_PROJECT_VERSION,
                            "script_tally": BCI_SCRIPT_TALLY,
                            "build": BCI_BUILD,
                            "source": str(self.mastering_source_path),
                            "master": str(output_path),
                            "operations": self.mastering_operations,
                            "metrics": final_metrics,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )

                self.refresh_recordings()

        self._master_refresh_controls()

        if self.mastering_save_pending:
            self.mastering_save_pending = False
            self._master_start_render("save")
        elif self.mastering_preview_pending:
            self.mastering_preview_pending = False
            self._master_start_render("preview")


    def _master_play(self, version):
        self.stop_playback(wait=True)
        self.stop_mastering_playback(wait=True)

        if version == "original":
            path = self.mastering_source_path
            label = "ORIGINAL"
        else:
            path = self.mastering_preview_path
            label = "EDITED"

        if path is None or not Path(path).exists():
            self.mastering_status_label.setText(
                "Preview the edited recording first."
            )
            return

        self.mastering_status_label.setText(
            f"Playing {label.lower()}: {Path(path).name}"
        )

        self.mastering_playback_thread = AudioPlaybackThread(
            str(path),
            self,
        )
        self.mastering_playback_thread.playback_status.connect(
            lambda status: self.mastering_status_label.setText(
                f"{label}: {status}"
            )
        )
        self.mastering_playback_thread.playback_finished.connect(
            self._master_playback_finished
        )
        self.mastering_playback_thread.start()


    def _master_playback_finished(self):
        self.mastering_status_label.setText(
            "Playback finished."
        )


    def stop_mastering_playback(self, wait=False):
        thread = self.mastering_playback_thread
        if thread is None:
            return

        if thread.isRunning():
            thread.stop_playback()
            if wait:
                thread.wait(1500)


    def _master_compare(self):
        if self.mastering_preview_path is None:
            self.mastering_status_label.setText(
                "Preview your changes before comparing."
            )
            return

        self.mastering_compare_original = (
            not self.mastering_compare_original
        )
        self._master_play(
            "original"
            if self.mastering_compare_original
            else "edited"
        )

    def _build_recordings_tab(self):
        layout = QtWidgets.QVBoxLayout(
            self.recordings_tab
        )
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header_row = QtWidgets.QHBoxLayout()

        library_title = QtWidgets.QLabel(
            "BCI RECORDING LIBRARY"
        )
        library_title.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 20px;"
            "font-weight: bold;"
            "color: #71c7ff;"
            "letter-spacing: 0.8px;"
        )
        header_row.addWidget(library_title)

        header_row.addStretch()

        self.recording_count_label = QtWidgets.QLabel(
            "0 recordings"
        )
        self.recording_count_label.setStyleSheet(
            "font-size: 14px;"
            "color: #b1bac4;"
        )
        header_row.addWidget(
            self.recording_count_label
        )

        self.recordings_version_badge = QtWidgets.QLabel(
            f"{BCI_PROJECT_VERSION}  •  #{BCI_SCRIPT_TALLY}"
        )
        self.recordings_version_badge.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 11px;"
            "font-weight: bold;"
            "color: #8d99a5;"
            "border: 1px solid #30363d;"
            "border-radius: 4px;"
            "padding: 4px 7px;"
        )
        header_row.addWidget(
            self.recordings_version_badge
        )

        self.select_all_recordings_button = QtWidgets.QPushButton(
            "Select All"
        )
        self.select_all_recordings_button.setMinimumHeight(34)
        self.select_all_recordings_button.setStyleSheet(
            "font-size: 13px;"
            "font-weight: bold;"
            "padding: 5px 11px;"
        )
        self.select_all_recordings_button.clicked.connect(
            self.select_all_recordings
        )
        header_row.addWidget(
            self.select_all_recordings_button
        )

        self.recordings_refresh_button = QtWidgets.QPushButton(
            "Refresh"
        )
        self.recordings_refresh_button.setMinimumHeight(34)
        self.recordings_refresh_button.clicked.connect(
            self.refresh_recordings
        )
        header_row.addWidget(
            self.recordings_refresh_button
        )

        layout.addLayout(header_row)

        self.recordings_table = QtWidgets.QTableWidget(
            0,
            6,
        )
        self.recordings_table.setHorizontalHeaderLabels(
            [
                "Recorded",
                "Version",
                "Duration",
                "Size",
                "Transcript",
                "File",
            ]
        )
        self.recordings_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.recordings_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.recordings_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.recordings_table.setAlternatingRowColors(True)
        self.recordings_table.verticalHeader().setVisible(False)
        self.recordings_table.setStyleSheet(
            "QTableWidget {"
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "gridline-color: #30363d;"
            "alternate-background-color: #1b2028;"
            "}"
            "QHeaderView::section {"
            "font-family: 'DejaVu Sans';"
            "font-size: 14px;"
            "font-weight: bold;"
            "letter-spacing: 0.4px;"
            "padding: 7px;"
            "background: #21262d;"
            "color: #e6edf3;"
            "border: 1px solid #30363d;"
            "}"
        )

        header = self.recordings_table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            1,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            2,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            4,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            5,
            QtWidgets.QHeaderView.ResizeMode.Stretch,
        )

        self.recordings_table.itemDoubleClicked.connect(
            self.play_recording_item
        )
        self.recordings_table.itemSelectionChanged.connect(
            self.update_recording_selection
        )

        layout.addWidget(self.recordings_table, 1)

        now_playing_box = QtWidgets.QFrame()
        now_playing_box.setStyleSheet(
            "QFrame {"
            "background-color: #0d1117;"
            "border: 1px solid #30363d;"
            "border-radius: 7px;"
            "}"
        )
        now_layout = QtWidgets.QVBoxLayout(
            now_playing_box
        )

        self.now_playing_label = QtWidgets.QLabel(
            "NOW PLAYING: nothing selected"
        )
        self.now_playing_label.setWordWrap(True)
        self.now_playing_label.setStyleSheet(
            "font-family: 'DejaVu Sans';"
            "font-size: 15px;"
            "font-weight: bold;"
            "color: #eef4f8;"
            "border: none;"
        )
        now_layout.addWidget(
            self.now_playing_label
        )

        self.playback_progress = QtWidgets.QProgressBar()
        self.playback_progress.setRange(0, 1000)
        self.playback_progress.setValue(0)
        self.playback_progress.setTextVisible(False)
        self.playback_progress.setFixedHeight(12)
        self.playback_progress.setStyleSheet(
            "QProgressBar {"
            "background: #161b22;"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
            "QProgressBar::chunk {"
            "background: #58a6ff;"
            "border-radius: 5px;"
            "}"
        )
        now_layout.addWidget(
            self.playback_progress
        )

        transport = QtWidgets.QHBoxLayout()

        self.play_button = QtWidgets.QPushButton(
            "▶ Play"
        )
        self.pause_button = QtWidgets.QPushButton(
            "⏸ Pause"
        )
        self.stop_button = QtWidgets.QPushButton(
            "■ Stop"
        )

        for button in (
            self.play_button,
            self.pause_button,
            self.stop_button,
        ):
            button.setMinimumHeight(38)
            button.setStyleSheet(
                "font-size: 14px;"
                "font-weight: bold;"
                "padding: 6px 14px;"
            )
            transport.addWidget(button)

        transport.addSpacing(10)

        self.playback_time_label = QtWidgets.QLabel(
            "00:00 / 00:00"
        )
        self.playback_time_label.setStyleSheet(
            "font-size: 14px;"
            "color: #b1bac4;"
            "border: none;"
        )
        transport.addWidget(
            self.playback_time_label
        )
        transport.addStretch()

        self.transcribe_button = QtWidgets.QPushButton(
            "Transcribe"
        )
        self.transcribe_button.setMinimumHeight(38)
        self.transcribe_button.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "padding: 6px 12px;"
        )
        transport.addWidget(self.transcribe_button)

        self.analyze_button = QtWidgets.QPushButton("Analyze")
        self.analyze_button.setMinimumHeight(38)
        self.analyze_button.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "padding: 6px 12px;"
        )
        transport.addWidget(self.analyze_button)

        self.process_button = QtWidgets.QPushButton("Isolate / Rebuild")
        self.process_button.setMinimumHeight(38)
        self.process_button.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "padding: 6px 12px;"
        )
        transport.addWidget(self.process_button)

        self.master_selected_button = QtWidgets.QPushButton("Master")
        self.master_selected_button.setMinimumHeight(38)
        self.master_selected_button.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "padding: 6px 12px;"
        )
        transport.addWidget(self.master_selected_button)

        self.delete_recording_button = QtWidgets.QPushButton(
            "Delete"
        )
        self.delete_recording_button.setMinimumHeight(38)
        self.delete_recording_button.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "padding: 6px 12px;"
            "color: #ffb3b3;"
            "background-color: #3a1717;"
            "border: 1px solid #f85149;"
            "border-radius: 4px;"
        )
        transport.addWidget(
            self.delete_recording_button
        )

        self.open_folder_button = QtWidgets.QPushButton(
            "Open Folder"
        )
        self.open_folder_button.setMinimumHeight(38)
        self.open_folder_button.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "padding: 6px 12px;"
        )
        transport.addWidget(
            self.open_folder_button
        )

        now_layout.addLayout(transport)

        automation_box = QtWidgets.QFrame()
        automation_box.setObjectName("automationBox")
        automation_box.setStyleSheet(
            "QFrame#automationBox {"
            "background: #090e13;"
            "border: 1px solid #24343d;"
            "border-radius: 6px;"
            "}"
            "QCheckBox {"
            "font-size: 13px;"
            "font-weight: 650;"
            "color: #b7c6ce;"
            "padding: 4px 8px;"
            "}"
        )
        automation_layout = QtWidgets.QHBoxLayout(automation_box)
        automation_layout.setContentsMargins(8, 5, 8, 5)

        automation_title = QtWidgets.QLabel("PROCESSING CONTROL")
        automation_title.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "font-weight: bold;"
            "color: #6bb8c7;"
            "border: none;"
        )
        automation_layout.addWidget(automation_title)
        automation_layout.addStretch()

        self.auto_processing_check = QtWidgets.QCheckBox("Auto Processing")
        self.auto_processing_check.setChecked(
            self.settings.value("auto_processing", False, type=bool)
        )
        automation_layout.addWidget(self.auto_processing_check)
        now_layout.addWidget(automation_box)

        self.processing_state_label = QtWidgets.QLabel(
            "ANALYSIS: NOT RUN   •   ISOLATION: NOT RUN   •   "
            "MASTERING: NOT RUN   •   TRANSCRIPTION: NOT RUN"
        )
        self.processing_state_label.setWordWrap(True)
        self.processing_state_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "color: #8fa0aa;"
            "background: #070b0f;"
            "border: 1px solid #24343d;"
            "border-radius: 5px;"
            "padding: 6px;"
        )
        now_layout.addWidget(self.processing_state_label)

        self.playback_transcript = QtWidgets.QPlainTextEdit()
        self.playback_transcript.setReadOnly(True)
        self.playback_transcript.setMinimumHeight(130)
        self.playback_transcript.setPlaceholderText(
            "Select a recording to view its transcript."
        )
        self.playback_transcript.setStyleSheet(
            "QPlainTextEdit {"
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 14px;"
            "color: #dce8ee;"
            "background: #090d12;"
            "border: 1px solid #30363d;"
            "border-radius: 5px;"
            "padding: 7px;"
            "}"
        )
        now_layout.addWidget(self.playback_transcript)

        layout.addWidget(now_playing_box)

        self.play_button.clicked.connect(
            self.play_selected_recording
        )
        self.pause_button.clicked.connect(
            self.toggle_pause_playback
        )
        self.stop_button.clicked.connect(
            self.stop_playback
        )
        self.open_folder_button.clicked.connect(
            self.open_recordings_folder
        )
        self.transcribe_button.clicked.connect(
            self.transcribe_selected_recording
        )
        self.analyze_button.clicked.connect(
            self.analyze_selected_recording
        )
        self.process_button.clicked.connect(
            self.process_selected_recording
        )
        self.master_selected_button.clicked.connect(
            self.master_selected_recording
        )
        self.auto_processing_check.toggled.connect(
            self.set_auto_processing
        )
        self.delete_recording_button.clicked.connect(
            self.delete_selected_recording
        )

        self.delete_recording_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence(
                QtGui.QKeySequence.StandardKey.Delete
            ),
            self.recordings_table,
        )
        self.delete_recording_shortcut.activated.connect(
            self.delete_selected_recording
        )

        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.delete_recording_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.process_button.setEnabled(False)
        self.master_selected_button.setEnabled(False)
        self.transcribe_button.setEnabled(False)

    @staticmethod
    def _format_seconds(seconds):
        seconds = max(0, int(round(float(seconds))))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            return f"{hours:d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_bytes(size):
        value = float(size)

        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024.0 or unit == "GB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0

        return f"{value:.1f} GB"

    def _recording_metadata(self, path):
        duration = 0.0

        try:
            with wave.open(str(path), "rb") as wf:
                rate = int(wf.getframerate())
                frames = int(wf.getnframes())
                if rate > 0:
                    duration = frames / rate
        except Exception:
            pass

        stem = path.stem

        if (
            stem.endswith("_master")
            or "_master_" in stem
        ):
            version = "MASTER"
        elif stem.endswith("_isolated"):
            version = "ISOLATED"
        elif stem.endswith("_raw"):
            version = "RAW"
        else:
            version = "WAV"

        recorded_text = datetime.fromtimestamp(
            path.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M:%S")

        transcript_path = self._transcript_for_audio(path)

        return {
            "path": path,
            "recorded": recorded_text,
            "version": version,
            "duration": duration,
            "size": path.stat().st_size,
            "transcript_path": transcript_path,
        }

    @staticmethod
    def _direct_transcript_path(path):
        return Path(path).with_suffix(".txt")

    def _transcript_for_audio(self, path):
        path = Path(path)
        direct = self._direct_transcript_path(path)

        if direct.exists():
            return direct

        if path.stem.endswith("_raw"):
            paired = path.with_name(
                path.stem[:-4]
                + "_isolated.txt"
            )
            if paired.exists():
                return paired

        if path.stem.endswith("_isolated"):
            paired = path.with_name(
                path.stem[:-9]
                + "_raw.txt"
            )
            if paired.exists():
                return paired

        return None

    def _read_transcript_for_audio(self, path):
        transcript = self._transcript_for_audio(path)

        if transcript is None:
            return ""

        try:
            return transcript.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            report_exception(
                f"reading transcript {transcript}",
                exc,
            )
            return f"Transcript read error: {exc}"


    def refresh_recordings(self):
        """
        Refresh RECORDINGS using one logical row per capture.

        RAW and ISOLATED WAV files remain preserved on disk.
        The UI prefers ISOLATED for playback/transcription/mastering
        and falls back to RAW when ISOLATED is unavailable.
        """

        log_path = Path(LOG_DIR)
        log_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Preserve logical selection using the currently resolved path.
        current_path = self.selected_recording_path()

        def logical_key(audio_path):
            stem = audio_path.stem

            if stem.endswith("_raw"):
                return stem[:-4]

            if stem.endswith("_isolated"):
                return stem[:-9]

            return stem

        groups = {}

        for audio_path in log_path.glob("*.wav"):
            key = logical_key(audio_path)

            entry = groups.setdefault(
                key,
                {
                    "raw": None,
                    "isolated": None,
                    "other": [],
                },
            )

            if audio_path.stem.endswith("_raw"):
                entry["raw"] = audio_path

            elif audio_path.stem.endswith("_isolated"):
                entry["isolated"] = audio_path

            else:
                entry["other"].append(audio_path)

        logical_rows = []

        for key, entry in groups.items():
            preferred = (
                entry["isolated"]
                if (
                    entry["isolated"] is not None
                    and entry["isolated"].exists()
                )
                else entry["raw"]
                if (
                    entry["raw"] is not None
                    and entry["raw"].exists()
                )
                else (
                    entry["other"][0]
                    if entry["other"]
                    else None
                )
            )

            if preferred is None:
                continue

            try:
                modified = max(
                    p.stat().st_mtime
                    for p in (
                        entry["raw"],
                        entry["isolated"],
                        *entry["other"],
                    )
                    if p is not None and p.exists()
                )
            except Exception:
                modified = preferred.stat().st_mtime

            logical_rows.append(
                {
                    "key": key,
                    "preferred": preferred,
                    "raw": entry["raw"],
                    "isolated": entry["isolated"],
                    "modified": modified,
                }
            )

        logical_rows.sort(
            key=lambda item: item["modified"],
            reverse=True,
        )

        self.recordings_table.setRowCount(
            len(logical_rows)
        )

        restore_row = -1

        current_key = (
            logical_key(current_path)
            if current_path is not None
            else None
        )

        for row, logical in enumerate(logical_rows):
            preferred = logical["preferred"]
            meta = self._recording_metadata(preferred)

            transcript_path = self._transcript_for_audio(
                preferred
            )

            pair_state = (
                "RAW + ISOLATED"
                if (
                    logical["raw"] is not None
                    and logical["isolated"] is not None
                )
                else "ISOLATED"
                if logical["isolated"] is not None
                else "RAW"
                if logical["raw"] is not None
                else meta.get("version", "WAV")
            )

            values = [
                meta["recorded"],
                pair_state,
                self._format_seconds(
                    meta["duration"]
                ),
                self._format_bytes(
                    meta["size"]
                ),
                (
                    "READY"
                    if transcript_path is not None
                    else "—"
                ),
                logical["key"],
            ]

            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(
                    str(value)
                )

                # File/path column remains the actual working path.
                if column == 5:
                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole,
                        str(preferred.resolve()),
                    )

                    # Preserve the companion paths for future logical actions.
                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole + 1,
                        (
                            str(logical["raw"].resolve())
                            if logical["raw"] is not None
                            else ""
                        ),
                    )

                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole + 2,
                        (
                            str(logical["isolated"].resolve())
                            if logical["isolated"] is not None
                            else ""
                        ),
                    )

                if pair_state == "RAW + ISOLATED":
                    item.setToolTip(
                        "Logical recording: RAW source and "
                        "ISOLATED working copy are both preserved."
                    )

                self.recordings_table.setItem(
                    row,
                    column,
                    item,
                )

            if (
                current_key is not None
                and logical["key"] == current_key
            ):
                restore_row = row

        if hasattr(
            self,
            "recording_count_label",
        ):
            self.recording_count_label.setText(
                f"{len(logical_rows)} recording"
                + (
                    ""
                    if len(logical_rows) == 1
                    else "s"
                )
            )

        if restore_row >= 0:
            self.recordings_table.selectRow(
                restore_row
            )

    def selected_recording_path(self):
        paths = self.selected_recording_paths()
        if not paths:
            return None
        if len(paths) == 1:
            return paths[0]
        current = self._current_recording_path()
        return current if current is not None else None

    def update_recording_selection(self):
        paths = self.selected_recording_paths()
        self.delete_recording_button.setEnabled(bool(paths))

        active_path = self.selected_recording_path()
        playback_running = (
            self.playback_thread is not None
            and self.playback_thread.isRunning()
        )
        self.play_button.setEnabled(active_path is not None and not playback_running)
        has_active = active_path is not None
        self.transcribe_button.setEnabled(has_active)
        self.analyze_button.setEnabled(has_active)
        self.process_button.setEnabled(has_active)
        self.master_selected_button.setEnabled(has_active)

        if not paths:
            self.now_playing_label.setText("NOW PLAYING: nothing selected")
            self.playback_transcript.clear()
            return

        if len(paths) > 1:
            active_name = active_path.name if active_path is not None else "none"
            self.now_playing_label.setText(
                f"SELECTED: {len(paths)} recordings // ACTIVE: {active_name}"
            )
            self.playback_transcript.setPlainText(
                "Multiple recordings selected.\n"
                "Delete applies to every selected row.\n"
                "Play and Transcribe apply only to the ACTIVE row."
            )
            return

        path = paths[0]
        self.now_playing_label.setText(f"SELECTED: {path.name}")
        transcript_text = self._read_transcript_for_audio(path)
        if transcript_text:
            self.playback_transcript.setPlainText(transcript_text)
        else:
            self.playback_transcript.setPlainText(
                "No transcript yet. Click Transcribe or enable a local Whisper backend."
            )

    def play_selected_recording(self):
        if hasattr(self, "stop_mastering_playback"):
            self.stop_mastering_playback(wait=True)

        path = self.selected_recording_path()

        if path is None:
            self.now_playing_label.setText(
                "Select a recording first."
            )
            return

        self.stop_playback(wait=True)

        self.playback_progress.setValue(0)
        self.playback_time_label.setText(
            "00:00 / 00:00"
        )
        self.now_playing_label.setText(
            f"NOW PLAYING: {path.name}"
        )

        self.playback_thread = AudioPlaybackThread(
            str(path),
            self,
        )
        self.playback_thread.progress.connect(
            self.handle_playback_progress
        )
        self.playback_thread.playback_status.connect(
            self.handle_playback_status
        )
        self.playback_thread.playback_finished.connect(
            self.handle_playback_finished
        )

        self.pause_button.setText(
            "⏸ Pause"
        )
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.play_button.setEnabled(False)

        self.playback_thread.start()

    def toggle_pause_playback(self):
        thread = self.playback_thread
        if thread is None or not thread.isRunning():
            return

        with thread._state_lock:
            paused = thread._paused

        new_paused = not paused
        thread.set_paused(new_paused)

        self.pause_button.setText(
            "▶ Resume"
            if new_paused
            else "⏸ Pause"
        )

    def stop_playback(self, wait=False):
        thread = self.playback_thread

        if thread is None:
            return

        if thread.isRunning():
            thread.stop_playback()

            if wait:
                thread.wait(1500)

    def _from_stale_playback_thread(self):
        sender = self.sender()

        return (
            sender is not None
            and sender
            is not self.playback_thread
        )

    def handle_playback_progress(
        self,
        current_seconds,
        total_seconds,
    ):
        if self._from_stale_playback_thread():
            return

        if total_seconds > 0:
            ratio = (
                current_seconds
                / total_seconds
            )
        else:
            ratio = 0.0

        self.playback_progress.setValue(
            int(
                max(
                    0.0,
                    min(
                        1.0,
                        ratio,
                    ),
                )
                * 1000
            )
        )

        self.playback_time_label.setText(
            f"{self._format_seconds(current_seconds)} / "
            f"{self._format_seconds(total_seconds)}"
        )

    def handle_playback_status(self, status):
        if self._from_stale_playback_thread():
            return

        thread = self.playback_thread

        name = (
            Path(thread.filename).name
            if thread is not None
            else "recording"
        )

        if status == "PAUSED":
            self.now_playing_label.setText(
                f"PAUSED: {name}"
            )
        elif status == "PLAYING":
            self.now_playing_label.setText(
                f"NOW PLAYING: {name}"
            )
        elif status.startswith(
            "PLAYBACK ERROR"
        ):
            self.now_playing_label.setText(
                status
            )

    def handle_playback_finished(self):
        if self._from_stale_playback_thread():
            return

        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setText(
            "⏸ Pause"
        )

    def handle_short_event_logged(self, payload):
        try:
            locked_seconds = float(
                payload.get(
                    "locked_seconds",
                    0.0,
                )
            )
            peak_hz = float(
                payload.get(
                    "peak_hz",
                    0.0,
                )
            )
            ended_at = str(
                payload.get(
                    "ended_at",
                    "",
                )
            )

            clock_text = ended_at
            if "T" in ended_at:
                clock_text = ended_at.split(
                    "T",
                    1,
                )[1][:8]

            self.short_event_status_label.setText(
                f"Short signal logged at {clock_text}  •  "
                f"{locked_seconds:.1f}s lock  •  "
                f"{peak_hz:.0f} Hz  •  audio discarded"
            )
            self.short_event_status_label.setToolTip(
                f"Detection history: {SHORT_EVENT_LOG}"
            )

        except Exception as exc:
            report_exception(
                "short-event UI update",
                exc,
            )

    def set_auto_processing(self, enabled):
        enabled = bool(enabled)
        self.settings.setValue("auto_processing", enabled)
        self.settings.sync()
        if hasattr(self, "processing_state_label"):
            self.processing_state_label.setText(
                "AUTO PROCESSING: "
                + ("ON" if enabled else "OFF")
                + "   •   TRANSCRIPTION: MANUAL"
            )

    def auto_processing_enabled(self):
        return bool(
            hasattr(self, "auto_processing_check")
            and self.auto_processing_check.isChecked()
        )

    def _raw_isolated_pair_for_path(self, path):
        path = Path(path)
        if path.stem.endswith("_raw"):
            raw_path = path
            isolated_path = path.with_name(
                path.stem[:-4] + "_isolated.wav"
            )
        elif path.stem.endswith("_isolated"):
            isolated_path = path
            raw_path = path.with_name(
                path.stem[:-9] + "_raw.wav"
            )
        else:
            raw_path = path
            isolated_path = path.with_name(
                path.stem + "_isolated.wav"
            )
        return raw_path, isolated_path

    def analyze_selected_recording(self):
        path = self.selected_recording_path()
        if path is None:
            self.playback_transcript.setPlainText("Select a recording first.")
            return

        try:
            meta = self._recording_metadata(path)
            transcript = self._read_transcript_for_audio(path)
            self.processing_state_label.setText(
                "ANALYSIS: COMPLETE   •   ISOLATION: READY   •   "
                "MASTERING: MANUAL   •   TRANSCRIPTION: "
                + ("COMPLETE" if transcript else "NOT RUN")
            )
            self.playback_transcript.setPlainText(
                "RECORDING ANALYSIS\n"
                f"File: {path.name}\n"
                f"Duration: {meta.get('duration', 0.0):.2f} s\n"
                f"Size: {self._format_bytes(path.stat().st_size)}\n"
                f"Version: {meta.get('version', BCI_PROJECT_VERSION)}\n"
                f"Transcript: {'available' if transcript else 'not run'}\n\n"
                "Use Isolate / Rebuild for the reconstruction pipeline, "
                "Master for the mastering workspace, or Transcribe for Whisper."
            )
        except Exception as exc:
            self.processing_state_label.setText("ANALYSIS: FAILED")
            self.playback_transcript.setPlainText(
                "ANALYSIS ERROR\n" + str(exc)
            )

    def process_selected_recording(self):
        path = self.selected_recording_path()
        if path is None:
            self.playback_transcript.setPlainText("Select a recording first.")
            return

        raw_path, isolated_path = self._raw_isolated_pair_for_path(path)
        if not raw_path.exists():
            self.playback_transcript.setPlainText(
                "The RAW partner for this recording was not found. "
                "Reconstruction requires the retained RAW recording."
            )
            return
        if not isolated_path.exists():
            self.playback_transcript.setPlainText(
                "The isolated partner for this recording was not found."
            )
            return

        self.processing_state_label.setText(
            "ANALYSIS: QUEUED   •   ISOLATION: QUEUED   •   "
            "MASTERING: WAITING   •   TRANSCRIPTION: NOT RUN"
        )
        self.playback_transcript.setPlainText(
            f"Reconstruction queued: {isolated_path.name}"
        )
        self.postprocess_thread.submit(raw_path, isolated_path)

    def master_selected_recording(self):
        path = self.selected_recording_path()
        if path is None:
            self.playback_transcript.setPlainText("Select a recording first.")
            return
        self.main_tabs.setCurrentWidget(self.mastering_tab)
        self._master_load_recordings_selection()
        self.processing_state_label.setText(
            "MASTERING: READY — use the Mastering workspace controls."
        )

    def handle_recording_saved(
        self,
        raw_filename,
        isolated_filename,
    ):
        prune_old_recordings()
        self.refresh_recordings()

        raw_path = (
            Path(raw_filename)
            if raw_filename
            else None
        )
        isolated_path = (
            Path(isolated_filename)
            if isolated_filename
            else None
        )

        if (
            self.auto_processing_enabled()
            and raw_path is not None
            and isolated_path is not None
            and raw_path.exists()
            and isolated_path.exists()
        ):
            self.analysis_transcript.setPlainText(
                "Recording complete. "
                "Re-analyzing the captured spectrum and rebuilding "
                "the isolated signal for audibility..."
            )

            self.postprocess_thread.submit(
                raw_path,
                isolated_path,
            )
            return

    @guarded_slot("post-processing status")
    def handle_postprocess_status(self, message):
        message = str(message)

        if message.startswith(
            "RECONSTRUCTING:"
        ):
            self.analysis_transcript.setPlainText(
                message
                + "\n\n"
                + "BCI is rebuilding the isolated signal from RAW using the "
                "learned room profile, STFT spectral suppression, foreground "
                "masking, harmonic preservation, hum rejection, dynamics, "
                "loudness normalization, and quality control."
            )

    @guarded_slot("post-processing result")
    def handle_postprocess_result(self, result):
        raw_path = Path(
            str(
                result.get(
                    "raw_path",
                    "",
                )
            )
        )

        isolated_path = Path(
            str(
                result.get(
                    "isolated_path",
                    "",
                )
            )
        )

        if result.get("error"):
            message = (
                "RECONSTRUCTION ERROR\n"
                + str(
                    result["error"]
                )
                + "\n\nRAW and the previous isolated recording were preserved."
            )

            self.analysis_transcript.setPlainText(
                message
            )

            TELEMETRY_DAEMON.log_event(
                "POSTPROCESS_ERROR",
                json.dumps(
                    {
                        "project_version": BCI_PROJECT_VERSION,
                        "script_tally": BCI_SCRIPT_TALLY,
                        "build": BCI_BUILD,
                        "raw_file": str(raw_path),
                        "isolated_file": str(isolated_path),
                        "error": str(
                            result["error"]
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

            self.refresh_recordings()
            return

        low_hz = float(
            result.get(
                "low_hz",
                0.0,
            )
        )
        high_hz = float(
            result.get(
                "high_hz",
                0.0,
            )
        )
        hum_hz = result.get(
            "hum_hz",
            [],
        )
        foreground_probability = float(
            result.get(
                "foreground_probability",
                0.0,
            )
        )
        accepted = bool(
            result.get(
                "accepted",
                False,
            )
        )
        loudness_backend = str(
            result.get(
                "loudness_backend",
                "unknown",
            )
        )

        mud_cut_db = float(
            result.get(
                "mud_cut_db",
                0.0,
            )
        )
        presence_boost_db = float(
            result.get(
                "presence_boost_db",
                0.0,
            )
        )
        air_boost_db = float(
            result.get(
                "air_boost_db",
                0.0,
            )
        )
        deess_db = float(
            result.get(
                "deess_db",
                0.0,
            )
        )

        original_metrics = result.get(
            "original_metrics",
            {},
        )
        candidate_metrics = result.get(
            "candidate_metrics",
            {},
        )

        if accepted:
            outcome = (
                "LOUD + CLEAR MASTER ACCEPTED"
            )
            detail = (
                "The isolated WAV was atomically replaced with the mastered version."
            )
        else:
            outcome = (
                "MASTER REJECTED BY QUALITY GATE"
            )
            detail = (
                "The previous isolated WAV was kept unchanged."
            )

        hum_text = (
            ", ".join(
                f"{value:.0f} Hz"
                for value in hum_hz
            )
            if hum_hz
            else "none detected"
        )

        self.analysis_transcript.setPlainText(
            f"{outcome}\n"
            f"Occupied band: {low_hz:.0f}–{high_hz:.0f} Hz\n"
            f"Foreground probability: {foreground_probability:.2f}\n"
            f"Mud reduction: -{mud_cut_db:.1f} dB\n"
            f"Presence lift: +{presence_boost_db:.1f} dB\n"
            f"Air lift: +{air_boost_db:.1f} dB\n"
            f"Adaptive de-ess: -{deess_db:.1f} dB\n"
            f"Final target: {POSTPROCESS_TARGET_LUFS:.0f} LUFS / "
            f"{POSTPROCESS_TRUE_PEAK_DBTP:.0f} dBTP\n"
            f"Hum notches: {hum_text}\n"
            f"Loudness backend: {loudness_backend}\n"
            f"Original SNR proxy: "
            f"{float(original_metrics.get('snr_proxy_db', 0.0)):.1f} dB\n"
            f"Master SNR proxy: "
            f"{float(candidate_metrics.get('snr_proxy_db', 0.0)):.1f} dB\n"
            f"{detail}\n\n"
            "Transcription is manual unless Auto Transcribe is enabled."
        )

        TELEMETRY_DAEMON.log_event(
            (
                "POSTPROCESS_COMPLETE"
                if accepted
                else "POSTPROCESS_REJECTED"
            ),
            json.dumps(
                {
                    "project_version": BCI_PROJECT_VERSION,
                    "script_tally": BCI_SCRIPT_TALLY,
                    "build": BCI_BUILD,
                    **result,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

        self.refresh_recordings()

    def transcribe_selected_recording(self):
        path = self.selected_recording_path()

        if path is None:
            self.playback_transcript.setPlainText(
                "Select a recording first."
            )
            return

        preferred = path

        if path.stem.endswith("_raw"):
            isolated = path.with_name(
                path.stem[:-4]
                + "_isolated.wav"
            )

            if isolated.exists():
                preferred = isolated

        self.playback_transcript.setPlainText(
            f"Transcription queued: {preferred.name}"
        )

        self.transcription_thread.submit(
            preferred,
            reason="manual",
        )

    @guarded_slot("transcription status")
    def handle_transcription_status(self, message):
        message = str(message)

        if message.startswith("TRANSCRIBING"):
            self.analysis_transcript.setPlainText(message)

    @guarded_slot("transcription result")
    def handle_transcription_result(self, result):
        if result.get("error"):
            message = (
                "TRANSCRIPTION UNAVAILABLE\n"
                + str(result["error"])
                + "\n\nInstall openai-whisper (primary) or faster-whisper (fallback), "
                "or configure whisper.cpp using "
                "BCI_WHISPER_CPP_MODEL."
            )

            self.analysis_transcript.setPlainText(message)

            if self.selected_recording_path() is not None:
                self.playback_transcript.setPlainText(message)

            return

        transcript_path = Path(
            str(
                result.get(
                    "transcript_path",
                    "",
                )
            )
        )

        try:
            transcript_text = transcript_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            report_exception(
                "transcription result read",
                exc,
            )
            transcript_text = str(
                result.get("text", "")
            )

        self.analysis_transcript.setPlainText(
            transcript_text
        )

        selected = self.selected_recording_path()

        if selected is not None:
            selected_transcript = self._transcript_for_audio(
                selected
            )

            if (
                selected_transcript is not None
                and transcript_path.exists()
                and selected_transcript.resolve()
                == transcript_path.resolve()
            ):
                self.playback_transcript.setPlainText(
                    transcript_text
                )

        self.refresh_recordings()

    def open_recordings_folder(self):
        path = Path(LOG_DIR).resolve()
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(
                str(path)
            )
        )

    # --------------------------------------------------------------------------
    # Device UI
    # --------------------------------------------------------------------------

    @staticmethod
    def _safe_capture_endpoint(device):
        try:
            channels = int(device.get("max_input_channels", 0))
        except Exception:
            channels = 0

        if channels <= 0:
            return False

        name = str(device.get("name", "")).strip().lower()

        if name in {
            "upmix",
            "vdownmix",
            "lavrate",
            "samplerate",
            "speexrate",
            "speex",
        }:
            return False

        if ".monitor" in name or name.endswith(" monitor"):
            return False

        if name.startswith("bluez_output."):
            return False

        return True

    @staticmethod
    def _stable_capture_identity(device_name):
        """Normalize volatile ALSA hw:X,Y numbering out of a device name."""
        name = " ".join(
            str(device_name or "").strip().casefold().split()
        )
        name = re.sub(
            r"\((?:plug)?hw:\d+,\d+\)",
            "",
            name,
        )
        name = re.sub(
            r"(?<![a-z])(?:plug)?hw:\d+,\d+(?![a-z])",
            "",
            name,
        )
        return " ".join(name.split()).strip(" -:")

    @staticmethod
    def _normalize_bluetooth_address(value):
        return (
            str(value or "")
            .strip()
            .upper()
            .replace("_", ":")
            .replace("-", ":")
        )

    @staticmethod
    def _bluetooth_address_from_portaudio_name(device_name):
        """
        Extract a BlueZ MAC from names such as:
            bluez_input.B8:84:11:65:F2:BC
            bluez_input.B8_84_11_65_F2_BC.0
        """
        name = str(device_name or "")
        match = re.search(
            r"bluez_input[.:]([0-9A-Fa-f:_-]{17})",
            name,
        )
        if not match:
            return ""

        return BCIWindow._normalize_bluetooth_address(
            match.group(1)
        )

    def _paired_bluetooth_devices(self):
        """Return the boundary-published BlueZ snapshot without blocking Qt."""
        return list(getattr(self, "_cached_paired_bluetooth", []) or [])

    def _system_default_source_name(self):
        """Return the cached signature published by the audio boundary."""
        return str(getattr(self, "_system_default_signature", "") or "")

    def _audio_device_fingerprint(self):
        """Return the cached topology fingerprint; never enumerate PortAudio."""
        return getattr(self, "_audio_device_snapshot", ()) or ()

    @staticmethod
    def _usb_capture_devices(devices):
        out = []

        for index, device in enumerate(devices):
            if not BCIWindow._safe_capture_endpoint(device):
                continue

            name = str(device.get("name", "Unknown USB Input"))
            lowered = name.lower()

            if "usb" not in lowered:
                continue

            out.append((index, device))

        return out

    @classmethod
    def _bluetooth_capture_map(cls, devices):
        """
        Map stable BlueZ MAC addresses to current bluez_input PortAudio indices.
        """
        endpoints = {}

        for index, device in enumerate(devices):
            if not cls._safe_capture_endpoint(device):
                continue

            name = str(device.get("name", ""))
            address = cls._bluetooth_address_from_portaudio_name(name)

            if not address:
                continue

            endpoints.setdefault(
                address,
                (index, device),
            )

        return endpoints

    def populate_audio_devices(
        self,
        preserve_device_id=None,
        preserve_device_name="",
        selection_mode=None,
    ):
        """Populate the selector from the most recent background snapshot.

        This function is deliberately GUI-only: it performs no PortAudio
        enumeration and launches no subprocesses.
        """
        devices = list(
            getattr(self, "_cached_audio_devices", []) or []
        )
        paired_devices = list(
            getattr(self, "_cached_paired_bluetooth", []) or []
        )

        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()

        endpoint_name_role = (
            QtCore.Qt.ItemDataRole.UserRole + 2
        )

        self.mic_combo.addItem(
            "System Default",
            -1,
        )
        self.mic_combo.setItemData(
            0,
            "",
            endpoint_name_role,
        )

        selected_combo_index = 0
        matched_saved_device = False

        selection_mode = str(
            selection_mode
            or self.settings.value(
                "input_selection_mode",
                "auto",
                type=str,
            )
            or "auto"
        ).lower()

        preserve_explicit = selection_mode == "explicit"
        preserve_stable_key = self._stable_capture_identity(
            preserve_device_name
        )
        usb_entries = self._usb_capture_devices(devices)
        stable_usb_counts = {}
        for _, device in usb_entries:
            key = self._stable_capture_identity(
                device.get("name", "")
            )
            if key:
                stable_usb_counts[key] = stable_usb_counts.get(key, 0) + 1

        # USB class.
        for index, device in usb_entries:
            device_name = str(
                device.get("name", "USB Microphone")
            )
            label = f"USB — {device_name}"
            combo_index = self.mic_combo.count()
            self.mic_combo.addItem(label, index)
            self.mic_combo.setItemData(
                combo_index,
                device_name,
                endpoint_name_role,
            )

            if preserve_explicit:
                device_stable_key = self._stable_capture_identity(
                    device_name
                )
                stable_name_match = bool(
                    preserve_stable_key
                    and device_stable_key == preserve_stable_key
                    and stable_usb_counts.get(device_stable_key, 0) == 1
                )
                if (
                    preserve_device_name
                    and (
                        device_name == preserve_device_name
                        or stable_name_match
                    )
                ):
                    selected_combo_index = combo_index
                    matched_saved_device = True
                elif not preserve_device_name and preserve_device_id is not None:
                    # A PortAudio index is a legacy locator only when no stable
                    # name was stored. Never let a stale index select a different
                    # microphone after hot-plug renumbering.
                    try:
                        if int(preserve_device_id) == index:
                            selected_combo_index = combo_index
                            matched_saved_device = True
                    except (TypeError, ValueError):
                        pass

        # Bluetooth identity comes from the cached BlueZ probe result.
        bluetooth_endpoints = self._bluetooth_capture_map(devices)

        for item in paired_devices:
            address = str(item.get("address", ""))
            display_name = str(item.get("name", address or "Bluetooth"))
            endpoint = bluetooth_endpoints.get(address)

            if endpoint is not None:
                index, device = endpoint
                endpoint_name = str(
                    device.get("name", "")
                )
                label = f"Bluetooth — {display_name}"
                combo_index = self.mic_combo.count()
                self.mic_combo.addItem(label, index)
                self.mic_combo.setItemData(
                    combo_index,
                    address,
                    QtCore.Qt.ItemDataRole.UserRole + 1,
                )
                self.mic_combo.setItemData(
                    combo_index,
                    endpoint_name,
                    endpoint_name_role,
                )

                if preserve_explicit:
                    if (
                        preserve_device_name
                        and endpoint_name == preserve_device_name
                    ):
                        selected_combo_index = combo_index
                        matched_saved_device = True
                    elif not preserve_device_name and preserve_device_id is not None:
                        try:
                            if int(preserve_device_id) == index:
                                selected_combo_index = combo_index
                                matched_saved_device = True
                        except (TypeError, ValueError):
                            pass
            else:
                status = (
                    "paired / disconnected"
                    if not bool(item.get("connected", False))
                    else "paired / microphone unavailable"
                )
                label = f"Bluetooth — {display_name} ({status})"
                combo_index = self.mic_combo.count()
                self.mic_combo.addItem(label, None)
                self.mic_combo.setItemData(
                    combo_index,
                    address,
                    QtCore.Qt.ItemDataRole.UserRole + 1,
                )
                self.mic_combo.setItemData(
                    combo_index,
                    "",
                    endpoint_name_role,
                )

                model_item = self.mic_combo.model().item(
                    combo_index
                )
                if model_item is not None:
                    model_item.setEnabled(False)

        if preserve_explicit and not matched_saved_device and devices:
            self.device_status_label.setText(
                "Saved USB/Bluetooth microphone is unavailable; "
                "System Default is selected."
            )

        self.mic_combo.setCurrentIndex(
            selected_combo_index
        )
        self.boot_screen.set_microphone(
            self.mic_combo.currentText()
        )
        self.mic_combo.blockSignals(False)

    def refresh_audio_devices(self):
        """Request a non-blocking hardware refresh."""
        self.device_status_label.setText(
            "Refreshing audio devices in background..."
        )
        self.request_audio_device_probe()

    def request_audio_device_probe(self):
        thread = getattr(self, "audio_boundary_thread", None)
        if thread is not None and thread.isRunning():
            thread.request_probe()

    def sync_audio_devices(self):
        """Compatibility entry point; never performs discovery on the GUI."""
        self.request_audio_device_probe()

    @guarded_slot("audio device probe error")
    def handle_audio_probe_error(self, message):
        self.device_status_label.setText(
            f"Audio-device probe warning: {message}"
        )

    @guarded_slot("audio device probe snapshot")
    def handle_audio_probe_snapshot(self, result):
        """Consume a precomputed device snapshot without blocking Qt."""
        devices = list(result.get("devices", []) or [])
        paired_devices = list(
            result.get("paired_devices", []) or []
        )
        snapshot = result.get("fingerprint", ())
        default_signature = str(
            result.get("default_signature", "")
        )

        first_snapshot = not bool(
            getattr(self, "_audio_probe_initialized", False)
        )
        old_snapshot = getattr(
            self,
            "_audio_device_snapshot",
            None,
        )
        old_default = getattr(
            self,
            "_system_default_signature",
            None,
        )

        topology_changed = (
            not first_snapshot
            and snapshot != old_snapshot
        )
        default_changed = (
            not first_snapshot
            and default_signature != old_default
        )

        self._cached_audio_devices = devices
        self._cached_paired_bluetooth = paired_devices
        self._audio_device_snapshot = snapshot
        self._system_default_signature = default_signature
        self._audio_probe_initialized = True

        endpoint_name_role = (
            QtCore.Qt.ItemDataRole.UserRole + 2
        )

        if first_snapshot:
            preserve_device_id = getattr(
                self,
                "_saved_device_id",
                -999,
            )
            preserve_device_name = getattr(
                self,
                "_saved_device_name",
                "",
            )
            selection_mode = getattr(
                self,
                "_saved_selection_mode",
                "auto",
            )
        else:
            preserve_device_id = self.mic_combo.currentData()
            preserve_device_name = str(
                self.mic_combo.currentData(endpoint_name_role)
                or self.settings.value(
                    "last_input_device_name",
                    "",
                    type=str,
                )
                or ""
            )
            selection_mode = self.settings.value(
                "input_selection_mode",
                "auto",
                type=str,
            )

        if first_snapshot or topology_changed:
            old_device_id = self.mic_combo.currentData()

            self.populate_audio_devices(
                preserve_device_id=preserve_device_id,
                preserve_device_name=preserve_device_name,
                selection_mode=selection_mode,
            )

            new_device_id = self.mic_combo.currentData()

            # A topology update can invalidate an explicit selection. Push the
            # resulting cached selection to the audio worker exactly once.
            if new_device_id != old_device_id or first_snapshot:
                if (
                    hasattr(self, "audio_thread")
                    and self.audio_thread.isRunning()
                ):
                    try:
                        new_int = int(
                            -1 if new_device_id is None else new_device_id
                        )
                    except (TypeError, ValueError):
                        new_int = -1

                    current_worker_id = int(
                        getattr(
                            self.audio_thread,
                            "selected_device_id",
                            -1,
                        )
                    )

                    if new_int != current_worker_id:
                        # Script 57.1: discovery reports route changes but does
                        # not own page state. update_parameters() asks the worker
                        # to reopen; baseline_started is the sole authority that
                        # may re-enter the full boot/baseline page.
                        self.device_status_label.setText(
                            "Discovered microphone route changed; "
                            "waiting for capture stream confirmation..."
                        )

                self.apply_params_now()

        current_device = self.mic_combo.currentData()
        try:
            auto_mode = (
                current_device is None
                or int(current_device) < 0
            )
        except (TypeError, ValueError):
            auto_mode = True

        if (
            default_changed
            and auto_mode
            and hasattr(self, "audio_thread")
        ):
            if (
                hasattr(self, "live_broadcaster")
                and self.live_broadcaster.is_live
            ):
                self.stop_go_live()
                self.live_url_label.setText(
                    "Go Live stopped because the system default microphone "
                    "changed. Press GO LIVE after the new input calibrates."
                )

            # Script 57.5: the boundary process owns default-route recovery.
            # The GUI reports state but never commands a second, competing open.
            self.device_status_label.setText(
                "System microphone route changed; "
                "isolated audio boundary is reconciling capture..."
            )

        if not first_snapshot:
            self.device_status_label.setText(
                "Audio-device background sync complete."
            )

    # --------------------------------------------------------------------------
    # Go Live
    # --------------------------------------------------------------------------

    def handle_live_audio_block(self, packet):
        if not self.go_live_controller.is_live:
            return

        block = packet.get("block")
        sample_rate = packet.get(
            "sample_rate",
            self.audio_thread.sample_rate,
        )

        # BroadcastBus is deliberately non-blocking. A slow future publisher
        # may lose stale broadcast frames but can never stall local capture.
        self.broadcast_bus.publish_audio(
            block,
            sample_rate,
            channels=1,
        )

        try:
            samples = np.asarray(block, dtype=np.float32).reshape(-1)
            if samples.size:
                rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
                peak = float(np.max(np.abs(samples)))
                level_dbfs = 20.0 * np.log10(max(rms, 1e-9))
                peak_dbfs = 20.0 * np.log10(max(peak, 1e-9))
            else:
                level_dbfs = -180.0
                peak_dbfs = -180.0

            bus_stats = self.broadcast_bus.stats()
            public_payload = sanitize_public_broadcast_telemetry({
                "broadcast_state": self.go_live_controller.state.value,
                "uptime_seconds": self.go_live_controller.uptime_seconds,
                "sample_rate": int(sample_rate),
                "channels": 1,
                "level_dbfs": round(float(level_dbfs), 2),
                "peak_dbfs": round(float(peak_dbfs), 2),
                "codec": "mp3",
                "bitrate_kbps": int(LIVE_STREAM_BITRATE_KBPS),
                "connections": int(getattr(self.live_broadcaster, "client_count", 0)),
                "dropped_audio_frames": int(bus_stats["audio_dropped"]),
            })
            self.broadcast_bus.publish_telemetry(public_payload)
        except Exception:
            # Telemetry must never interrupt the realtime audio path.
            pass

        # Script 51 preserves the v5 local broadcaster as a compatibility
        # publisher. Script 52 replaces this handoff with outbound publishing.
        try:
            if self.live_broadcaster.is_live:
                self.live_broadcaster.submit_audio(
                    block,
                    sample_rate,
                )
        except Exception as exc:
            self.handle_live_error(str(exc))

    def set_go_live(self, enabled):
        enabled = bool(
            enabled
        )

        if enabled:
            try:
                self.go_live_controller.begin_start()
                sample_rate = max(
                    8000,
                    int(
                        getattr(
                            self.audio_thread,
                            "sample_rate",
                            48000,
                        )
                    ),
                )

                url = self.live_broadcaster.start_live(
                    sample_rate
                )
                self.audio_thread.set_live_stream_enabled(
                    True
                )
                self.go_live_controller.mark_live()

                self.go_live_button.setText(
                    "STOP LIVE"
                )
                self.live_url_label.setText(
                    f"Listen: {url}"
                )

                TELEMETRY_DAEMON.log_event(
                    "LIVE_STREAM_STARTED",
                    json.dumps(
                        {
                            "project_version": BCI_PROJECT_VERSION,
                            "script_tally": BCI_SCRIPT_TALLY,
                            "build": BCI_BUILD,
                            "url": str(url),
                            "bind_host": str(
                                LIVE_STREAM_HOST
                            ),
                            "port": int(
                                LIVE_STREAM_PORT
                            ),
                            "sample_rate": int(
                                sample_rate
                            ),
                            "bitrate_kbps": int(
                                LIVE_STREAM_BITRATE_KBPS
                            ),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )

            except Exception as exc:
                try:
                    self.go_live_controller.fail(str(exc))
                except Exception:
                    pass
                self.audio_thread.set_live_stream_enabled(
                    False
                )

                self.go_live_button.blockSignals(
                    True
                )
                self.go_live_button.setChecked(
                    False
                )
                self.go_live_button.blockSignals(
                    False
                )
                self.go_live_button.setText(
                    "GO LIVE"
                )

                self.live_status_label.setText(
                    "OFFLINE"
                )
                self.live_url_label.setText(
                    f"Go Live failed: {exc}"
                )
                self.show_runtime_error(
                    "Go Live",
                    str(exc),
                )

        else:
            self.stop_go_live()

    def stop_go_live(self):
        was_live = bool(
            self.live_broadcaster.is_live
        )

        try:
            self.go_live_controller.begin_stop()
        except Exception:
            pass

        self.audio_thread.set_live_stream_enabled(
            False
        )

        try:
            self.live_broadcaster.stop_live()
        except Exception as exc:
            report_exception(
                "Go Live stop",
                exc,
            )

        self.broadcast_bus.clear()
        try:
            self.go_live_controller.mark_offline()
        except Exception:
            pass

        self.go_live_button.blockSignals(
            True
        )
        self.go_live_button.setChecked(
            False
        )
        self.go_live_button.blockSignals(
            False
        )
        self.go_live_button.setText(
            "GO LIVE"
        )
        self.live_status_label.setText(
            "OFFLINE"
        )
        self.live_status_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "font-weight: 800;"
            "color: #6f7e86;"
            "background: transparent;"
            "border: none;"
        )
        self.live_url_label.setText(
            "Go Live is off. No streaming server is running."
        )
        self.live_clients_label.setText(
            "0 listeners"
        )

        if was_live:
            try:
                TELEMETRY_DAEMON.log_event(
                    "LIVE_STREAM_STOPPED",
                    json.dumps(
                        {
                            "project_version": BCI_PROJECT_VERSION,
                            "script_tally": BCI_SCRIPT_TALLY,
                            "build": BCI_BUILD,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            except Exception:
                pass

    def handle_live_status(self, message, live):
        self.live_status_label.setText(
            "LIVE"
            if live
            else "OFFLINE"
        )
        self.live_status_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono';"
            "font-size: 12px;"
            "font-weight: 800;"
            f"color: {'#b96b74' if live else '#6f7e86'};"
            "background: transparent;"
            "border: none;"
        )

        if live:
            self.live_url_label.setText(
                str(message)
            )

    def handle_live_client_count(self, count):
        count = max(
            0,
            int(count),
        )

        self.live_clients_label.setText(
            f"{count} "
            + (
                "listener"
                if count == 1
                else "listeners"
            )
        )

    def handle_live_error(self, message):
        self.live_url_label.setText(
            f"Live stream warning: {message}"
        )

    # --------------------------------------------------------------------------
    # Parameter UI
    # --------------------------------------------------------------------------

    def update_parameter_labels(self):
        self.lowcut_value.setText(
            f"{self.lowcut_slider.value()} Hz"
        )
        self.highcut_value.setText(
            f"{self.highcut_slider.value()} Hz"
        )
        self.input_volume_value.setText(
            f"{self.input_volume_slider.value()}%"
        )
        self.sens_value.setText(
            f"{self.sens_slider.value() / 10.0:.1f}"
        )

    def on_input_volume_changed(self, value):
        """
        Keep the user-facing control simple while mapping it to the existing
        live DSP gain underneath. 100% equals DEFAULT_GAIN.
        """
        value = max(
            25,
            min(
                200,
                int(value),
            ),
        )

        self.input_volume_value.setText(
            f"{value}%"
        )
        self.settings.setValue(
            "input_volume_percent",
            value,
        )
        self.settings.sync()

        self.on_param_changed()

    def on_device_changed(self):
        if (
            hasattr(self, "live_broadcaster")
            and self.live_broadcaster.is_live
        ):
            self.stop_go_live()
            self.live_url_label.setText(
                "Go Live stopped because the microphone changed. "
                "Press GO LIVE after the new input opens."
            )

        device_id = self.mic_combo.currentData()
        if device_id is None:
            device_id = -1

        if int(device_id) >= 0:
            endpoint_name_role = (
                QtCore.Qt.ItemDataRole.UserRole + 2
            )
            device_name = str(
                self.mic_combo.currentData(endpoint_name_role)
                or self.mic_combo.currentText()
            )
        else:
            device_name = ""

        self.settings.setValue(
            "last_input_device_id",
            int(device_id),
        )
        self.settings.setValue(
            "last_input_device_name",
            device_name,
        )
        self.settings.setValue(
            "input_selection_mode",
            "explicit" if int(device_id) >= 0 else "auto",
        )
        self.settings.sync()

        selected_display_name = self.mic_combo.currentText()
        self.boot_screen.set_microphone(
            selected_display_name
        )
        self.device_status_label.setText(
            f"Selected: {selected_display_name}"
        )
        self.device_status_label.setStyleSheet(
            "font-size: 11px;"
            "font-weight: 600;"
            "color: #8fa2ac;"
            "background: transparent;"
            "border: none;"
        )

        if (
            hasattr(self, "audio_thread")
            and self.audio_thread.isRunning()
        ):
            # Script 57.1: selecting a route requests the worker change, but the
            # GUI does not enter a new full-baseline boot state until the worker
            # confirms that the replacement capture stream actually opened.
            self.device_status_label.setText(
                f"Switching to {selected_display_name}; "
                "waiting for capture confirmation..."
            )

        self.apply_params_now()

    def on_param_changed(self):
        """
        Update labels immediately, then apply the engine parameters once slider
        activity pauses briefly.
        """
        self.update_parameter_labels()

        if hasattr(
            self,
            "_param_debounce",
        ):
            self._param_debounce.start()

    def apply_params_now(self):
        if hasattr(
            self,
            "_param_debounce",
        ):
            self._param_debounce.stop()

        self.update_parameter_labels()

        lowcut = self.lowcut_slider.value()
        highcut = self.highcut_slider.value()

        if lowcut >= highcut:
            highcut = min(
                20000,
                lowcut + 100,
            )

            self.highcut_slider.blockSignals(
                True
            )
            self.highcut_slider.setValue(
                highcut
            )
            self.highcut_slider.blockSignals(
                False
            )

            self.update_parameter_labels()

        volume_percent = float(
            self.input_volume_slider.value()
        )
        gain = (
            DEFAULT_GAIN
            * volume_percent
            / 100.0
        )
        sensitivity = (
            self.sens_slider.value()
            / 10.0
        )

        device_id = self.mic_combo.currentData()

        if device_id is None:
            device_id = -1

        endpoint_name_role = (
            QtCore.Qt.ItemDataRole.UserRole + 2
        )

        # Before the first hardware snapshot arrives the combo necessarily
        # contains only System Default. Preserve a saved explicit *name* as the
        # startup intent so a stale/missing PortAudio index cannot silently
        # rewrite the operator's selection.
        if (
            not bool(getattr(self, "_audio_probe_initialized", False))
            and str(getattr(self, "_saved_selection_mode", "auto")).lower() == "explicit"
            and str(getattr(self, "_saved_device_name", "") or "")
        ):
            selection_mode = "explicit"
            device_name = str(self._saved_device_name or "")
            try:
                device_id = int(self._saved_device_id)
            except (TypeError, ValueError):
                device_id = -1
        else:
            device_name = str(
                self.mic_combo.currentData(endpoint_name_role)
                or ""
            )
            selection_mode = (
                "explicit"
                if int(device_id) >= 0
                else "auto"
            )

        self.audio_thread.update_parameters(
            lowcut,
            highcut,
            gain,
            sensitivity,
            int(device_id),
            device_name=device_name,
            selection_mode=selection_mode,
        )

    # --------------------------------------------------------------------------
    # Worker event handling
    # --------------------------------------------------------------------------

    def show_runtime_error(self, context, message):
        display_text = (
            f"ERROR [{context}]: {message} "
            f"— details logged to {ERROR_LOG}"
        )

        if hasattr(
            self,
            "runtime_error_label",
        ):
            self.runtime_error_label.setText(
                display_text
            )
            self.runtime_error_label.setVisible(
                True
            )

        LOGGER.error(
            "Visible runtime error [%s]: %s",
            context,
            message,
        )

    @guarded_slot("runtime error signal")
    def handle_runtime_error(self, context, message):
        self.show_runtime_error(
            context,
            message,
        )

    @guarded_slot("device status update")
    def handle_device_status(self, message, success):
        color = (
            "#5fa77a"
            if success
            else "#a94249"
        )

        self.boot_screen.set_device_status(
            message,
            success,
        )

        self.device_status_label.setText(
            message
        )
        self.device_status_label.setStyleSheet(
            "font-size: 11px;"
            "font-weight: 600;"
            f"color: {color};"
            "background: transparent;"
            "border: none;"
        )

    @guarded_slot("baseline interruption")
    def handle_baseline_interrupted(self, message):
        """Report capture loss without ever trapping an entered main display.

        Before the first live microphone block, the boot page remains a truthful
        waiting screen.  After the main display has been entered once, capture
        recovery and recalibration happen in-place on the analyzer page.
        """
        self.device_status_label.setText(
            f"Capture interrupted: {message}"
        )

        if not self._main_display_entered:
            self.app_state.mark_waiting_for_audio(str(message))
            self.page_stack.setCurrentWidget(self.boot_screen)
            self.boot_screen.wait_for_microphone(
                "Microphone stream interrupted; waiting for live audio frames..."
            )
            print(
                "[BCI] Capture interrupted before main display -> "
                "waiting for live microphone frames"
            )
            return

        self.app_state.mark_recovering(str(message))
        self._show_analyzer_page()
        self.status_label.setText(
            "STATUS: [MICROPHONE INTERRUPTED] "
            "WAITING FOR LIVE AUDIO / BASELINE RESTART"
        )
        self.status_label.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "color: #d29922;"
            "padding: 6px;"
        )
        print(
            "[BCI] Capture interrupted -> analyzer remains visible; "
            "recovery will restart baseline in background"
        )

    @guarded_slot("baseline start")
    def handle_baseline_started(self, payload):
        """Promote to the main display as soon as real microphone audio exists.

        Script 57.7 preserves the 60-second room profile from the
        page-navigation critical path.  Calibration still runs for the full
        configured duration in the audio worker; only the splash-screen gate is
        removed.  Detection/recording remain worker-gated by ``self.calibrated``.
        """
        duration = float(
            payload.get("duration", STARTUP_CALIBRATION_SECONDS)
        )
        if duration < 30.0:
            return

        device_name = str(payload.get("device_name", "Microphone"))
        sample_rate = int(payload.get("sample_rate", 0) or 0)

        self.app_state.mark_calibrating(
            f"live microphone frames: {device_name} @ {sample_rate} Hz"
        )
        self._show_analyzer_page()

        self.status_label.setText(
            "STATUS: [ROOM BASELINE CALIBRATING] "
            f"{device_name} @ {sample_rate} Hz | "
            f"{duration:.0f}s profile running in background"
        )
        self.status_label.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "color: #58a6ff;"
            "padding: 6px;"
        )

        print(
            "[BCI] First live microphone block -> main display "
            f"({device_name} @ {sample_rate} Hz); "
            f"{duration:.0f}s baseline continues in background"
        )

    def _show_analyzer_page(self):
        """Perform and verify the one-way completed-baseline handoff."""
        if self.boot_in_progress or not self.analysis_started:
            return

        # Script 57.2: the analyzer's stack page is the adaptive-frame view,
        # not the analyzer canvas embedded inside that view's graphics scene.
        target = getattr(self, "adaptive_frame", None)
        if target is None:
            if self.page_stack.count() <= 1:
                raise RuntimeError("Analyzer frame is missing from page stack")
            target = self.page_stack.widget(1)

        self.page_stack.setCurrentWidget(target)

        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentIndex(0)

        # Force a clean top-level visibility transition.  The boot page is a
        # sibling of the adaptive analyzer frame, so it can no longer remain as
        # a stale QGraphicsProxyWidget backing-store image.
        target.show()
        self.analysis_page.show()
        self.page_stack.updateGeometry()
        self.page_stack.update()
        target.refresh_design_canvas()
        target.viewport().update()
        target.scene().invalidate(target.sceneRect())

    def _verify_analyzer_handoff(self):
        """Verify that no queued GUI work reversed a completed handoff."""
        if self.boot_in_progress or not self.analysis_started:
            return

        target = getattr(self, "adaptive_frame", None)
        if target is None and self.page_stack.count() > 1:
            target = self.page_stack.widget(1)

        if target is not None and self.page_stack.currentWidget() is not target:
            LOGGER.warning(
                "Boot handoff page mismatch after completion; "
                "restoring analyzer page"
            )
            self._show_analyzer_page()

    @guarded_slot("boot handoff")
    def handle_boot_complete(self, payload):
        """Commit worker-confirmed calibration without gating page visibility.

        Script 57.4 keeps this signal authoritative for *calibration readiness*,
        but no longer for access to the main display.  The analyzer page is
        entered on the first verified microphone block, so a delayed/missing
        completion signal can never strand the application on the splash page.
        """
        self.app_state.mark_ready(
            "worker-confirmed room baseline complete"
        )
        self._show_analyzer_page()

        noise_floor_db = float(
            payload.get("noise_floor_db", -120.0)
        )
        peak_freq = float(
            payload.get("baseline_profile_peak_freq", 0.0)
        )
        valid_seconds = float(
            payload.get("baseline_valid_seconds", 0.0)
        )

        # Boot-page presentation is now non-authoritative and hidden.
        self.boot_screen.finish_baseline()
        self.boot_screen.update_baseline(
            1.0,
            0.0,
            noise_floor_db,
            peak_freq,
            max(valid_seconds, BASELINE_MIN_VALID_SECONDS),
            "",
        )

        self.status_label.setText(
            "STATUS: [ROOM AUDIO PROFILE ESTABLISHED] "
            f"NOISE FLOOR: {noise_floor_db:.1f} dBFS | "
            f"AMBIENT PEAK: {peak_freq:.0f} Hz"
        )
        self.status_label.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
            "color: #3fb950;"
            "padding: 6px;"
        )

        # Verify after queued paint/probe callbacks from the same event turn.
        QtCore.QTimer.singleShot(0, self._verify_analyzer_handoff)
        QtCore.QTimer.singleShot(100, self._verify_analyzer_handoff)

        print(
            "[BCI] GUI handoff complete -> analyzer "
            f"(page={self.page_stack.currentIndex()})"
        )

    @guarded_slot("isolated display update")
    def handle_isolated_analysis(self, result):
        if result.get("reset"):
            self.isolated_widget.update_data(
                None,
                None,
                False,
                0.0,
                0.0,
                0.0,
                48000.0,
                calibrating=False,
            )
            self.classification_label.setText(
                "CLASSIFICATION: WAITING"
            )
            return

        if "error" in result:
            self.classification_label.setText(
                "CLASSIFICATION: ANALYSIS ERROR"
            )
            self.classification_label.setStyleSheet(
                "font-size: 13px;"
                "font-weight: bold;"
                "color: #f85149;"
                "padding: 5px 9px;"
                "border: 1px solid #30363d;"
                "border-radius: 4px;"
            )
            return

        isolated_spectrum_db = result.get(
            "spectrum_db"
        )
        sample_rate = float(
            result.get("sample_rate", 48000.0)
        )
        lock_low = float(
            result.get("lock_low", 0.0)
        )
        lock_high = float(
            result.get("lock_high", 0.0)
        )
        lock_center = float(
            result.get("lock_center", 0.0)
        )

        # This panel receives data ONLY from the isolated-analysis thread.
        # The main audio packet never paints over it while a lock is active.
        self.isolated_widget.update_data(
            isolated_spectrum_db,
            isolated_spectrum_db,
            True,
            lock_low,
            lock_high,
            lock_center,
            sample_rate,
            calibrating=False,
        )

        classification = str(
            result.get(
                "classification",
                "ANALYZING",
            )
        )
        confidence = float(
            result.get(
                "classification_confidence",
                0.0,
            )
        )

        if confidence > 0.0:
            class_text = (
                f"CLASSIFICATION: {classification} "
                f"({confidence * 100:.0f}%)"
            )
        else:
            class_text = (
                f"CLASSIFICATION: {classification}"
            )

        if "TALKING" in classification:
            class_color = "#3fb950"
        elif "MUSIC" in classification:
            class_color = "#d29922"
        elif "ANALYZING" in classification:
            class_color = "#58a6ff"
        else:
            class_color = "#8b949e"

        self.classification_label.setText(
            class_text
        )
        self.classification_label.setStyleSheet(
            f"font-size: 13px;"
            f"font-weight: bold;"
            f"color: {class_color};"
            f"padding: 5px 9px;"
            f"border: 1px solid #30363d;"
            f"border-radius: 4px;"
        )

    @guarded_slot("main spectrum update")
    def handle_audio_data(self, packet):
        spectrum_db = packet.get("spectrum_db")
        isolated_spectrum_db = packet.get(
            "isolated_spectrum_db"
        )
        rms_energy = float(packet.get("rms", 0.0))
        peak_freq = float(packet.get("peak_freq", 0.0))
        snr_db = float(packet.get("snr_db", 0.0))
        is_active = bool(packet.get("is_active", False))
        status_msg = str(packet.get("status", "MONITORING"))
        lock_low = float(packet.get("lock_low", 0.0))
        lock_high = float(packet.get("lock_high", 0.0))
        lock_center = float(packet.get("lock_center", 0.0))
        sample_rate = float(
            packet.get("sample_rate", 48000.0)
        )
        classification = str(
            packet.get("classification", "WAITING")
        )
        classification_confidence = float(
            packet.get("classification_confidence", 0.0)
        )
        calibration_progress = float(
            packet.get("calibration_progress", 1.0)
        )
        calibration_remaining = float(
            packet.get("calibration_remaining", 0.0)
        )
        noise_floor_db = float(
            packet.get("noise_floor_db", -120.0)
        )
        calibration_duration = float(
            packet.get("calibration_duration", 0.0)
        )
        baseline_profile_peak_freq = float(
            packet.get("baseline_profile_peak_freq", 0.0)
        )
        baseline_valid_seconds = float(
            packet.get("baseline_valid_seconds", 0.0)
        )
        baseline_warning = str(
            packet.get("baseline_warning", "")
        )
        lock_excess_db = float(
            packet.get("lock_excess_db", -120.0)
        )

        full_boot_baseline = (
            status_msg == "CALIBRATING"
            and calibration_duration >= 30.0
        )

        # Script 57.5: calibration packets remain worker-authoritative for
        # readiness/status, but page visibility is no longer coupled to the
        # 60-second baseline.  Once the first live microphone block has promoted
        # the UI, calibration continues on the analyzer page.
        if (
            full_boot_baseline
            and self.boot_in_progress
            and not self._main_display_entered
        ):
            if self.page_stack.currentWidget() is not self.boot_screen:
                self.page_stack.setCurrentWidget(
                    self.boot_screen
                )
            self.boot_screen.update_baseline(
                calibration_progress,
                calibration_remaining,
                noise_floor_db,
                baseline_profile_peak_freq,
                baseline_valid_seconds,
                baseline_warning,
            )

        if status_msg == "BASELINE_COMPLETE":
            status_text = (
                "STATUS: [ROOM AUDIO PROFILE ESTABLISHED] "
                f"NOISE FLOOR: {noise_floor_db:.1f} dBFS | "
                f"AMBIENT PEAK: {baseline_profile_peak_freq:.0f} Hz"
            )
            style = (
                "font-size: 14px;"
                "font-weight: bold;"
                "color: #3fb950;"
                "padding: 6px;"
            )

        elif status_msg == "CALIBRATING":
            calibration_name = (
                "60-SECOND AMBIENT BASELINE"
                if calibration_duration >= 30.0
                else "QUICK NOISE RECALIBRATION"
            )
            status_text = (
                f"STATUS: [{calibration_name}] "
                f"{calibration_progress * 100:5.1f}% | "
                f"{calibration_remaining:4.1f}s REMAINING | "
                f"RMS: {rms_energy:.6f}"
            )
            style = (
                "font-size: 13px;"
                "color: #d29922;"
                "padding: 4px;"
            )

        elif is_active:
            status_text = (
                f"STATUS: [{status_msg}] "
                f"PEAK: {peak_freq:.1f} Hz | "
                f"LOCK: {lock_low:.0f}–{lock_high:.0f} Hz | "
                f"LOCK LEVEL: +{max(0.0, lock_excess_db):.1f} dB | "
                f"SNR: {snr_db:.2f} dB | "
                "[RECORDING LOCKED SIGNAL]"
            )
            style = (
                "font-size: 13px;"
                "font-weight: bold;"
                "color: #f85149;"
                "padding: 4px;"
            )

        else:
            status_text = (
                f"STATUS: [{status_msg}] "
                f"FREQ: {peak_freq:.1f} Hz | "
                f"RMS: {rms_energy:.6f} | "
                f"SNR: {snr_db:.2f} dB | "
                f"BASELINE: {noise_floor_db:.1f} dBFS"
            )
            style = (
                "font-size: 13px;"
                "color: #8b949e;"
                "padding: 4px;"
            )

        if status_text != self._last_status_text:
            self.status_label.setText(status_text)
            self._last_status_text = status_text

        if style != self._last_status_style:
            self.status_label.setStyleSheet(style)
            self._last_status_style = style

        self.spectrum_widget.update_data(
            spectrum_db,
            None,
            is_active,
            lock_low,
            lock_high,
            lock_center,
            sample_rate,
            calibrating=(status_msg == "CALIBRATING"),
        )

        # The isolated spectrum has its own analysis QThread. Do not update
        # that widget from broad-spectrum packets while a lock is active.
        if self._last_signal_active and not is_active:
            self.isolated_analysis_thread.reset_analysis()

        if not is_active and not self._last_signal_active:
            if status_msg in (
                "CALIBRATING",
                "BASELINE_COMPLETE",
            ):
                self.isolated_widget.update_data(
                    None,
                    None,
                    False,
                    0.0,
                    0.0,
                    0.0,
                    sample_rate,
                    calibrating=(
                        status_msg == "CALIBRATING"
                    ),
                )

        self._last_signal_active = is_active

    # --------------------------------------------------------------------------
    # Shutdown
    # --------------------------------------------------------------------------

    def closeEvent(self, event):
        print(
            "[BCI][SHUTDOWN] closeEvent ENTER",
            flush=True,
        )

        self.app_state.mark_stopping("Qt closeEvent")

        print(
            "[BCI][SHUTDOWN] application state marked stopping",
            flush=True,
        )

        # Stop external device discovery first so no queued probe result can
        # arrive while widgets and audio workers are being torn down.
        if hasattr(self, "audio_boundary_thread"):
            print(
                "[BCI][SHUTDOWN] stopping audio boundary",
                flush=True,
            )

            self.audio_boundary_thread.stop()

            print(
                "[BCI][SHUTDOWN] audio boundary stop returned "
                f"running={self.audio_boundary_thread.isRunning()}",
                flush=True,
            )

        self.stop_playback(wait=True)

        if hasattr(self, "live_broadcaster"):
            self.stop_go_live()

        if hasattr(self, "stop_mastering_playback"):
            self.stop_mastering_playback(wait=True)

        if (
            getattr(self, "mastering_render_thread", None) is not None
            and self.mastering_render_thread.isRunning()
        ):
            self.mastering_render_thread.requestInterruption()
            self.mastering_render_thread.wait(2000)

        # Stop capture first so no more isolated blocks can be published.
        self.audio_thread.stop()
        self.isolated_analysis_thread.stop()
        self.postprocess_thread.stop()
        self.transcription_thread.stop()

        print(
            "[BCI][SHUTDOWN] worker shutdown sequence complete",
            flush=True,
        )

        event.accept()

        print(
            "[BCI][SHUTDOWN] closeEvent EXIT accepted",
            flush=True,
        )

    @staticmethod
    def _paired_recording_path(path):
        path = Path(path)

        if path.stem.endswith("_raw"):
            return path.with_name(
                path.stem[:-4] + "_isolated.wav"
            )

        if path.stem.endswith("_isolated"):
            return path.with_name(
                path.stem[:-9] + "_raw.wav"
            )

        return None

    @staticmethod
    def _recording_delete_sidecars(path):
        path = Path(path)

        return [
            path.with_suffix(".txt"),
            path.with_suffix(
                ".enhancement.json"
            ),
            path.with_suffix(
                ".mastering.json"
            ),
        ]

    def _validate_recording_delete_target(self, path):
        root = Path(LOG_DIR).resolve()
        candidate = Path(path).resolve()

        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                "Refusing to delete a file outside the BCI recordings directory."
            ) from exc

        return candidate

    def _playback_uses_any_path(self, paths):
        thread = self.playback_thread

        if thread is None:
            return False

        try:
            playing = Path(
                thread.filename
            ).resolve()
        except Exception:
            return False

        return playing in {
            Path(path).resolve()
            for path in paths
        }

    @guarded_slot("delete recording")
    def delete_selected_recording(self, _checked=False):
        selected_paths = self.selected_recording_paths()

        if not selected_paths:
            self.now_playing_label.setText(
                "Select one or more recordings to delete."
            )
            return

        safe_selected = [
            self._validate_recording_delete_target(
                path
            )
            for path in selected_paths
        ]

        # Multi-selection is straightforward: delete exactly what is selected.
        # Single selection preserves the convenient paired RAW/ISOLATED option.
        if len(safe_selected) > 1:
            box = QtWidgets.QMessageBox(self)
            box.setIcon(
                QtWidgets.QMessageBox.Icon.Warning
            )
            box.setWindowTitle(
                "Delete BCI Recordings"
            )
            box.setText(
                f"Delete {len(safe_selected)} selected recordings?"
            )
            box.setInformativeText(
                "This permanently removes all selected WAV files "
                "and their transcript sidecars."
            )

            delete_button = box.addButton(
                "Delete Selected",
                QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
            )
            cancel_button = box.addButton(
                QtWidgets.QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(
                cancel_button
            )

            box.exec()

            if box.clickedButton() is not delete_button:
                return

            targets = safe_selected

        else:
            selected = safe_selected[0]

            paired = self._paired_recording_path(
                selected
            )

            if (
                paired is not None
                and paired.exists()
            ):
                paired = self._validate_recording_delete_target(
                    paired
                )
            else:
                paired = None

            box = QtWidgets.QMessageBox(self)
            box.setIcon(
                QtWidgets.QMessageBox.Icon.Warning
            )
            box.setWindowTitle(
                "Delete BCI Recording"
            )
            box.setText(
                "Delete this recording?"
            )
            box.setInformativeText(
                selected.name
                + (
                    "\n\nA matching RAW/ISOLATED recording is also available."
                    if paired is not None
                    else ""
                )
                + "\n\nThis permanently removes the selected WAV "
                "and its transcript sidecar."
            )

            delete_selected_button = box.addButton(
                "Delete Selected",
                QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
            )

            delete_pair_button = None

            if paired is not None:
                delete_pair_button = box.addButton(
                    "Delete RAW + ISOLATED",
                    QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
                )

            cancel_button = box.addButton(
                QtWidgets.QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(
                cancel_button
            )

            box.exec()
            clicked = box.clickedButton()

            if clicked is cancel_button:
                return

            targets = [selected]

            if (
                delete_pair_button is not None
                and clicked is delete_pair_button
                and paired is not None
            ):
                targets.append(
                    paired
                )
            elif clicked is not delete_selected_button:
                return

        self.postprocess_thread.cancel_paths(
            targets
        )

        if not self.postprocess_thread.wait_for_paths_idle(
            targets,
            timeout=2.0,
        ):
            LOGGER.warning(
                "Timed out waiting for active reconstruction before delete"
            )

        self.transcription_thread.cancel_paths(
            targets
        )

        if self._playback_uses_any_path(
            targets
        ):
            self.stop_playback(
                wait=True
            )
            self.playback_thread = None

        delete_paths = []

        for target in targets:
            safe_target = (
                self._validate_recording_delete_target(
                    target
                )
            )

            delete_paths.append(
                safe_target
            )

            for sidecar in (
                self._recording_delete_sidecars(
                    safe_target
                )
            ):
                if sidecar.exists():
                    delete_paths.append(
                        self._validate_recording_delete_target(
                            sidecar
                        )
                    )

        unique_paths = []
        seen = set()

        for path in delete_paths:
            key = str(path)

            if key in seen:
                continue

            seen.add(key)
            unique_paths.append(
                path
            )

        deleted_names = []

        for path in unique_paths:
            if not path.exists():
                continue

            try:
                path.unlink()
                deleted_names.append(
                    path.name
                )
            except Exception as exc:
                report_exception(
                    f"deleting recording {path}",
                    exc,
                )
                raise RuntimeError(
                    f"Could not delete {path.name}: {exc}"
                ) from exc

        self.recordings_table.clearSelection()
        self.refresh_recordings()

        self.playback_progress.setValue(
            0
        )
        self.playback_time_label.setText(
            "00:00 / 00:00"
        )
        self.playback_transcript.clear()

        self.play_button.setEnabled(
            True
        )
        self.pause_button.setEnabled(
            False
        )
        self.stop_button.setEnabled(
            False
        )
        self.delete_recording_button.setEnabled(
            False
        )

        if deleted_names:
            self.now_playing_label.setText(
                f"DELETED: {len(deleted_names)} file"
                + (
                    ""
                    if len(deleted_names) == 1
                    else "s"
                )
            )

            LOGGER.info(
                "Deleted recording files: %s",
                ", ".join(
                    deleted_names
                ),
            )
        else:
            self.now_playing_label.setText(
                "Nothing was deleted."
            )

    def selected_recording_paths(self):
        selection_model = self.recordings_table.selectionModel()
        if selection_model is None:
            return []

        indexes = selection_model.selectedRows(5)
        paths = []
        seen = set()

        for index in indexes:
            item = self.recordings_table.item(index.row(), 5)
            if item is None:
                continue
            stored_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not stored_path:
                continue
            path = Path(str(stored_path))
            if not path.exists():
                continue
            try:
                key = str(path.resolve())
            except Exception:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
        return paths

    def select_all_recordings(self):
        if self.recordings_table.rowCount() <= 0:
            self.now_playing_label.setText("No recordings to select.")
            return

        previous_block_state = self.recordings_table.blockSignals(True)
        try:
            self.recordings_table.selectAll()
            model = self.recordings_table.model()
            selection_model = self.recordings_table.selectionModel()
            if model is not None and selection_model is not None and self.recordings_table.rowCount() > 0:
                selection_model.setCurrentIndex(
                    model.index(0, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        finally:
            self.recordings_table.blockSignals(previous_block_state)

        self.update_recording_selection()

    def _recording_path_for_row(self, row, require_exists=True):
        try:
            row = int(row)
        except (TypeError, ValueError):
            return None

        if row < 0 or row >= self.recordings_table.rowCount():
            return None

        item = self.recordings_table.item(row, 5)
        if item is None:
            return None

        stored_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not stored_path:
            return None

        path = Path(str(stored_path))
        if require_exists and not path.exists():
            return None
        return path

    def _current_recording_path(self):
        current_row = self.recordings_table.currentRow()
        if current_row < 0:
            return None

        current_path = self._recording_path_for_row(current_row)
        if current_path is None:
            return None

        selected_keys = {str(path.resolve()) for path in self.selected_recording_paths()}
        try:
            current_key = str(current_path.resolve())
        except Exception:
            return None
        return current_path if current_key in selected_keys else None

    def play_recording_item(self, item):
        if item is None:
            return

        path = self._recording_path_for_row(item.row())
        if path is None:
            self.now_playing_label.setText("The selected recording is no longer available.")
            return

        selection_model = self.recordings_table.selectionModel()
        if selection_model is not None:
            index = self.recordings_table.model().index(item.row(), 0)
            selection_model.setCurrentIndex(index, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)

        self.play_selected_recording()


# ==============================================================================
# Main
# ==============================================================================



def main():
    _bci_mp.freeze_support()
    install_global_exception_hook()

    LOGGER.info(
        "Starting Beacon Computing Initiative build %s",
        BCI_BUILD,
    )

    print(
        f"[BCI] Project version {BCI_PROJECT_VERSION}"
    )
    print(
        f"[BCI] Script revision {BCI_SCRIPT_REVISION} (tally {BCI_SCRIPT_TALLY})"
    )
    print(
        f"[BCI] Engineering build {BCI_BUILD}"
    )
    print(
        f"[BCI] GUI framework: PyQt6 {QtCore.PYQT_VERSION_STR} "
        f"/ Qt {QtCore.QT_VERSION_STR}"
    )
    print(
        "[BCI] Room baseline: "
        f"{STARTUP_CALIBRATION_SECONDS:.1f} seconds in background"
    )
    print(
        "[BCI] Startup gate: first verified live microphone block"
    )
    print(
        "[BCI] Main display: no longer blocked by baseline completion"
    )
    print(
        "[BCI] UI scheduler: 20 FPS visual / 12.5 Hz spectrum telemetry"
    )
    print(
        "[BCI] Capture transport: thread-safe circular audio ring buffer"
    )
    print(
        f"[BCI] Hardware boundary: protocol v{BOUNDARY_PROTOCOL_VERSION}; "
        "PortAudio input calls are process-isolated"
    )
    print(
        "[BCI] Telemetry: SQLite WAL + compatibility text log"
    )
    print(
        f"[BCI] Telemetry DB: {TELEMETRY_DB}"
    )
    print(
        f"[BCI] Short-event log: {SHORT_EVENT_LOG}"
    )
    print(
        f"[BCI] Recording keep rule: "
        f"{MIN_SAVED_LOCK_SECONDS:.1f}s confirmed lock minimum"
    )
    print(
        f"[BCI] Go Live: opt-in HTTP/MP3 on "
        f"{LIVE_STREAM_HOST}:{LIVE_STREAM_PORT}"
    )
    print(
        "[BCI] Reconstruction: room-profile + STFT/Wiener + harmonic protection"
    )
    print(
        "[BCI] Finalization: clarity mastering + -14 LUFS loudness + -1 dBTP"
    )
    print(
        "[BCI] Local transcription backends: "
        "openai-whisper -> faster-whisper -> whisper.cpp"
    )
    print(
        "[BCI] Audio routing: isolated PortAudio process + supervised IPC boundary"
    )
    print(
        "[BCI] Control plane: explicit application/audio state machines; "
        "legacy boolean collisions removed"
    )
    print(
        f"[BCI] OpenAI Whisper primary: {OPENAI_WHISPER_MODEL} "
        f"({OPENAI_WHISPER_DEVICE})"
    )
    print(
        f"[BCI] Faster-Whisper fallback: {FASTER_WHISPER_MODEL}"
    )

    try:
        TELEMETRY_DAEMON.start()

        TELEMETRY_DAEMON.log_event(
            "APPLICATION_START",
            json.dumps(
                {
                    "project_version": BCI_PROJECT_VERSION,
                    "script_tally": BCI_SCRIPT_TALLY,
                    "build": BCI_BUILD,
                    "pid": os.getpid(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

    except Exception as exc:
        report_exception(
            "SQLite telemetry startup",
            exc,
        )
        print(
            f"[BCI] SQLite telemetry unavailable: {exc}"
        )

    app = QtWidgets.QApplication(
        sys.argv
    )

    install_error_bridge()
    prune_old_recordings()

    window = BCIWindow()
    window.show()

    # ------------------------------------------------------------------
    # BCI QA-only graceful shutdown hook
    #
    # This is disabled during normal operation.  The autonomous
    # acceptance harness may set BCI_QA_AUTOCLOSE_MS so that the frozen
    # application closes through Qt's normal closeEvent() path instead
    # of being externally terminated.
    # ------------------------------------------------------------------
    try:
        qa_autoclose_ms = int(
            os.environ.get(
                "BCI_QA_AUTOCLOSE_MS",
                "0",
            )
            or 0
        )
    except (TypeError, ValueError):
        qa_autoclose_ms = 0

    if qa_autoclose_ms > 0:
        print(
            f"[BCI][QA] Graceful Qt close scheduled "
            f"in {qa_autoclose_ms} ms",
            flush=True,
        )

        def _bci_qa_graceful_close():
            print(
                "[BCI][QA] autoclose timer FIRED",
                flush=True,
            )

            result = window.close()

            print(
                f"[BCI][QA] window.close() returned {result}",
                flush=True,
            )

        QtCore.QTimer.singleShot(
            qa_autoclose_ms,
            _bci_qa_graceful_close,
        )

    exit_code = 0

    try:
        exit_code = app.exec()

    finally:
        try:
            TELEMETRY_DAEMON.log_event(
                "APPLICATION_STOP",
                json.dumps(
                    {
                        "project_version": BCI_PROJECT_VERSION,
                        "script_tally": BCI_SCRIPT_TALLY,
                        "build": BCI_BUILD,
                        "dropped_events": (
                            TELEMETRY_DAEMON.dropped_events()
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            TELEMETRY_DAEMON.stop()

        except Exception as exc:
            report_exception(
                "SQLite telemetry shutdown",
                exc,
            )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
