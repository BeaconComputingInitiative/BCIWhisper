# BCIWhisper Android

BCIWhisper Android is the native Android port of the BCIWhisper workflow.

## Current mobile baseline — Alpha 6

Workspaces:

```text
MONITOR | RECORDINGS | TRANSCRIPTS | MASTERING
```

### Implemented

- native Kotlin / Android application
- branded BCI launcher, splash, typography and UI
- one-time microphone permission behavior
- phone microphone and operator-selected Bluetooth headset microphone
- Android AudioRecord hardware boundary
- foreground microphone service
- 44.1 kHz mono PCM16 capture
- bounded 15-second circular capture ring
- 60-second room baseline
- baseline-relative RMS detection
- spectral baseline profile
- adaptive post-trigger spectral lock using the desktop lock constants:
  - 12% / 92% occupied-energy quantiles
  - 700 Hz minimum lock width
  - 150 Hz lock margin
  - 0.35 smoothing
  - 500 Hz maximum update step
  - 3 dB spectral-presence gate
- two-block trigger confirmation
- 5-second signal-loss release grace
- 15-second retained-event rule
- raw + isolated WAV preservation
- app-private recordings library
- native whisper.cpp offline transcription
- bundled tiny.en model
- manual, downstream transcription workflow
- outbound authenticated WSS broadcast publisher
- cellular / Wi-Fi network awareness
- gateway PCM16 -> MP3 transcode path
- offline STFT/Wiener reconstruction
- harmonic spectral protection
- non-destructive reconstructed and mastered WAV derivatives
- conservative mobile clarity EQ and -1 dBFS output ceiling

## Permission policy

Runtime permissions are requested only when required:

- `RECORD_AUDIO`: requested once on first launch.
- `BLUETOOTH_CONNECT` on Android 12+: requested only when Bluetooth Mic is selected for the first time.

If either permission is denied, BCIWhisper does not repeatedly prompt. Subsequent operator actions direct Android to the app-permission settings.

BCIWhisper does not request location, storage, contacts, camera, SMS, phone, Bluetooth scanning, or notification permission.

## Signal chain

```text
MIC / INPUT
    ↓
AudioRecord hardware boundary
    ↓
capture ring
    ↓
room baseline + spectral profile
    ↓
RMS trigger + adaptive spectral lock
    ↓
retained event lifecycle
    ↓
RAW + isolated WAV
    ├── whisper.cpp -> TRANSCRIPTS
    ├── STFT/Wiener reconstruction
    │       ↓
    │   clarity mastering -> MASTERING
    └── outbound WSS publisher -> Broadcast Gateway -> MP3 StreamPlayer
```

## Mastering status

The reconstruction stage now carries the desktop algorithmic intent: STFT analysis, percentile noise estimation, Wiener-style subtraction, spectral floor, and local-peak/harmonic protection.

Alpha 6 does **not** claim exact desktop mastering parity yet. The desktop release targets -14 LUFS and -1 dBTP. The mobile build currently uses deterministic RMS normalization with a -1 dBFS ceiling. EBU R128 gating and oversampled true-peak measurement remain validation items before production release.

## Transcription

The Android application embeds whisper.cpp as a pinned native ARM64 dependency and bundles `ggml-tiny.en.bin`. Transcription is manual and runs on a dedicated worker thread downstream of recording, so it cannot block capture, detection, recording, or broadcast.

## Broadcast

Android Go Live makes an outbound authenticated `wss://` connection. No inbound mobile-network port is required, so carrier NAT / CGNAT is compatible with the design.

## Build

Requirements:

- JDK 17
- Android SDK 36
- Android Build Tools 36.0.0
- Android NDK 25.2.9519653
- CMake 3.22.1
- Gradle 9.5.0

```bash
cd android
gradle :app:assembleDebug
```

Output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Package:

```text
org.beaconcomputinginitiative.bciwhisper
```

## Remaining release-validation items

- physical Android-device microphone lifecycle stress
- Bluetooth route validation across representative headsets
- real LTE/5G -> public gateway broadcast validation
- whisper.cpp thermal / latency profiling on ARM64 hardware
- EBU R128 integrated loudness and oversampled true-peak implementation
- production signing / release-key custody

These are not represented as passed until they have real device or release-key evidence.
