<!-- BEACON COMPUTING INITIATIVE -->
<!-- BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1 -->
<!-- Developer Seal: CJB-DEV-2026 -->
<!-- Canonical Payload SHA-256: a18cc51546f55439ad7611723ca095b42eed56bc22e145811d6f7d8c967dd620 -->
<!-- Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged. -->

# BCIWhisper Script 58.1 — QML Modular Foundation

**Project version:** v6.0  
**Script revision:** 58.1  
**Engineering build:** `2026.10.22-r6.35.1`  
**Developer:** Chance Joaquin Boone  
**Developer Seal:** `CJB-DEV-2026`

## Purpose

Script 58.1 begins the post-57.10 desktop architecture migration. The frozen 57.10 runtime remains the behavioral baseline. 58.1 is additive: it introduces a QML / Qt Quick presentation shell, a PySide6 bridge, and UI-independent application services without replacing the verified capture pipeline.

## Architectural rule

One subsystem owns one resource.

```text
QML / Qt Quick
      │
      ▼
PySide6 bridge
      │
      ▼
Application services
      │
      ├── audio
      ├── DSP
      ├── recording
      ├── mastering
      ├── transcription
      ├── broadcast
      └── telemetry
```

QML may display state and issue operator commands. It may not directly enumerate microphones, open PortAudio, manipulate DSP state, write SQLite, load Whisper models, spawn the broadcast gateway, or own recording files.

## 57.10 compatibility boundary

The 57.10 processing sequence remains authoritative during migration:

```text
Microphone / input
      ↓
PortAudio hardware process
      ↓
ownership / selection / hotplug / stream lifecycle
      ↓
supervised IPC
      ↓
application capture ring
      ↓
DSP / filtering
      ↓
baseline / detection
      ↓
recording
      ↓
reconstruction
      ↓
mastering
      ↓
manual transcription
```

A subsystem is considered migrated if and only if its new service-boundary behavior matches the frozen baseline contract for lifecycle, output, and error handling.

## Transcription

58.1 introduces `bciwhisper.services.transcription.TranscriptionService`.

Default backend preference remains:

```text
OpenAI Whisper
      ↓ failure/unavailable
Faster-Whisper
      ↓ failure/unavailable
whisper.cpp
```

The standalone 57.10 release remains optimized around Faster-Whisper / CTranslate2 with external `small.en` model weights. 58.1 does not bundle model weights.

The service is `READY` if and only if a backend has been selected. The invariant is checked in code after discovery and fallback.

## Threading

The QML GUI thread owns presentation only. Transcription is launched with `QThreadPool` through the PySide6 bridge so model loading and decoding do not block the QML event loop.

## New files

```text
bciwhisper/services/
    __init__.py
    transcription.py

bciwhisper/ui_qml/
    __init__.py
    bridge.py
    main.py
    qml/
        Main.qml
        components/
            PanelCard.qml

requirements-qml-desktop.txt
run-bciwhisper-qml.sh
tests/test_transcription_service.py
```

## Migration policy

1. Preserve the 57.10 release and tag.
2. Add a service contract before moving implementation ownership.
3. Validate the extracted service independently.
4. Expose only stable properties, models, signals, and commands to QML.
5. Move the next subsystem only after the prior boundary is stable.
6. Do not mix QML presentation code with PortAudio, DSP, SQLite, Whisper model loading, or gateway process ownership.

## Development launch

Use a dedicated environment during the migration so the frozen PyQt6 release toolchain remains isolated.

```bash
python3 -m venv .venv-qml
source .venv-qml/bin/activate
python -m pip install -r requirements-qml-desktop.txt
bash ./run-bciwhisper-qml.sh
```

## Validation scope

The 58.1 source foundation can be statically validated for imports, service fallback, and QML bridge ownership. Physical microphone behavior, recording parity, and final QML visual acceptance remain target-host checks because those behaviors continue to belong to the 57.10 engine until their individual service migrations are completed.
