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


## Animated 3D spectrum

The Monitor workspace includes a native Kotlin/Canvas spectrum renderer.

- 40 logarithmically grouped bands derived from the detector FFT.
- attack/release interpolation for stable motion.
- perspective grid plus depth-history waterfall for a defined 3D analyzer presentation.
- cyan energy geometry with restrained maroon lock-region accents.
- adaptive spectral-lock boundaries rendered directly over the spectrum.
- Android Choreographer drives presentation frames; DSP remains on the capture/detector path.
- visualization data is presentation-only and cannot block capture, recording, transcription, mastering, or broadcast.


## Alpha 8 — baseline and locked-signal decibel telemetry

The Monitor workspace now exposes decibel telemetry at both key stages:

- During the initial 60-second room baseline, BCIWhisper shows a continuously updated 40th-percentile room-floor estimate in **dBFS**.
- When the baseline completes, the final baseline room-floor value remains visible.
- Each active locked signal gets its own running **average dBFS** value.
- Each active lock also exposes the strongest observed **peak dBFS** value.
- Lock SNR remains shown separately as a relative dB value above the room baseline.

These values are deliberately labeled **dBFS**. Android microphone samples do not provide a trustworthy acoustic dB SPL value without per-device microphone calibration, so the app does not mislabel digital amplitude as SPL.


## Alpha 9 — low-signal microphone optimization

The Android capture boundary now probes and uses more of the selected input route while preserving transparent measurements:

- Phone-microphone mode explicitly prefers the Android built-in input device when one is exposed by the device.
- The app records the selected microphone's reported sample-rate and channel-count capabilities for operator visibility.
- Bluetooth microphone mode keeps Android's communication-device / HFP route and now explicitly enters communication mode while that route is active, then restores the previous audio mode on exit.
- The detector's weak-signal threshold is reduced to approximately **4 dB RMS SNR**, while retaining the independent **3 dB spectral-excess** requirement and the two-block confirmation gate.
- BCIWhisper attempts to disable platform AGC, noise suppression, and acoustic echo cancellation on the AudioRecord session when Android exposes those effects. This prevents weak real signal from being silently suppressed and keeps dBFS telemetry meaningful.
- The app does **not** digitally boost microphone samples before detection. Boosting would raise noise together with signal and corrupt the established baseline/SNR relationship.

Hardware caveat: Bluetooth HFP microphone bandwidth, codec, gain, and DSP are controlled partly by the headset and Android vendor stack. BCIWhisper can select and optimize the route but cannot recover frequencies or signal below the hardware/codec noise floor.


## Alpha 10 — identity-preserving spectral lock

The lock now has two distinct stages instead of continuously chasing whichever signal is strongest.

1. **Acquire** — a candidate must satisfy the weak-signal RMS threshold and spectral-excess threshold for two consecutive blocks.
2. **Anchor** — once confirmed, the occupied frequency band and center frequency become the signal identity anchor.
3. **Track** — subsequent blocks are accepted only when their frequency-band overlap and center-frequency proximity are sufficiently similar to the anchored signal.
4. **Constrain** — accepted drift is smoothed and bounded so nearby unrelated sounds cannot drag the lock across the spectrum.
5. **Isolate** — the isolated WAV now uses a fourth-order adaptive band-pass that follows the locked band with small guard margins, attenuating energy outside the specific tracked signal.
6. **Release** — after the configured loss grace finishes the event, the detector explicitly releases the anchor before searching for the next signal.

Raw WAV capture is still preserved unchanged. Only the isolated derivative follows the lock-aware moving filter.


## Production signing

The repository contains a manual signed-release workflow. It does not store or expose the signing key.

Required GitHub Actions secrets:

- `BCI_ANDROID_KEYSTORE_B64`
- `BCI_ANDROID_KEYSTORE_PASSWORD`
- `BCI_ANDROID_KEY_ALIAS`
- `BCI_ANDROID_KEY_PASSWORD`

The workflow materializes the keystore only inside the ephemeral GitHub Actions runner, builds `:app:assembleRelease`, verifies the APK with `apksigner --print-certs`, hashes it, and uploads the signed APK as a workflow artifact.

The signing key itself must remain under operator custody. Losing that private key can prevent future updates from being accepted as the same application identity.
