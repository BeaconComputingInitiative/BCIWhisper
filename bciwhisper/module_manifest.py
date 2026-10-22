# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 24bac0bc7b64ed68fb2dcf1e78aad8e7a6162ffe9cddedb791fe897920e8ebec
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

# Lower number = lower architectural layer.
# A module may depend on its own layer or any lower-numbered layer.
MODULE_LAYERS = {
    "common": 0,
    "config": 0,

    "core": 1,
    "telemetry": 1,

    "audio": 2,

    "dsp": 3,

    "recording": 4,

    "transcription": 5,
    "broadcast": 5,

    "services": 6,

    "ui": 7,
    "ui_qml": 7,
}

STARTUP_SEQUENCE = (
    "common",
    "config",
    "core",
    "telemetry",
    "audio",
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
    "audio": "microphone discovery, PortAudio ownership, PCM transport",
    "dsp": "filtering, baseline, spectrum, detection, reconstruction, mastering math",
    "recording": "event capture lifecycle, retention, WAV/file library",
    "transcription": "OpenAI Whisper, Faster-Whisper, whisper.cpp backend adapters",
    "broadcast": "BroadcastBus, Go-Live state, publisher, Bun gateway process/client",
    "services": "UI-independent application use-cases and subsystem coordination",
    "ui": "57.10 PyQt6 presentation compatibility boundary",
    "ui_qml": "Script 58.1 QML / Qt Quick presentation via PySide6 only",
}
