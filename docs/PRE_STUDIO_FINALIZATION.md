<!-- BEACON COMPUTING INITIATIVE -->
<!-- BCIWhisper pre-studio restoration checkpoint: v6.0 Script 58.4 -->
<!-- Developer Seal: CJB-DEV-2026 / BCI Development Division -->
<!-- Integrity: SHA-256 in PRE_STUDIO_SHA256SUMS.txt -->

# BCIWhisper: Pre-Studio Restoration and Finalization

## Immutable source of truth

- Product: BCIWhisper (desktop acoustic monitoring, recording and transcription)
- Last released pre-podcast-studio version: v6.0, Script 58.4
- Original immutable tag: `v6.0-script58.4`
- Original commit: `e53547657c3e884dd41223263597bf4962fe996b`
- Recovery branch: `pre-studio-58.4-finalization`
- Original 57.10 cross-platform package: behavioral reference, **not** a substitute for the refactored 58.4 code.
- Developer Seal: `CJB-DEV-2026`

This branch is intentionally rooted in Script 58.4. Scripts 59 and 60 belong to BCIStudio, not this independent BCIWhisper line. Never rewrite `master` or historical release tags to perform the separation.

## Owned subsystem contract

```text
QML / Qt Quick presentation
  -> PySide6 presentation bridge
    -> Python ApplicationRuntime and service modules
      -> isolated PortAudio hardware capture
      -> C++20 DSP primitives through pybind11
      -> capture ring / baseline / adaptive detection
      -> retention-controlled raw and isolated recordings
      -> reconstruction and mastering derivatives
      -> manual transcription
      -> optional authenticated live publisher
      -> local SQLite/WAL telemetry
```

QML owns presentation only. Capture, DSP, recording and broadcast retain separate lifecycle and resource ownership. The original recording is immutable; subsequent processing produces derivatives. No podcast mixing, episode/timeline controls, multitrack program bus, or podcast-specific workflows are part of BCIWhisper.

## Release gates

A final pre-studio build is accepted **if and only if** all of these conditions are verified:

1. The identity and exclusion guard `tests/test_pre_studio_boundary.py` passes.
2. Python module tests, C++20 native build/ABI checks and parity tests pass.
3. Audio capture process isolation, device failure recovery and shutdown lifecycle are validated.
4. QML boots once per process and closes cleanly without orphan capture processes.
5. Raw/isolated WAV preservation, the minimum confirmed lock retention rule, offline reconstruction/mastering, and manual transcription pass regression tests.
6. The opt-in broadcast gateway passes authorized publisher and shut-down checks.
7. A packaged Linux artifact passes startup smoke; its SHA-256 is recorded against the exact built file.
8. Microphone device behavior and latency claims are clearly separated from CI-only simulated testing; physical hardware claims require device logs.

A CI success is **not** a physical-microphone endurance, acoustic-localization, or thermal validation result. The existing published Script 58.4 package is a historical artifact; changing code requires a distinct maintenance build and renewed acceptance evidence.

## Regression and recovery commands

```bash
python3 -m unittest discover -s tests -p 'test_pre_studio_boundary.py' -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m compileall -q bciwhisper bci_audio bci_core
git diff --name-status v6.0-script58.4...HEAD
sha256sum -c docs/PRE_STUDIO_SHA256SUMS.txt
```

The hash manifest checks the recovery documentation and boundary test. It does not assert integrity of every source file; repository object IDs and a signed/tagged release are separately necessary for wider supply-chain provenance.

## Deferred to BCIStudio

All Scripts 59.x and 60.x podcast-studio workflows, episode metadata, synchronized multitrack recording, timeline, program bus, and StudioPage/TimelinePage QML live in the separate BCIStudio project. Their development must not silently migrate back into this branch.

## Current completion status

- **PASS**: Exact Script 58.4 historical code checkpoint isolated from the later studio code.
- **PENDING**: New maintenance branch CI execution and acceptance results.
- **PENDING**: Target-hardware audio capture, Bluetooth behavior, endurance and microphone recovery verification.
- **PENDING**: Any new maintenance release build, its checksum and distribution artifacts.

Do not label pending acceptance gates as passed.
