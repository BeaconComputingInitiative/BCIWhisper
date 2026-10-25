# BEACON COMPUTING INITIATIVE
# BCIWhisper pre-studio restoration contract - Script 58.4
# Developer Seal: CJB-DEV-2026 / BCI Development Division
# SHA-256: see docs/PRE_STUDIO_SHA256SUMS.txt

"""Regression guard for the final standalone BCIWhisper checkpoint.

A build is pre-studio if and only if all independent identity, architecture,
core-feature, and studio-exclusion predicates remain true.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bciwhisper"
FORBIDDEN = (
    ".github/workflows/accept-podcast-59-4.yml",
    ".github/workflows/release-podcast-60-0.yml",
    ".github/workflows/verify-podcast-sequences-59-2.yml",
    "bciwhisper/audio/program_bus.py",
    "bciwhisper/audio/secondary.py",
    "bciwhisper/recording/multitrack.py",
    "bciwhisper/recording/timeline.py",
    "bciwhisper/ui_qml/qml/pages/StudioPage.qml",
    "bciwhisper/ui_qml/qml/pages/TimelinePage.qml",
    "tests/test_episode_timeline_60_0.py",
    "tests/test_multitrack_59_6.py",
    "tests/test_podcast_59_2.py",
    "tests/test_program_bus_59_3.py",
)
REQUIRED = (
    "bciwhisper/version.py",
    "bciwhisper/app/runtime.py",
    "bciwhisper/audio/service.py",
    "bciwhisper/dsp/engine.py",
    "bciwhisper/recording/service.py",
    "bciwhisper/processing/service.py",
    "bciwhisper/broadcast/service.py",
    "bciwhisper/services/transcription.py",
    "bciwhisper/ui_qml/main.py",
    "bciwhisper/ui_qml/bridge.py",
    "bciwhisper/ui_qml/qml/pages/MonitorPage.qml",
    "bciwhisper/ui_qml/qml/pages/TranscriptPage.qml",
    "bciwhisper/ui_qml/qml/pages/MasteringPage.qml",
    "bci_audio/boundary.py",
    "native/CMakeLists.txt",
)


class PreStudioBoundaryTests(unittest.TestCase):
    def test_release_identity(self) -> None:
        version = (SOURCE / "version.py").read_text(encoding="utf-8")
        tree = ast.parse(version)
        values = {
            t.targets[0].id: t.value.value
            for t in tree.body
            if isinstance(t, ast.Assign)
            and len(t.targets) == 1
            and isinstance(t.targets[0], ast.Name)
            and isinstance(t.value, ast.Constant)
        }
        self.assertEqual(values.get("PROJECT_NAME"), "BCIWhisper")
        self.assertEqual(values.get("PROJECT_VERSION"), "v6.0")
        self.assertEqual(values.get("SCRIPT_REVISION"), "58.4")
        self.assertEqual(values.get("DEVELOPER_SEAL"), "CJB-DEV-2026")

    def test_all_required_standalone_modules_exist(self) -> None:
        missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
        self.assertEqual(missing, [], f"Missing core modules: {missing}")

    def test_all_podcast_only_modules_are_absent(self) -> None:
        present = [path for path in FORBIDDEN if (ROOT / path).exists()]
        self.assertEqual(present, [], f"Podcast-only modules crossed boundary: {present}")

    def test_qml_navigation_remains_audio_analysis_focused(self) -> None:
        qml = (SOURCE / "ui_qml/qml/Main.qml").read_text(encoding="utf-8")
        self.assertNotIn("StudioPage", qml)
        self.assertNotIn("TimelinePage", qml)
        self.assertIn("MonitorPage", qml)

    def test_qml_entrypoint_preserves_modular_runtime(self) -> None:
        bridge = (SOURCE / "ui_qml/bridge.py").read_text(encoding="utf-8")
        self.assertIn("ApplicationRuntime", bridge)
        main = (SOURCE / "ui_qml/main.py").read_text(encoding="utf-8")
        self.assertIn("BCIWhisperBridge", main)
        self.assertNotIn("BCIWhisper.py", bridge)


if __name__ == "__main__":
    unittest.main()
