# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

# Lower number = lower architectural layer.
# A module may depend on its own layer or any lower-numbered layer.
MODULE_LAYERS = {
    "common": 0,
    "config": 0,

    "core": 1,
    "telemetry": 1,

    "audio": 2,
    "native": 3,
    "dsp": 4,
    "recording": 5,

    "transcription": 6,
    "broadcast": 6,

    "services": 7,

    "ui": 8,
    "ui_qml": 8,
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
    "transcription",
    "broadcast",
    "services",
    "ui_qml",
)

RUNTIME_OWNERSHIP = {
    "common": "shared stateless helpers only",
    "config": "paths, environment, immutable runtime configuration",
    "core": "application lifecycle, contracts, orchestration primitives",
    "telemetry": "logs, SQLite, structured health/events",
    "audio": "microphone discovery, isolated PortAudio ownership, PCM transport",
    "native": "C++20 deterministic low-latency primitives exposed through pybind11",
    "dsp": "filtering, baseline, spectrum, detection, reconstruction, mastering math",
    "recording": "event capture lifecycle, retention, WAV/file library",
    "transcription": "OpenAI Whisper, Faster-Whisper, whisper.cpp backend adapters",
    "broadcast": "BroadcastBus, Go-Live state, publisher, gateway process/client",
    "services": "UI-independent application use-cases and subsystem coordination",
    "ui": "57.10 PyQt6 presentation compatibility boundary",
    "ui_qml": "58.x QML / Qt Quick presentation via PySide6 only",
}

LANGUAGE_ARCHITECTURE = {
    "qml": "presentation, controls, animation, visualization",
    "python": "application orchestration, services, lifecycle, transcription, telemetry",
    "cpp20": "timing-sensitive audio/DSP primitives with deterministic ownership",
}
