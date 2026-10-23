# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3

from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RefactorArchitectureTests(unittest.TestCase):
    def test_new_runtime_does_not_import_monolith_or_pyqt(self) -> None:
        offenders = []
        roots = [
            ROOT / "bciwhisper",
            ROOT / "bci_audio",
            ROOT / "bci_core",
        ]
        for package_root in roots:
            for path in package_root.rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="replace")
                if "import BCIWhisper" in text or "from BCIWhisper" in text:
                    offenders.append(f"{path}: monolith import")
                if "PyQt5" in text or "PyQt6" in text:
                    offenders.append(f"{path}: PyQt dependency")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_qml_entrypoint_uses_rewritten_runtime(self) -> None:
        text = (ROOT / "bciwhisper/ui_qml/bridge.py").read_text(encoding="utf-8")
        self.assertIn("ApplicationRuntime", text)
        self.assertNotIn("BCIWhisper.py", text)


if __name__ == "__main__":
    unittest.main()
