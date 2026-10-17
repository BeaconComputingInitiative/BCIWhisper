# BCIWhisper

<p align="center">
  <img src="assets/bciwhisper.png" alt="BCIWhisper logo" width="220">
</p>

<p align="center">
  <strong>Beacon Computing Initiative</strong><br>
  Audio analysis, recording, reconstruction, mastering, transcription, telemetry, and live-broadcast tooling.
</p>

---

## Overview

**BCIWhisper** is a desktop audio-analysis application developed by the **Beacon Computing Initiative (BCI)**. It is designed around a supervised, process-isolated audio pipeline that separates hardware capture from the GUI and signal-processing layers, allowing device faults and native audio failures to be contained rather than propagated through the entire application.

The current public release is:

- **Project version:** v6.0
- **Script revision:** 57.10
- **Script tally:** 57
- **Engineering build:** `2026.10.17-r6.34.10`
- **Current release platforms:** Linux x86_64, Windows x86_64, macOS ARM64
- **GUI framework:** PyQt6 / Qt 6
- **Developer seal:** `CJB-DEV-2026`

BCIWhisper v6.0 / Script 57.10 is available for Linux x86_64, Windows x86_64, and macOS ARM64 / Apple Silicon.

---

## Core Principles

BCI work follows five operating principles:

1. **Observe accurately**
2. **Preserve faithfully**
3. **Analyze transparently**
4. **Communicate securely**
5. **Act deliberately**

These principles are intended to guide the design of the software, its diagnostics, its data-handling behavior, and its release process.

---

## Architecture

BCIWhisper uses a layered audio architecture:

```text
MICROPHONE / INPUT DEVICE
        │
        ▼
PortAudio hardware process
        │
        ▼
Device ownership / selection / hotplug / stream lifecycle
        │
        ▼
Supervised IPC boundary
        │
        ▼
Application capture ring buffer
        │
        ▼
DSP / filtering
        │
        ▼
Baseline analysis / detection
        │
        ▼
Recording
        │
        ▼
Reconstruction
        │
        ▼
Mastering
        │
        ▼
Manual transcription
```

### Process-isolated audio boundary

PortAudio hardware access is isolated behind `bci_audio/boundary.py`.

The boundary is responsible for:

- hardware discovery
- input stream ownership
- input-device selection
- hotplug-sensitive lifecycle behavior
- stream startup and shutdown
- process supervision
- IPC between native audio capture and the application

This design prevents the Qt GUI and DSP pipeline from directly owning PortAudio device enumeration or capture calls.

### Explicit lifecycle state

Application and audio-runtime lifecycle behavior is implemented through explicit state machines in:

```text
bci_core/state.py
```

This separates application state from audio state and reduces reliance on loosely coupled boolean flags.

---

## Major Features

### Live audio monitoring

BCIWhisper continuously analyzes microphone input while keeping capture and GUI work separated.

The current presentation scheduler targets:

- approximately **20 FPS** for visual presentation
- approximately **12.5 Hz** for spectrum telemetry
- lower-rate presentation updates during calibration

DSP and capture continue independently from GUI repaint cadence.

### Baseline calibration

BCIWhisper performs a startup room baseline before using the measured environment for signal analysis.

Current baseline configuration:

```text
Startup baseline: 60 seconds
Minimum valid baseline: 10 seconds
```

The main interface is not blocked while the full baseline continues in the background.

### Adaptive detection and locking

Detection begins inside the configured analysis band. Once an event is confirmed, BCIWhisper can adaptively follow the spectral region containing the event's dominant energy.

Current retention policy requires:

```text
15 seconds of confirmed lock
```

before a completed recording is retained.

Shorter detections are discarded as recordings and may instead be represented through lightweight event history.

### Circular capture buffer

Audio capture is transported through a thread-safe circular ring buffer, keeping the hardware capture path decoupled from downstream analysis.

### Recording

Recordings are streamed to disk rather than accumulated entirely in memory.

BCIWhisper preserves the raw recording as the primary source material.

### Reconstruction

Offline reconstruction includes mechanisms for:

