# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 01ea7e7c784a7df9201077c2b6480c1f736947f560c5ab1e6237c8c14e505304
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQml

from bciwhisper.ui_qml.bridge import BCIWhisperBridge


def main() -> int:
    app = QtGui.QGuiApplication(sys.argv)
    app.setApplicationName("BCIWhisper")
    app.setOrganizationName("Beacon Computing Initiative")
    app.setOrganizationDomain("beaconcomputing.initiative")

    engine = QtQml.QQmlApplicationEngine()
    bridge = BCIWhisperBridge(app)
    engine.rootContext().setContextProperty("bci", bridge)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    # Root creation succeeds if and only if at least one root object exists.
    if not engine.rootObjects():
        print("[BCIWhisper][QML] FAIL: no root object created", file=sys.stderr)
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
