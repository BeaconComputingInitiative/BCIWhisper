# BEACON COMPUTING INITIATIVE
# BCIWhisper v6.0 Script 58.4 | Standalone pre-podcast boundary
# Developer Seal: CJB-DEV-2026 / BCI Development Division
# File SHA-256: see docs/PRESTUDIO_SHA256SUMS

import unittest
from pathlib import Path
from bciwhisper import version

ROOT = Path(__file__).resolve().parents[1]

STUDIO_ONLY = (
    "bciwhisper/recording/multitrack.py",
    "bciwhisper/recording/timeline.py",
    "bciwhisper/audio/program_bus.py",
    "bciwhisper/audio/secondary.py",
    "bciwhisper/ui_qml/qml/pages/StudioPage.qml",
    "bciwhisper/ui_qml/qml/pages/TimelinePage.qml",
    ".github/workflows/accept-podcast-59-4.yml",
    ".github/workflows/release-podcast-60-0.yml",
    ".github/workflows/verify-podcast-sequences-59-2.yml",
)


class PreStudioBoundaryTests(unittest.TestCase):
    """The release gate passes if and only if all boundary requirements hold."""

    def test_checkpoint_identity(self):
        self.assertEqual(version.PROJECT_NAME, "BCIWhisper")
        self.assertEqual(version.PROJECT_VERSION, "v6.0")
        self.assertEqual(version.SCRIPT_REVISION, "58.4")
        self.assertEqual(version.DEVELOPER_SEAL, "CJB-DEV-2026")

    def test_studio_components_absent(self):
        found = [p for p in STUDIO_ONLY if (ROOT / p).exists()]
        self.assertEqual(found, [], "BCIStudio source leaked: " + repr(found))

    def test_whisper_workspace_identity(self):
        qml = (ROOT / "bciwhisper/ui_qml/qml/Main.qml").read_text(encoding="utf-8").upper()
        required = ('"MONITOR"', '"RECORDINGS"', '"TRANSCRIPTS"', '"MASTERING"', '"GO LIVE"', '"TELEMETRY"', '"SETTINGS"')
        for label in required:
            with self.subTest(label=label):
                self.assertIn(label, qml)
        for forbidden in ('"PODCAST"', '"STUDIO"', '"TIMELINE"'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, qml)

    def test_core_service_paths(self):
        required = (
            "bciwhisper/app/runtime.py",
            "bciwhisper/audio/service.py",
            "bciwhisper/dsp/engine.py",
            "bciwhisper/recording/service.py",
            "bciwhisper/processing/service.py",
            "bciwhisper/services/transcription.py",
            "bciwhisper/telemetry/database.py",
            "bciwhisper/broadcast/service.py",
            "bciwhisper/ui_qml/bridge.py",
            "native/CMakeLists.txt",
        )
        missing = [p for p in required if not (ROOT / p).is_file()]
        self.assertEqual(missing, [], "Missing required source: " + repr(missing))


if __name__ == "__main__":
    unittest.main()
