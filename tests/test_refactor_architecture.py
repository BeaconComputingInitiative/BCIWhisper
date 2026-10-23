# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3

from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def imported_modules(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


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
                for module in imported_modules(path):
                    top = module.split(".", 1)[0]
                    if top == "BCIWhisper":
                        offenders.append(f"{path}: imports monolith {module}")
                    if top in {"PyQt5", "PyQt6"}:
                        offenders.append(f"{path}: imports {top}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_qml_entrypoint_uses_rewritten_runtime(self) -> None:
        text = (ROOT / "bciwhisper/ui_qml/bridge.py").read_text(encoding="utf-8")
        self.assertIn("ApplicationRuntime", text)

        modules = imported_modules(ROOT / "bciwhisper/ui_qml/bridge.py")
        self.assertNotIn("BCIWhisper", {module.split(".", 1)[0] for module in modules})


if __name__ == "__main__":
    unittest.main()
