<!-- BEACON COMPUTING INITIATIVE -->
<!-- BCIWhisper v6.0 - Script 58.4 standalone finalization -->
<!-- Developer Seal: CJB-DEV-2026 / BCI Development Division -->
<!-- File SHA-256: see docs/PRESTUDIO_SHA256SUMS -->

# BCIWhisper - pre-podcast product boundary

Status: **finalization candidate**, not yet a validated stable release.
Source: tag `v6.0-script58.4`, commit `e53547657c3e884dd41223263597bf4962fe996b`.
Existing Linux prerelease archive SHA-256: `f7249721906f1decf581e0f3f82d1b68d8b4387affdaa8df5114aacc201f5ea4`.
Developer seal: **CJB-DEV-2026**.

## Keep in BCIWhisper

A dedicated desktop audio-analysis application using QML / Qt Quick, PySide6, modular Python services, C++20 / pybind11 native DSP, and a process-isolated microphone boundary. Keep microphone selection, baseline and spectral lock, RAW recording and retention, nondestructive reconstruction, mastering, manual transcription, playback, SQLite WAL telemetry, error reporting, and opt-in Go Live broadcasting.

## Move to BCIStudio

All podcast-specific episode editing, studio track buses, multi-input studio mixing, multitrack recording, episode timelines, and podcast-focused QML pages belong exclusively to BCIStudio. Do not rename BCIWhisper to Studio.

The BCIStudio GitHub repository contains an extracted source baseline, **not yet a validated standalone Studio executable**. Preserve historical 59-60 tags and commits until independent Studio build acceptance; no destructive Git history rewriting.

## Stable release gates

Promote BCIWhisper 58.4 **if and only if** all these gates pass on the final release commit:

1. Pre-podcast identity and product-boundary tests pass, with no podcast UI or runtime modules.
2. Full Python tests pass in both fallback and native C++20 modes, including DSP parity.
3. QML starts exactly one window and shutdown leaves no orphaned audio/gateway processes.
4. Microphone hotplug, 60-second calibration, detection, lock, 15-second retention, and RAW preservation pass device-level acceptance.
5. Reconstruction, mastering, playback, offline/manual transcription, and SQLite WAL recover correctly.
6. Go Live is opt-in, its gateway cleans up on stop, and tokens are not leaked to logs.
7. Build, package, and smoke-test each claimed platform independently. Script 58.4 has a published Linux **prerelease**; Windows and macOS builds still need fresh validation.
8. Produce release artifacts and SHA-256 integrity evidence before publishing a stable release.

## Audit references

- Pre-podcast release: https://github.com/BeaconComputingInitiative/BCIWhisper/releases/tag/v6.0-script58.4
- Earlier cross-platform reference: https://github.com/BeaconComputingInitiative/BCIWhisper/releases/tag/v6.0-script57.10
- Separate Studio repository: https://github.com/BeaconComputingInitiative/BCIStudio

BCI principles: Observe accurately; Preserve faithfully; Analyze transparently; Communicate securely; Act deliberately.
