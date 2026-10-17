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

    "ui": 6,
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
    "ui",
)

RUNTIME_OWNERSHIP = {
    "common": "shared stateless helpers only",
    "config": "paths, environment, immutable runtime configuration",
    "core": "application lifecycle, contracts, orchestration primitives",
    "telemetry": "logs, SQLite, structured health/events",
    "audio": "microphone discovery, PortAudio ownership, PCM transport",
    "dsp": "filtering, baseline, spectrum, detection, reconstruction, mastering math",
    "recording": "event capture lifecycle, retention, WAV/file library",
    "transcription": "OpenAI Whisper, Faster-Whisper, whisper.cpp",
    "broadcast": "BroadcastBus, Go-Live state, publisher, Bun gateway process/client",
    "ui": "PyQt6 presentation and operator actions only",
}
