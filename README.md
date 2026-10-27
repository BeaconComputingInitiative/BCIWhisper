<!-- BEACON COMPUTING INITIATIVE | Developer Seal: CJB-DEV-2026 | Chance Joaquin Boone -->
<!-- SHA-256: see docs/HYGIENE_SHA256SUMS from the repository root -->

# BCIWhisper

<p align="center"><img src="assets/bciwhisper.png" width="180" alt="BCIWhisper"></p>

Desktop audio monitoring, event recording, reconstruction, mastering and manual transcription, with an opt-in broadcast gateway.

**Developer:** Chance Joaquin Boone · **Developer Seal:** CJB-DEV-2026

## Choose a baseline

| Starting point | Status | Link |
| --- | --- | --- |
| Current desktop source | Script 58.4 pre-Studio finalization candidate; hardware acceptance remains open | [Acceptance gates](docs/WHISPER_PRESTUDIO_FINALIZATION.md) |
| Packaged cross-platform reference | Script 57.10; historical Linux, Windows and Apple Silicon packages | [Downloads](https://github.com/BeaconComputingInitiative/BCIWhisper/releases/tag/v6.0-script57.10) · [Installation guide](docs/guides/packaged-57.10.md) |
| QML previews | Scripts 58.1–58.4; Linux prereleases | [Releases](https://github.com/BeaconComputingInitiative/BCIWhisper/releases) |
| Podcast Studio 59–60 | Historical Studio work; independent source now belongs to BCIStudio | [BCIStudio](https://github.com/BeaconComputingInitiative/BCIStudio) |
| Android | Independently maintained mobile application | [BCIAndroid](https://github.com/BeaconComputingInitiative/BCIAndroid) |

The 60.0 release still listed here is historical Podcast Lab work. Use the product and status above when choosing a starting point; its higher number does not designate the current standalone Whisper source.

## Architecture

QML / Qt Quick presents state through a PySide6 bridge. Python application services own lifecycle, DSP policy, recordings, transcription, playback and SQLite WAL telemetry. C++20 / pybind11 supplies native primitives; a separate process owns PortAudio hardware access. RAW recordings are preserved while processing produces derivatives.

| Path | Responsibility |
| --- | --- |
| `bciwhisper/ui_qml/` | Current desktop presentation and launcher |
| `bciwhisper/app/`, `bciwhisper/*/service.py` | Current application orchestration and services |
| `native/` | C++ primitives and Python extension |
| `bci_audio/`, `bci_core/` | Hardware process boundary and lifecycle state |
| `services/broadcast-gateway/` | Opt-in publisher / listener transport |
| `BCIWhisper.py`, legacy platform specs | Historical 57.10 implementation and packaging references |
| `tests/` | DSP, services, storage and product-boundary checks |

## Run the current source

Use a dedicated Python environment with PortAudio available on the host. Bun and FFmpeg are needed for a locally hosted broadcast gateway. Model weights are configured separately.

```bash
python3 -m venv .venv-qml
.venv-qml/bin/python -m pip install -r requirements-qml-desktop.txt
bash run-bciwhisper-qml.sh
```

The Python/NumPy fallback is available for source development. Build `native/` with CMake and pybind11 for native acceptance; see the acceptance workflows. Physical microphone behavior and platform packaging require their own tests.

## Verify and contribute

```bash
python3 -m unittest discover -s tests -v
sha256sum -c docs/HYGIENE_SHA256SUMS
```

Dependencies must be installed before running the full suite. Start with [acceptance gates](docs/WHISPER_PRESTUDIO_FINALIZATION.md), [cleanup findings](docs/PORTFOLIO_AUDIT.md) and [maintenance rules](docs/REPOSITORY_HYGIENE.md). No new runtime release is created by this portfolio cleanup.

Observe accurately. Preserve faithfully. Analyze transparently. Communicate securely. Act deliberately.
