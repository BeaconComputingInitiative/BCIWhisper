#!/usr/bin/env python3
from __future__ import annotations

import ast
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "bciwhisper"
sys.path.insert(0, str(ROOT))

from bciwhisper.module_manifest import MODULE_LAYERS, STARTUP_SEQUENCE

def group_for(path: Path):
    rel = path.relative_to(PKG)
    if len(rel.parts) < 2:
        return None
    return rel.parts[0]

def imported_group(name: str):
    if not name.startswith("bciwhisper."):
        return None
    parts = name.split(".")
    if len(parts) < 2:
        return None
    return parts[1]

violations = []

for path in PKG.rglob("*.py"):
    py_compile.compile(str(path), doraise=True)
    tree = ast.parse(path.read_text(), filename=str(path))
    src_group = group_for(path)
    if src_group not in MODULE_LAYERS:
        continue
    src_layer = MODULE_LAYERS[src_group]

    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names = [node.module]

        for name in names:
            dst_group = imported_group(name)
            if dst_group not in MODULE_LAYERS:
                continue
            dst_layer = MODULE_LAYERS[dst_group]
            if dst_layer > src_layer:
                violations.append(
                    f"{path.relative_to(ROOT)}: "
                    f"{src_group}(L{src_layer}) imports "
                    f"{dst_group}(L{dst_layer})"
                )

if violations:
    print("[FAIL] architectural dependency violations:")
    for item in violations:
        print("  -", item)
    raise SystemExit(1)

main = ROOT / "BCIWhisper.py"
if main.exists():
    ast.parse(main.read_text(), filename=str(main))
    py_compile.compile(str(main), doraise=True)
    print("[PASS] active BCIWhisper.py compiles")

print("[PASS] all bciwhisper modules compile")
print("[PASS] lower layers do not import higher layers")
print("[PASS] startup sequence:")
print("       " + " -> ".join(STARTUP_SEQUENCE))

for legacy in ("bci_audio/boundary.py", "bci_core/state.py"):
    p = ROOT / legacy
    if p.exists():
        print(f"[PASS] preserved compatibility boundary: {legacy}")