- room-profile-aware processing
- STFT analysis/reconstruction
- Wiener-style spectral suppression
- harmonic protection
- hum rejection
- bounded chunk processing
- conservative dynamics

The reconstruction pipeline is designed to preserve the original RAW file while producing derived material separately.

### Mastering

The finalization pipeline includes:

- adaptive clarity processing
- mud reduction
- presence enhancement
- air-band enhancement
- de-essing
- loudness normalization
- peak protection

Current mastering targets:

```text
Integrated loudness: -14 LUFS
True-peak ceiling:   -1 dBTP
```

### Manual transcription

Transcription is deliberately **manual**.

BCIWhisper does not automatically transcribe recordings as part of capture, reconstruction, or mastering.

The runtime backend preference is:

```text
OpenAI Whisper
      ↓
Faster-Whisper / CTranslate2
      ↓
whisper.cpp
```

The standalone release is designed around Faster-Whisper / CTranslate2 as the bundled native CPU transcription path. Large Whisper models are stored outside the executable package.

#### Download the transcription model

BCIWhisper's standalone transcription path uses the CTranslate2-format **Faster-Whisper `small.en`** model. The model is distributed separately from the application package.

Official model repository:

https://huggingface.co/Systran/faster-whisper-small.en

The complete model repository should be downloaded, not only `model.bin`, because Faster-Whisper also needs the accompanying configuration and tokenizer files.

With the Hugging Face CLI:

```bash
hf download Systran/faster-whisper-small.en \
  --local-dir faster-whisper-small.en
```

BCIWhisper can then be pointed at that directory with:

```text
BCI_FASTER_WHISPER_MODEL=/path/to/faster-whisper-small.en
```

For packaged installs, the default model directory is inside the platform-specific BCIWhisper data directory:

```text
Linux:
~/.local/share/BCIWhisper/models/faster-whisper-small.en

Windows:
%LOCALAPPDATA%\BCIWhisper\models\faster-whisper-small.en

macOS:
~/Library/Application Support/BCIWhisper/models/faster-whisper-small.en
```

The model is approximately **486 MB** on Hugging Face and is licensed separately under its upstream model license.

### Recording library

The application contains dedicated interfaces for:

```text
MONITOR
RECORDINGS
TRANSCRIPTS
MASTERING
```

RAW and isolated files may be represented as a single logical recording in the interface while remaining distinct physical files on disk.

### Go Live

BCIWhisper contains an opt-in live HTTP/MP3 streaming path.

Default configuration:

```text
Host:    0.0.0.0
Port:    8765
Bitrate: 96 kbps
```

The service is not intended to bind until the user explicitly starts live operation, and it is stopped when live mode is stopped or the application exits.

Environment overrides:

```text
BCI_LIVE_HOST
BCI_LIVE_PORT
BCI_LIVE_BITRATE_KBPS
BCI_LIVE_PUBLIC_URL
```

---

## Telemetry and diagnostics

BCIWhisper maintains local diagnostic and telemetry data.

The current telemetry system uses:

- SQLite
- WAL mode
- compatibility text logging
- short-event JSONL logging
- rotating error logs

Typical runtime data includes:

```text
bci_telemetry.db
bci_telemetry.log
bci_short_events.jsonl
bci_error.log
bci_audio_logs/
```

Telemetry is local application data and is separate from the immutable packaged application files.

---

## Runtime data locations

`BCI_DATA_DIR` has the highest priority and can be used to override the application data root.

### Linux

```text
$XDG_DATA_HOME/BCIWhisper
```

or, when `XDG_DATA_HOME` is not set:

```text
~/.local/share/BCIWhisper
```

### Windows

```text
%LOCALAPPDATA%\BCIWhisper
```

with an `APPDATA` / user-profile fallback.

### macOS

```text
~/Library/Application Support/BCIWhisper
```

### Source mode

When running directly from source rather than a frozen application, BCIWhisper preserves the historical project-local data layout unless `BCI_DATA_DIR` is explicitly supplied.

---

## Repository layout

