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
- BCI typography roles: Oxanium for brand/display, Rajdhani for UI controls and labels, JetBrains Mono for technical telemetry
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
- Android SDK platform 36
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


## Typography

BCIWhisper Android follows the BCI typography system:

- **Oxanium** — BCIWhisper brand name, section/display headings.
- **Rajdhani** — tabs, buttons, labels, explanatory interface copy.
- **JetBrains Mono** — RMS/peak levels, baseline timing, and other technical/data values.

The app declares these as Android downloadable font resources through the Google Fonts provider, with deterministic Android fallbacks if the provider is unavailable.


## Permission policy

The Android alpha requests only the permission it currently needs from the operator:

- `RECORD_AUDIO` is requested once, on first launch.
- If microphone access is denied, BCIWhisper does not repeatedly prompt. The Monitor control opens Android App permissions instead.
- `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_MICROPHONE` are manifest service capabilities and do not create additional runtime prompts.
- The current Android alpha does not request location, storage, contacts, camera, SMS, phone, Bluetooth, or notification permission.

The one-time request state is stored in private app preferences and resets only if the app is reinstalled or its app data is cleared.

## Branding

The mobile shell follows the BCI identity:

- Oxanium for BCIWhisper branding and section/display headings.
- Rajdhani for tabs, controls, labels, and explanatory interface copy.
- JetBrains Mono for telemetry and technical values.
- Black base, cyan signal accents, and maroon structural accents.
- Beacon Computing Initiative identification and developer seal are visible in-app.
- Launcher and splash assets use the BCI listening / waveform mark.


## Broadcast transport

Android Go Live uses an outbound authenticated WebSocket publisher.

```text
Android microphone
    -> PCM16 capture
    -> outbound authenticated WSS publisher
    -> public BCI Broadcast Gateway
    -> gateway FFmpeg transcode
    -> MP3 StreamPlayer
```

This architecture is specifically compatible with cellular networks because the phone does not accept inbound connections. Carrier-grade NAT does not require any port forwarding.

The app requires a public `wss://` gateway URL and a publisher token. The token is not persisted by the Android UI. The gateway URL may be remembered locally for convenience.

The Android app publishes 44.1 kHz mono signed 16-bit PCM to the gateway. That is approximately 705.6 kbit/s of audio payload before WebSocket overhead. The gateway transcodes that stream to the configured MP3 bitrate for listeners.

The gateway now accepts both desktop MP3 publishers and Android `pcm_s16le` publishers under `bci-broadcast-v1`.
