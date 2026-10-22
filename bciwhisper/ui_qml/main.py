# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 3fdbc1a0284cc6888866853162c8b3546d1d6a8707d97320bc6eacbf1dbcb6c5
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

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

    # Root creation succeeded if and only if the engine exposes at least one
    # root object. Fail closed rather than running an invisible event loop.
    if bool(engine.rootObjects()) != True:
        return 2

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
