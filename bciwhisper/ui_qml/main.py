# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import os
import sys
import multiprocessing
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
    app.aboutToQuit.connect(bridge.shutdown)
    engine.rootContext().setContextProperty("bci", bridge)

    qml_path = _qml_main_path()
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        print(f"[BCIWhisper][QML] FAIL: no root object created from {qml_path}", file=sys.stderr)
        return 2

    print("[BCIWhisper][QML] ROOT_READY")
    print(
        f"[BCIWhisper][QML] {bridge.projectVersion} "
        f"Script {bridge.scriptRevision} Build {bridge.engineeringBuild}"
    )
    print(
        "[BCIWhisper][NATIVE] "
        f"loaded={bridge.nativeLoaded} "
        f"backend={bridge.nativeBackend} "
        f"self_test={bridge.nativeSelfTest}"
    )

    smoke = os.environ.get("BCI_QML_SMOKE_TEST", "").strip() == "1"
    if smoke:
        QtCore.QTimer.singleShot(250, app.quit)
    else:
        QtCore.QTimer.singleShot(0, bridge.startRuntime)

    return app.exec()


if __name__ == "__main__":
    # Required for PyInstaller + multiprocessing spawn. Without this, every
    # isolated PortAudio child may re-enter main() and create another Qt window.
    multiprocessing.freeze_support()
    raise SystemExit(main())
