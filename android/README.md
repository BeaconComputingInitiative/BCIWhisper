# BCIWhisper Android

BCIWhisper Android is a native Android port of the BCIWhisper workflow. It is not a wrapper around the PyQt6 desktop executable.

## Current mobile baseline

The Android interface is organized around the same operator workflow as desktop:

```text
MONITOR | RECORDINGS | TRANSCRIPTS | MASTERING
```

Only MONITOR is active in the current Android baseline. The remaining workspaces are visible but explicitly marked pending so mobile navigation can stabilize before those subsystems are enabled.

### Implemented

- native Kotlin application
- Android `AudioRecord` microphone boundary
- foreground microphone service
- 44.1 kHz mono PCM16 capture
- bounded 15-second circular capture ring
- live RMS / peak telemetry
- live signal meter
- 60-second background baseline clock
- clear Start Monitor / Stop controls
- stable four-workspace navigation
- BCI dark interface with cyan/maroon accents
- permission-aware microphone startup

### Pending

- detector / lock logic
- recording library
- reconstruction
- mastering
- manual transcription backend
- Go Live publisher

## Architecture

```text
MIC / INPUT
    ↓
Android AudioRecord hardware boundary
    ↓
bounded capture ring
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

The Android hardware boundary replaces the desktop PortAudio/PipeWire layer. Higher processing stages are being ported independently so the mobile application does not inherit desktop-specific hardware assumptions.

## Build

Requirements:

- JDK 17
- Android SDK platform 37
- Android SDK Build Tools 36.0.0
- Gradle 9.5.0
- Android Gradle Plugin 9.3.0

From `android/`:

```bash
gradle :app:assembleDebug
```

Output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Package identifier

```text
org.beaconcomputinginitiative.bciwhisper
```

## Release status

This remains an Android alpha port and is not yet feature-equivalent to the sealed desktop v6.0 / Script 57.10 release.