```text
BCIWhisper/
├── BCIWhisper.py
├── BCIWhisper.spec
├── assets/
│   └── bciwhisper.png
├── bci/
├── bci_audio/
│   ├── __init__.py
│   └── boundary.py
├── bci_core/
│   ├── __init__.py
│   └── state.py
├── bciwhisper/
│   └── config/
│       └── paths.py
├── services/
│   └── broadcast-gateway/
├── tools/
├── versions/
├── bci_stress_57_9.py
└── bci_verify_57_9.py
```

### Key files

**`BCIWhisper.py`**  
Primary desktop application and current v6.0 runtime.

**`BCIWhisper.spec`**  
PyInstaller build specification. It packages BCI-owned modules, immutable assets, services, Faster-Whisper, CTranslate2, and required metadata while excluding the previous heavy OpenAI Whisper/Torch/CUDA payload from the standalone build.

**`bci_audio/boundary.py`**  
Supervised process boundary around PortAudio and hardware capture.

**`bci_core/state.py`**  
Explicit application/audio lifecycle state machines.

**`bciwhisper/config/paths.py`**  
Cross-platform runtime-data path resolution.

**`bci_stress_57_9.py`**  
Lifecycle stress harness used during release hardening.

**`bci_verify_57_9.py`**  
Autonomous acceptance/verification tooling.

---

## Current release

The current public release is:

**BCIWhisper v6.0 — Script 57.10**

Release artifact:

```text
BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz
```

SHA-256:

```text
e72d945ba17dddb74343a43e9e786c511a29340f103acaf1bee02b1503d7c354
```

Release page:

https://github.com/BeaconComputingInitiative/BCIWhisper/releases/tag/v6.0-script57.10

### Verify the archive

```bash
sha256sum -c   BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz.sha256
```

Expected result:

```text
BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz: OK
```

### Extract

```bash
tar -xzf BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz
```

The current Linux build is distributed as a PyInstaller `onedir` package.

---

## Cross-platform installation

BCIWhisper v6.0 / Script 57.10 is packaged separately for each supported desktop platform. The application code and DSP pipeline are shared, while the native audio, Qt, and transcription components are built on the target operating system.

### Linux x86_64

Release package:

```text
BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz
```

Verify the checksum:

```bash
sha256sum -c BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz.sha256
```

Extract:

```bash
tar -xzf BCIWhisper-v6.0-Script57.10-Linux-x86_64.tar.gz
```

Run the packaged application from the extracted `BCIWhisper` directory.

### Windows x86_64

Windows is distributed as a native PyInstaller `onedir` ZIP:

```text
BCIWhisper-v6.0-Script57.10-Windows-x86_64.zip
```

Verify the SHA-256 checksum in PowerShell:

```powershell
Get-FileHash .\BCIWhisper-v6.0-Script57.10-Windows-x86_64.zip -Algorithm SHA256
```

Compare the printed hash with:

```text
BCIWhisper-v6.0-Script57.10-Windows-x86_64.zip.sha256
```

Extract the ZIP, open the resulting `BCIWhisper` directory, and launch:

```text
BCIWhisper.exe
```

BCIWhisper stores packaged Windows application data under:

```text
%LOCALAPPDATA%\BCIWhisper
```

The microphone and transcription model remain user-controlled runtime resources.

### macOS Apple Silicon

Apple Silicon builds target native `arm64` Macs.

Release packages:

```text
BCIWhisper-v6.0-Script57.10-macOS-arm64.dmg
BCIWhisper-v6.0-Script57.10-macOS-arm64.zip
```

Verify either package:

```bash
shasum -a 256 BCIWhisper-v6.0-Script57.10-macOS-arm64.dmg
shasum -a 256 BCIWhisper-v6.0-Script57.10-macOS-arm64.zip
```

Compare the result with the corresponding `.sha256` file.

For the DMG:

1. Open the `.dmg`.
2. Drag `BCIWhisper.app` into `Applications`.
3. Launch BCIWhisper from Applications.
4. Approve microphone access when macOS requests it.


BCIWhisper stores packaged macOS application data under:

```text
~/Library/Application Support/BCIWhisper
```

### macOS signing status

The current macOS workflow performs an ad-hoc application signature for bundle integrity testing. It is **not** an Apple Developer ID signature and the application is **not notarized**.

