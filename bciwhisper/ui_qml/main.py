# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 74fde0430fe9425872bb1275e84ebe213f1c25ac5db2f2371ec199263f8bcfaa
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQml

from bciwhisper.ui_qml.bridge import BCIWhisperBridge


def _qml_main_path() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "bciwhisper" / "ui_qml" / "qml" / "Main.qml"
    return Path(__file__).resolve().parent / "qml" / "Main.qml"


def main() -> int:
    app = QtGui.QGuiApplication(sys.argv)
    app.setApplicationName("BCIWhisper")
    app.setOrganizationName("Beacon Computing Initiative")
    app.setOrganizationDomain("beaconcomputing.initiative")

    engine = QtQml.QQmlApplicationEngine()
    bridge = BCIWhisperBridge(app)
    engine.rootContext().setContextProperty("bci", bridge)

    qml_path = _qml_main_path()
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    # Root creation succeeds if and only if at least one root object exists.
    if not engine.rootObjects():
        print(f"[BCIWhisper][QML] FAIL: no root object created from {qml_path}", file=sys.stderr)
        return 2

    print("[BCIWhisper][QML] ROOT_READY")
    print(f"[BCIWhisper][QML] {bridge.projectVersion} Script {bridge.scriptRevision} Build {bridge.engineeringBuild}")
    print(
        "[BCIWhisper][TRANSCRIPTION] "
        f"state={bridge.transcriptionStatus} "
        f"backend={bridge.transcriptionBackend} "
        f"model={bridge.transcriptionModel}"
    )

    # CI smoke mode proves that QML loaded and the event loop can start/stop
    # cleanly without requiring an interactive desktop session.
    if os.environ.get("BCI_QML_SMOKE_TEST", "").strip() == "1":
        QtCore.QTimer.singleShot(250, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
