#!/usr/bin/env bash
# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Executable Payload SHA-256: edad3af45421e9926f073262b20d8a2c1086757daccbdf313bc7d9fc28d23996
# Integrity rule: hash covers the shebang plus executable payload below this header, if and only if that payload is unchanged.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${BCI_QML_PYTHON:-}" ]]; then
    PYTHON="$BCI_QML_PYTHON"
elif [[ -x "$ROOT/.venv-qml/bin/python" ]]; then
    PYTHON="$ROOT/.venv-qml/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi

# The selected interpreter is acceptable if and only if PySide6 imports.
if ! "$PYTHON" -c 'import PySide6' >/dev/null 2>&1; then
    echo "[BCIWhisper] PySide6 is unavailable in: $PYTHON" >&2
    echo "[BCIWhisper] Install requirements-qml-desktop.txt in a dedicated environment." >&2
    exit 2
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m bciwhisper.ui_qml.main "$@"