Because of that, Gatekeeper may warn when launching a downloaded build. A future production packaging stage can add Developer ID signing and Apple notarization without changing the BCIWhisper runtime architecture.

### Microphone permission

BCIWhisper's macOS application bundle declares:

```text
NSMicrophoneUsageDescription
```

so macOS can request microphone access through its normal privacy controls.

Windows and Linux microphone access is governed by the operating system, audio backend, and the current user's device permissions.

### Transcription model

The Windows and macOS application packages include the Faster-Whisper / CTranslate2 transcription runtime, but **do not embed the speech model weights**.

Download the recommended model separately:

https://huggingface.co/Systran/faster-whisper-small.en

Expected default model directories:

```text
Linux:
~/.local/share/BCIWhisper/models/faster-whisper-small.en

Windows:
%LOCALAPPDATA%\BCIWhisper\models\faster-whisper-small.en

macOS:
~/Library/Application Support/BCIWhisper/models/faster-whisper-small.en
```

You can override the model location with:

```text
BCI_FASTER_WHISPER_MODEL
```

### Release downloads

All platform packages belong under the same release line:

https://github.com/BeaconComputingInitiative/BCIWhisper/releases/tag/v6.0-script57.10

Each platform artifact should be verified against its accompanying SHA-256 file before execution.

---

## Release validation

Script 57.10 was promoted after the v6.0 stabilization and runtime-hardening cycle.

Recorded validation for the release line includes:

- Script 57.8 autonomous acceptance: **PASS**
- Script 57.9 lifecycle stress: **50 / 50 PASS**
- telemetry integrity check: **PASS**
- new coredumps during lifecycle stress: **0**
- surviving multiprocessing helpers after tested shutdowns: **0**
- surviving frozen BCIWhisper processes after tested shutdowns: **0**
- Script 57.10 clean rebuild: **PASS**
- Script 57.10 packaged smoke test: **PASS**
- graceful Qt shutdown path: **PASS**

The release harness uses a QA-only environment hook to close the frozen application through Qt's normal `closeEvent()` path. This hook is disabled during normal application use.

---

## Building from source

BCIWhisper is a Python / PyQt6 application with native audio and transcription dependencies.

The PyInstaller specification expects, among other runtime packages:

```text
PyQt6
numpy
scipy
sounddevice
soundfile
av
faster-whisper
ctranslate2
tokenizers
huggingface-hub
```

Build environments should use platform-native dependencies and should not assume that Linux wheel selections are valid on Windows or macOS.

### PyInstaller

From a configured environment:

```bash
python -m PyInstaller   --clean   --noconfirm   BCIWhisper.spec
```

Expected `onedir` output:

```text
dist/BCIWhisper/
```

PyInstaller builds must be produced on the target operating system. Windows and macOS builds are therefore generated independently from the Linux release.

---

## Cross-platform strategy

The signal-processing pipeline is intended to remain OS-neutral.

Native audio routing is abstracted behind the PortAudio boundary, with platform families identified as:

```text
Linux   -> PipeWire / PulseAudio / ALSA through PortAudio
Windows -> WASAPI through PortAudio
macOS   -> CoreAudio through PortAudio
```

The current v6.0 / Script 57.10 release targets:

- Linux x86_64
- Windows x86_64
- macOS ARM64 / Apple Silicon

These are separate native release artifacts and should be validated independently. Intel macOS is not a supported release target for Script 57.10.

---

## Environment variables

Important runtime overrides include:

| Variable | Purpose |
|---|---|
| `BCI_DATA_DIR` | Override writable application-data root |
| `BCI_LIVE_HOST` | Live HTTP/MP3 bind host |
| `BCI_LIVE_PORT` | Live HTTP/MP3 port |
| `BCI_LIVE_BITRATE_KBPS` | Broadcast bitrate |
| `BCI_LIVE_PUBLIC_URL` | Optional published stream URL |
| `BCI_OPENAI_WHISPER_MODEL` | OpenAI Whisper model name |
| `BCI_OPENAI_WHISPER_DOWNLOAD_ROOT` | OpenAI Whisper model directory |
| `BCI_OPENAI_WHISPER_DEVICE` | OpenAI Whisper runtime device |
| `BCI_FASTER_WHISPER_MODEL` | Faster-Whisper model path |
| `BCI_WHISPER_LANGUAGE` | Transcription language |
| `BCI_WHISPER_CPP_MODEL` | whisper.cpp model path |
| `BCI_QA_AUTOCLOSE_MS` | QA-only graceful shutdown timer |

