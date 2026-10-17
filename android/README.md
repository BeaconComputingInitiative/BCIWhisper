# BCIWhisper Android

BCIWhisper Android is a native Android port, not a repackaging of the PyQt6 desktop executable.

## Phase 1

The first Android phase establishes the hardware and lifecycle boundary:

- native Kotlin application
- Android `AudioRecord` microphone ownership
- foreground microphone service
- 44.1 kHz mono PCM16 capture
- bounded 15-second circular capture ring
- live RMS / peak telemetry
- 60-second baseline clock
- explicit start/stop operator control
- dark BCI interface using cyan / maroon accents

The desktop invariant remains the design reference:

```text
MIC / INPUT
    ↓
hardware boundary
    ↓
bounded capture transport
    ↓
DSP
    ↓
detection
    ↓
recording
    ↓
reconstruction
    ↓
mastering
    ↓
manual transcription
```

Android replaces the desktop PortAudio/PipeWire hardware layer with Android AudioRecord. DSP, recording, reconstruction, mastering, transcription and broadcast are subsequent porting phases.

## Build

Requirements:

- JDK 17
- Android SDK
- Android platform 37
- Gradle 9.5.0
- Android Gradle Plugin 9.3.0

From the `android/` directory:

```bash
gradle :app:assembleDebug
```

APK output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## SDK policy

The project currently targets Android 16 / API 36 and compiles against API 37.

## Package

```text
org.beaconcomputinginitiative.bciwhisper
```

## Release status

This is an Android port baseline and is not feature-equivalent to the sealed desktop v6.0 / Script 57.10 release yet.
