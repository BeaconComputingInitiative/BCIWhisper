from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6 import QtCore

from bci.config.gateway import (
    GATEWAY_CONFIG,
    GATEWAY_DATA_PATH,
    GATEWAY_ENTRYPOINT_PATH,
    GATEWAY_ROOT_PATH,
)


class GatewayProcessManager(QtCore.QObject):
    """Own the local Bun gateway process only while GO LIVE is active."""

    status_changed = QtCore.pyqtSignal(str)
    output_received = QtCore.pyqtSignal(str)
    error_received = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(
            QtCore.QProcess.ProcessChannelMode.SeparateChannels
        )
        self.process.started.connect(lambda: self.status_changed.emit("RUNNING"))
        self.process.finished.connect(lambda *_: self.status_changed.emit("STOPPED"))
        self.process.errorOccurred.connect(self._on_error)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)

    @property
    def running(self) -> bool:
        return self.process.state() != QtCore.QProcess.ProcessState.NotRunning

    def start(self) -> bool:
        if not GATEWAY_CONFIG.locally_managed:
            return True

        if self.running:
            return True

        bun = shutil.which("bun")
        if not bun:
            self.failed.emit("Bun executable was not found in PATH.")
            self.status_changed.emit("ERROR")
            return False

        entrypoint = Path(GATEWAY_ENTRYPOINT_PATH).resolve()
        gateway_root = Path(GATEWAY_ROOT_PATH).resolve()
        data_dir = Path(GATEWAY_DATA_PATH).resolve()

        if not entrypoint.is_file():
            self.failed.emit(f"BCI gateway entrypoint not found: {entrypoint}")
            self.status_changed.emit("ERROR")
            return False

        data_dir.mkdir(parents=True, exist_ok=True)

        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("BCI_HOST", GATEWAY_CONFIG.host)
        env.insert("BCI_PORT", str(GATEWAY_CONFIG.port))
        env.insert("BCI_STREAM_ID", GATEWAY_CONFIG.stream_id)
        env.insert("BCI_DB_PATH", str(data_dir / "bci_gateway.db"))

        if GATEWAY_CONFIG.publisher_token:
            env.insert("BCI_PUBLISHER_TOKEN", GATEWAY_CONFIG.publisher_token)

        if GATEWAY_CONFIG.admin_token:
            env.insert("BCI_ADMIN_TOKEN", GATEWAY_CONFIG.admin_token)

        env.insert(
            "BCI_PUBLIC_BASE_URL",
            GATEWAY_CONFIG.public_base_url or GATEWAY_CONFIG.http_base_url,
        )

        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(gateway_root))

        self.status_changed.emit("STARTING")
        self.process.start(bun, ["run", str(entrypoint)])

        if not self.process.waitForStarted(3000):
            message = (
                "BCI Broadcast Gateway failed to start: "
                + self.process.errorString()
            )
            self.failed.emit(message)
            self.status_changed.emit("ERROR")
            return False

        return True

    def stop(self) -> None:
        if not self.running:
            return

        self.status_changed.emit("STOPPING")
        self.process.terminate()

        if not self.process.waitForFinished(3000):
            self.process.kill()
            self.process.waitForFinished(2000)

    def _on_error(self, _error) -> None:
        message = self.process.errorString()
        self.error_received.emit(message)
        self.failed.emit(message)
        self.status_changed.emit("ERROR")

    def _read_stdout(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        ).rstrip()
        if text:
            self.output_received.emit(text)

    def _read_stderr(self) -> None:
        text = bytes(self.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        ).rstrip()
        if text:
            self.error_received.emit(text)