`BCI_QA_AUTOCLOSE_MS` is intended only for automated acceptance testing.

---

## Data preservation model

BCIWhisper separates source material from derived material.

The design intent is:

```text
RAW recording
    │
    ├── preserved source
    │
    ▼
isolated / reconstructed derivative
    │
    ▼
mastered derivative
    │
    ▼
optional manually requested transcript
```

This keeps processing stages auditable and avoids treating a transformed file as if it were the original capture.

---

## Packaging policy

The standalone PyInstaller build intentionally excludes:

```text
whisper
torch
torchvision
torchaudio
triton
nvidia
onnx
onnxruntime
```

from the frozen payload.

Faster-Whisper and CTranslate2 provide the lean native transcription path for the standalone package. External transcription backends can still be selected at runtime where configured.

Model data is intentionally kept outside the executable package.

---

## Development status

**v6.0 / Script 57.10** is the current stable cross-platform release baseline for Linux x86_64, Windows x86_64, and macOS ARM64 / Apple Silicon.

The next development cycle is intended to continue beyond the 57.x stabilization line without modifying the sealed 57.10 release artifact.

Major architectural work, service changes, additional publishing infrastructure, and broader cross-platform packaging belong to subsequent development rather than retroactive changes to the sealed release.

---

## Security and operational notes

BCIWhisper interacts with microphones, local files, local telemetry databases, and an optional network listener.

Operators should understand the following:

- microphone capture begins only within the application runtime
- Go Live is opt-in
- live mode creates a network listener according to configured host/port values
- binding to `0.0.0.0` exposes the configured port on available network interfaces
- recordings and telemetry may contain sensitive local information
- runtime directories should be protected according to the host operating system's account and filesystem controls
- release hashes should be verified before execution

BCIWhisper does not treat logs, telemetry, transcripts, or reconstructed audio as immutable evidence by default. Users requiring evidentiary workflows should preserve original files independently and maintain their own chain-of-custody procedures.

---

## Project versioning

BCIWhisper uses the BCI script-count versioning convention:

```text
Scripts  1-10  -> v1.0
Scripts 11-20  -> v2.0
Scripts 21-30  -> v3.0
Scripts 31-40  -> v4.0
Scripts 41-50  -> v5.0
Scripts 51-60  -> v6.0
```

The current release remains within the v6.0 cycle:

```text
Script tally:    57
Script revision: 57.10
Build:           2026.10.17-r6.34.10
```

---

## Beacon Computing Initiative

BCIWhisper is a **Beacon Computing Initiative** project.

Lead developer:

**Chance Joaquin Boone**

Developer seal:

```text
CJB-DEV-2026
```

BCI's engineering approach emphasizes observable behavior, preservation of source material, transparent analysis, secure communication, deliberate changes, and reproducible validation.

---

## Releases

Current release:

https://github.com/BeaconComputingInitiative/BCIWhisper/releases/tag/v6.0-script57.10

Repository:

https://github.com/BeaconComputingInitiative/BCIWhisper

---

## License

No license file is currently included in this repository.

Until a license is explicitly added, do not assume that the repository grants the permissions normally associated with an open-source license.

---

## Release integrity

For **BCIWhisper v6.0 — Script 57.10**, verify each downloaded platform artifact against its accompanying checksum file. The Linux x86_64 archive SHA-256 is:

```text
SHA-256
e72d945ba17dddb74343a43e9e786c511a29340f103acaf1bee02b1503d7c354
```

Verify release artifacts against the checksum published with the GitHub Release before running them.

---

**Beacon Computing Initiative**  
**BCIWhisper v6.0**  
**Observe accurately. Preserve faithfully. Analyze transparently. Communicate securely. Act deliberately.**
