# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

MODULE_LAYERS = {
    "common": 0,
    "config": 0,
    "core": 1,
    "telemetry": 1,
    "audio": 2,
    "native": 3,
    "dsp": 4,
    "recording": 5,
    "processing": 6,
    "playback": 6,
    "transcription": 6,
    "broadcast": 6,
    "settings": 6,
    "services": 7,
    "app": 8,
    "ui_qml": 9,
}

STARTUP_SEQUENCE = (
    "common",
    "config",
    "core",
    "telemetry",
    "audio",
    "native",
    "dsp",
    "recording",
    "processing",
    "playback",
    "transcription",
    "broadcast",
    "settings",
    "services",
    "app",
    "ui_qml",
)

RUNTIME_OWNERSHIP = {
    "common": "shared stateless helpers only",
    "config": "paths, environment, immutable runtime configuration",
    "core": "application lifecycle and typed state machines",
    "telemetry": "SQLite WAL event persistence",
    "audio": "isolated PortAudio process supervision and PCM ingress",
    "native": "C++20 realtime primitives exposed through pybind11",
    "dsp": "filtering, baseline, spectrum, detection and signal state",
    "recording": "RAW/isolated capture lifecycle and 15-second retention policy",
    "processing": "offline reconstruction and mastering",
    "playback": "output-only playback lifecycle",
    "transcription": "local Whisper backend discovery, scheduling and fallback",
    "broadcast": "Go Live publisher and Bun gateway lifecycle",
    "settings": "persistent operator/runtime configuration",
    "services": "cross-domain application service facades",
    "app": "single runtime authority and subsystem orchestration",
    "ui_qml": "QML presentation through PySide6 bridge only",
}

LANGUAGE_ARCHITECTURE = {
    "qml": "presentation, controls, animation and visualization only",
    "python": "application state, services, lifecycle, persistence and model orchestration",
    "cpp20": "timing-sensitive audio/DSP primitives with deterministic ownership",
}

PROHIBITED_RUNTIME_DEPENDENCIES = (
    "BCIWhisper.py",
    "PyQt5",
    "PyQt6",
)
