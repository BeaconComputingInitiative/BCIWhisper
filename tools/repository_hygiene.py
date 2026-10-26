#!/usr/bin/env python3
# BEACON COMPUTING INITIATIVE
# Developer Seal: CJB-DEV-2026 | Chance Joaquin Boone
# SHA-256: see docs/HYGIENE_SHA256SUMS
"""Pass if and only if no new repository-clutter violations are introduced."""
import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath

CODE = {".py", ".sh", ".ps1", ".kt", ".java", ".cpp", ".c", ".hpp", ".h", ".ts", ".tsx", ".js", ".jsx", ".qml"}
COPY_NAME = re.compile(r"(?:^|[_ .-])(?:final|latest|new|old|backup|copy)(?:$|[_ .-]|\d)|\(\d+\)$", re.I)
GENERATED_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".gradle"}
GENERATED_SUFFIXES = {".apk", ".aab", ".exe", ".dmg", ".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}

def git(*args):
    return subprocess.check_output(["git", *args])

def entries(ref):
    result = {}
    for record in git("ls-tree", "-r", "-l", "-z", ref).split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, kind, oid, size = metadata.split()
        if kind == b"blob":
            result[path.decode("utf-8")] = (oid.decode(), int(size))
    return result

def violations(current, baseline):
    """Legacy paths remain visible in the audit; only additions are gated."""
    findings = []
    hashes = {}
    for path, (oid, size) in current.items():
        p = PurePosixPath(path)
        if p.suffix.lower() in CODE and size > 0:
            hashes.setdefault(oid, []).append(path)
        if path in baseline:
            continue
        if COPY_NAME.search(p.stem):
            findings.append(f"{path}: use a purpose-based name; preserve versions in Git")
        if GENERATED_DIRS.intersection(p.parts) or p.suffix.lower() in GENERATED_SUFFIXES:
            findings.append(f"{path}: generated/runtime data belongs outside tracked source")
        if any(part in {"recovery-snapshots", "backups"} for part in p.parts):
            findings.append(f"{path}: use Git history or release assets for source snapshots")
    for paths in hashes.values():
        if len(paths) > 1 and any(path not in baseline for path in paths):
            findings.append("byte-identical source copies require consolidation: " + ", ".join(sorted(paths)))
    return sorted(findings)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Original audited commit SHA")
    args = parser.parse_args()
    findings = violations(entries("HEAD"), entries(args.baseline))
    print("BEACON COMPUTING INITIATIVE | Developer Seal: CJB-DEV-2026")
    for finding in findings:
        print("ERROR: " + finding)
    passed = not findings
    print("PASS: no new repository clutter" if passed else "FAIL: resolve the reported additions")
    # Success occurs if and only if the complete finding list is empty.
    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())
