<!-- BEACON COMPUTING INITIATIVE | Developer Seal: CJB-DEV-2026 | Chance Joaquin Boone -->
<!-- SHA-256: see docs/HYGIENE_SHA256SUMS from the repository root -->

# Commit and portfolio audit: BCIWhisper

Reviewed October 26, 2026. Scope: all commits reachable from the available branches at the audit snapshot. GitHub commit/file-diff responses and complete default-branch trees were retrieved.

- Default branch: `master` at `882a3eace8e4f9b7a1a8bf8755743a452126662e`.
- Default history: **221 commits**; all available branch histories: **235 distinct commits within this repository**.
- Available branches: **8**. Shared ancestry across repositories is counted separately.

## Consolidation decision

Apply the presentation and source-boundary cleanup as one squash commit. Preserve published ancestry and release links. Matching commit messages do not prove redundant implementation; matching trees can be normal merge snapshots. Historical fixes and useful feature changes remain available in Git.

## Identical whole-tree snapshots

These commits expose identical tracked trees. They are not duplicate runtime files and do not warrant deleting published history.

- [`882a3eace8`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/882a3eace8e4f9b7a1a8bf8755743a452126662e), [`b21296953f`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/b21296953f4e5cd2a544676b48946c2b35e57f85)
- [`f509eba649`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/f509eba649d5d72fa5fbd0e87caa0d56fce34a50), [`ba862dbfbc`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/ba862dbfbccf9c7fa3c6984ac2e4eff2311a8902)
- [`69e9c68c94`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/69e9c68c9477295da051220d0c6ac509e2a9042e), [`131636bef8`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/131636bef8453b233cfd02032d1d9539fbb5ab87)
- [`0a01847bb5`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/0a01847bb5721dfcf037458dd2788369fc1bc53b), [`2d5a9c1d09`](https://github.com/BeaconComputingInitiative/BCIWhisper/commit/2d5a9c1d09944c69fe5579ac3b6fa0c376fa7551)

## Branch snapshot

| Branch | Reviewed head |
| --- | --- |
| `bci/repository-hygiene-2026-10-26` | `f0c57aaf22d0` |
| `bci/whisper-prestudio-58.4-finalization` | `b21296953f4e` |
| `master` | `882a3eace8e4` |
| `pre-studio-58.4-finalization` | `00ea2d177e16` |
| `script58.1-qml-modular-foundation` | `2d5a9c1d0994` |
| `script58.2-native-modular-finesse` | `131636bef845` |
| `script58.3-full-feature-runtime` | `ba862dbfbccf` |
| `separate-bcistudio-59-60` | `59bb0d9ac2ea` |

## Commit index

The ledger records every reviewed commit, its message, parent count and tree fingerprint. File-change inventories appear in the GitHub commit links. This is a structural redundancy and presentation audit, not a certification of every historical algorithm, dependency, dataset, or hardware behavior.

- [Commits 1](history/commits-01.md)
- [Commits 2](history/commits-02.md)
- [Commits 3](history/commits-03.md)

## Validation boundary

Text source snapshots used locally were checked against their remote Git blob IDs. Binary assets, submodule contents and datasets were inventoried by Git object identity rather than executed or semantically audited. Historical commit patches were retrieved for redundancy analysis; no claim is made that every line has passed a fresh runtime review. Device tests, production deployment and trained-model quality are outside this cleanup.

Release if and only if the exact source commit passes its documented acceptance gates. Existing releases and tags are retained; README status tables distinguish stable references, previews and incomplete recovered source.

## Source consolidation applied

The obsolete Android Alpha 10 tree, its submodule registration and two Android workflows are removed. BCIAndroid owns the newer Alpha 20 implementation. Historical recovery package stubs are removed from the active checkout; their exact prior contents remain at the audited pre-cleanup commit. The 57.10 monolith and its compatibility layers stay because legacy packaging and verification reference them.

Removed paths:

- `android/app/build.gradle.kts`
- `android/app/src/main/AndroidManifest.xml`
- `android/app/src/main/cpp/whisper/CMakeLists.txt`
- `android/app/src/main/cpp/whisper/jni.c`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/MainActivity.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/AudioInputOptimizer.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/AudioMonitorService.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/AudioRingBuffer.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/BluetoothAudioRouter.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/DetectionEngine.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/EventRecorder.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/audio/ReconstructionMasteringEngine.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/broadcast/BroadcastPublisher.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/transcription/TranscriptionEngine.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/transcription/WhisperNative.kt`
- `android/app/src/main/java/org/beaconcomputinginitiative/bciwhisper/ui/Spectrum3DView.kt`
- `android/app/src/main/res/drawable/ic_bci_launcher_foreground.xml`
- `android/app/src/main/res/drawable/ic_bci_notification.xml`
- `android/app/src/main/res/font/jetbrains_mono_regular.xml`
- `android/app/src/main/res/font/oxanium_semibold.xml`
- `android/app/src/main/res/font/rajdhani_medium.xml`
- `android/app/src/main/res/mipmap-anydpi/ic_launcher.xml`
- `android/app/src/main/res/mipmap-anydpi/ic_launcher_round.xml`
- `android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml`
- `android/app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml`
- `android/app/src/main/res/values/colors.xml`
- `android/app/src/main/res/values/font_certs.xml`
- `android/app/src/main/res/values/preloaded_fonts.xml`
- `android/app/src/main/res/values/styles.xml`
- `android/app/src/main/res/values-v31/styles.xml`
- `android/build.gradle.kts`
- `android/gradle.properties`
- `android/settings.gradle.kts`
- `.gitmodules`
- `.github/workflows/build-android.yml`
- `.github/workflows/build-signed-android.yml`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/ui/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/telemetry/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/broadcast/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/transcription/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/config/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/common/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/dsp/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/audio/__init__.py`
- `versions/recovery-snapshots/pre-recovery-20261011-163918/bciwhisper/recording/__init__.py`
- `android/vendor/whisper.cpp` (Git submodule entry)

## Fresh cleanup verification

Fresh local checks: 17 fallback-suite tests ran: 16 passed and one native-ring test skipped because the native extension was not built. Product-boundary, recording, processing, storage and transcription tests passed. This does not establish native, GUI, packaging or device acceptance.
