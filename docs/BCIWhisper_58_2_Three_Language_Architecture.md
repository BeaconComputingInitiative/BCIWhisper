# BCIWhisper Script 58.2 — Three-Language Modular Architecture

**Beacon Computing Initiative**  
**Project version:** v6.0  
**Script revision:** 58.2  
**Engineering build:** `2026.10.22-r6.35.2`  
**Developer Seal:** `CJB-DEV-2026`

## Architecture

BCIWhisper 58.2 formalizes three implementation languages with non-overlapping responsibilities:

```text
QML / Qt Quick
      │
      ▼
PySide6 presentation bridge
      │
      ▼
Python application services
      │
      ▼
pybind11 ABI boundary
      │
      ▼
C++20 native primitives
      │
      ▼
isolated audio hardware boundary
```

### QML / Qt Quick

Owns presentation, controls, animation, view composition, and operator feedback.

It does not own PortAudio, microphone discovery, DSP implementation state, SQLite, Whisper models, or broadcast processes.

### Python

Owns orchestration, services, lifecycle policy, fallback behavior, transcription coordination, telemetry coordination, and the Qt-facing bridge.

Python is the policy layer, not the timing-critical sample loop.

### C++20

Owns deterministic low-latency primitives as they are migrated from the historical Python implementation.

58.2 introduces:

- native audio metrics;
- a bounded native ring buffer;
- a pybind11 ABI boundary;
- explicit GIL release around native sample processing;
- numerical parity tests against the Python/NumPy fallback.

## Resource ownership

One subsystem owns one resource.

The 57.10 isolated PortAudio process remains the behavioral reference for hardware ownership. 58.2 does not introduce a second PortAudio owner and does not load the PyQt6 57.10 window into the PySide6 QML process.

## Fallback policy

The Python adapter provides a NumPy implementation for supported primitives if the C++ extension is unavailable.

The application therefore remains diagnosable in source mode, but a 58.2 packaged acceptance build is considered native-complete if and only if:

1. the C++20 extension builds;
2. the native numerical tests pass;
3. the ring-buffer tests pass;
4. QML reports `loaded=True`;
5. the packaged executable also reports `loaded=True`;
6. the native self-test reports `PASS`.

## Transcription

Transcription remains a Python service because model scheduling, backend fallback, model configuration, and result persistence are orchestration responsibilities.

Backend order remains:

```text
OpenAI Whisper
      ↓
Faster-Whisper
      ↓
whisper.cpp
```

Whisper model execution does not run on the QML GUI thread.

## Migration policy

58.x continues to extract deterministic hot-path components into C++ only when doing so does not violate the verified 57.10 ownership and lifecycle behavior.

No subsystem is considered migrated merely because a new implementation exists. Migration requires behavioral parity, explicit ownership, regression testing, and a clean rollback path.
