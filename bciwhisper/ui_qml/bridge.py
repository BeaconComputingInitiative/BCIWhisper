# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 8ca878b67682a94d23d63443d4c99ce22b600a2fa1fe81ef8ab1159722e68b68
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore

from bciwhisper.services.transcription import TranscriptionService
from bciwhisper.version import BUILD, PROJECT_VERSION, SCRIPT_REVISION


class _TaskSignals(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class _TranscriptionTask(QtCore.QRunnable):
    def __init__(self, service: TranscriptionService, path: Path) -> None:
        super().__init__()
        self.service = service
        self.path = path
        self.signals = _TaskSignals()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.service.transcribe(self.path))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class BCIWhisperBridge(QtCore.QObject):
    """Stable QML-facing facade.

    QML talks only to this bridge. The bridge delegates domain work to services;
    it does not own microphones, DSP, SQLite, or Whisper model internals.
    """

    identityChanged = QtCore.Signal()
    transcriptionChanged = QtCore.Signal()
    transcriptChanged = QtCore.Signal()

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._transcription = TranscriptionService()
        self._pool = QtCore.QThreadPool.globalInstance()
        self._busy = False
        self._progress = 0
        self._status = self._initial_status()
        self._transcript_text = ""
        self._transcript_path = ""
        self._error_text = ""

    def _initial_status(self) -> str:
        return "READY" if self._transcription.available else "UNAVAILABLE"

    @QtCore.Property(str, notify=identityChanged)
    def projectVersion(self) -> str:
        return PROJECT_VERSION

    @QtCore.Property(str, notify=identityChanged)
    def scriptRevision(self) -> str:
        return SCRIPT_REVISION

    @QtCore.Property(str, notify=identityChanged)
    def engineeringBuild(self) -> str:
        return BUILD

    @QtCore.Property(str, notify=transcriptionChanged)
    def transcriptionBackend(self) -> str:
        return self._transcription.backend_name or "none"

    @QtCore.Property(str, notify=transcriptionChanged)
    def transcriptionModel(self) -> str:
        return self._transcription.model_name or "not configured"

    @QtCore.Property(str, notify=transcriptionChanged)
    def transcriptionStatus(self) -> str:
        return self._status

    @QtCore.Property(bool, notify=transcriptionChanged)
    def transcriptionAvailable(self) -> bool:
        return self._transcription.available

    @QtCore.Property(bool, notify=transcriptionChanged)
    def transcriptionBusy(self) -> bool:
        return self._busy

    @QtCore.Property(int, notify=transcriptionChanged)
    def transcriptionProgress(self) -> int:
        return self._progress

    @QtCore.Property(str, notify=transcriptChanged)
    def transcriptText(self) -> str:
        return self._transcript_text

    @QtCore.Property(str, notify=transcriptChanged)
    def transcriptPath(self) -> str:
        return self._transcript_path

    @QtCore.Property(str, notify=transcriptChanged)
    def errorText(self) -> str:
        return self._error_text

    @QtCore.Slot()
    def refreshTranscriptionBackend(self) -> None:
        if self._busy:
            return
        self._transcription.discover()
        self._status = self._initial_status()
        self._error_text = "; ".join(self._transcription.last_errors)
        self.transcriptionChanged.emit()
        self.transcriptChanged.emit()

    @QtCore.Slot(str)
    def transcribeFile(self, file_url: str) -> None:
        if self._busy:
            return

        url = QtCore.QUrl(file_url)
        path = Path(url.toLocalFile() if url.isLocalFile() else file_url).expanduser()
        if not path.is_file():
            self._error_text = f"Audio file not found: {path}"
            self._status = "ERROR"
            self.transcriptChanged.emit()
            self.transcriptionChanged.emit()
            return

        self._busy = True
        self._progress = 5
        self._status = "TRANSCRIBING"
        self._error_text = ""
        self.transcriptionChanged.emit()
        self.transcriptChanged.emit()

        task = _TranscriptionTask(self._transcription, path)
        task.signals.finished.connect(self._on_transcription_finished)
        task.signals.failed.connect(self._on_transcription_failed)
        self._pool.start(task)

    @QtCore.Slot(object)
    def _on_transcription_finished(self, result: object) -> None:
        self._busy = False
        self._progress = 100
        self._status = "READY"
        self._transcript_text = str(getattr(result, "text", ""))
        self._transcript_path = str(getattr(result, "audio_path", ""))
        self._error_text = ""
        self.transcriptionChanged.emit()
        self.transcriptChanged.emit()

    @QtCore.Slot(str)
    def _on_transcription_failed(self, message: str) -> None:
        self._busy = False
        self._progress = 0
        self._status = "ERROR"
        self._error_text = message
        self.transcriptionChanged.emit()
        self.transcriptChanged.emit()
