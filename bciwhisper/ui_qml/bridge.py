# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import threading
import os
from pathlib import Path

from PySide6 import QtCore

from bciwhisper.app import ApplicationRuntime
from bciwhisper.services.native_dsp import NativeDSPService
from bciwhisper.version import BUILD, PROJECT_VERSION, SCRIPT_REVISION
from bciwhisper.recording.timeline import EpisodeTimeline


class BCIWhisperBridge(QtCore.QObject):
    runtimeChanged = QtCore.Signal()
    recordingsChanged = QtCore.Signal()
    telemetryChanged = QtCore.Signal()
    transcriptChanged = QtCore.Signal()
    nativeChanged = QtCore.Signal()
    transcriptionResultReady = QtCore.Signal(object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._runtime = ApplicationRuntime()
        self._native = NativeDSPService()
        self._snapshot = self._runtime.snapshot()
        self._recordings: list[dict] = []
        self._telemetry: list[dict] = []
        self._episode = EpisodeTimeline()
        self._transcript_text = ""
        self._transcript_status = "IDLE"
        self._transcript_backend = ""
        self._transcript_model = ""
        self._started = False
        self._shutting_down = False

        self._native_self_test = "NOT_RUN"
        self._native_metrics = ""
        self.transcriptionResultReady.connect(self._apply_transcription_result)
        self.runNativeSelfTest()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll_runtime)
        self._timer.start()

        self._slow_timer = QtCore.QTimer(self)
        self._slow_timer.setInterval(1000)
        self._slow_timer.timeout.connect(self._poll_slow)
        self._slow_timer.start()

    # ------------------------------------------------------------------
    # Identity / architecture
    # ------------------------------------------------------------------

    @QtCore.Property(str, constant=True)
    def projectVersion(self) -> str:
        return PROJECT_VERSION

    @QtCore.Property(str, constant=True)
    def scriptRevision(self) -> str:
        return SCRIPT_REVISION

    @QtCore.Property(str, constant=True)
    def engineeringBuild(self) -> str:
        return BUILD

    @QtCore.Property(str, notify=nativeChanged)
    def nativeBackend(self) -> str:
        return self._native.backend_label

    @QtCore.Property(bool, notify=nativeChanged)
    def nativeLoaded(self) -> bool:
        return self._native.native_loaded

    @QtCore.Property(str, notify=nativeChanged)
    def nativeSelfTest(self) -> str:
        return self._native_self_test

    @QtCore.Property(str, notify=nativeChanged)
    def nativeMetrics(self) -> str:
        return self._native_metrics

    @QtCore.Slot()
    def runNativeSelfTest(self) -> None:
        try:
            result = self._native.self_test()
            self._native_self_test = "PASS" if result["ok"] else "FAIL"
            self._native_metrics = (
                f"RMS {result['rms']:.4f} • "
                f"Peak {result['peak']:.4f} • "
                f"ZCR {result['zero_crossing_rate']:.4f}"
            )
        except Exception as exc:
            self._native_self_test = "FAIL"
            self._native_metrics = str(exc)
        self.nativeChanged.emit()

    # ------------------------------------------------------------------
    # Runtime properties
    # ------------------------------------------------------------------

    def _value(self, key: str, default=None):
        return self._snapshot.get(key, default)

    @QtCore.Property(str, notify=runtimeChanged)
    def phase(self) -> str:
        return str(self._value("phase", "starting"))

    @QtCore.Property(str, notify=runtimeChanged)
    def phaseReason(self) -> str:
        return str(self._value("phase_reason", ""))

    @QtCore.Property(str, notify=runtimeChanged)
    def deviceName(self) -> str:
        return str(self._value("device_name", ""))

    @QtCore.Property(int, notify=runtimeChanged)
    def deviceId(self) -> int:
        return int(self._value("device_id", -1))

    @QtCore.Property(int, notify=runtimeChanged)
    def sampleRate(self) -> int:
        return int(self._value("sample_rate", 0))

    @QtCore.Property(int, notify=runtimeChanged)
    def audioProcessPid(self) -> int:
        return int(self._value("audio_pid", 0))

    @QtCore.Property(float, notify=runtimeChanged)
    def rms(self) -> float:
        return float(self._value("rms", 0.0))

    @QtCore.Property(float, notify=runtimeChanged)
    def peak(self) -> float:
        return float(self._value("peak", 0.0))

    @QtCore.Property(float, notify=runtimeChanged)
    def peakFrequency(self) -> float:
        return float(self._value("peak_freq", 0.0))

    @QtCore.Property(float, notify=runtimeChanged)
    def noiseFloorDb(self) -> float:
        return float(self._value("noise_floor_db", -120.0))

    @QtCore.Property(float, notify=runtimeChanged)
    def snrDb(self) -> float:
        return float(self._value("snr_db", 0.0))

    @QtCore.Property(bool, notify=runtimeChanged)
    def signalActive(self) -> bool:
        return bool(self._value("active", False))

    @QtCore.Property(float, notify=runtimeChanged)
    def baselineProgress(self) -> float:
        return float(self._value("baseline_progress", 0.0))

    @QtCore.Property(bool, notify=runtimeChanged)
    def baselineComplete(self) -> bool:
        return bool(self._value("baseline_complete", False))

    @QtCore.Property(float, notify=runtimeChanged)
    def programGain(self) -> float:
        return float(self._value("program_bus", {}).get("gain", 1.0))

    @QtCore.Property(bool, notify=runtimeChanged)
    def programMuted(self) -> bool:
        return bool(self._value("program_bus", {}).get("muted", False))

    @QtCore.Slot(float, bool)
    def configureProgramBus(self, gain: float, muted: bool) -> None:
        try:
            self._runtime.configure_program_bus(gain, muted)
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Property(bool, notify=runtimeChanged)
    def secondaryRunning(self) -> bool:
        return bool(self._value("secondary_running", False))

    @QtCore.Property(bool, notify=runtimeChanged)
    def multitrackRecording(self) -> bool:
        return bool(self._value("multitrack_recording", False))

    @QtCore.Slot(int)
    def startSecondary(self, device_id: int) -> None:
        try:
            self._runtime.start_secondary_microphone(device_id)
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def stopSecondary(self) -> None:
        try:
            self._runtime.stop_secondary_microphone()
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def startMultitrack(self) -> None:
        try:
            self._runtime.start_multitrack_recording()
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def stopMultitrack(self) -> None:
        try:
            self._runtime.stop_multitrack_recording()
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
            self.refreshRecordings()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Property(bool, notify=runtimeChanged)
    def podcastRecording(self) -> bool:
        return bool(self._value("manual_recording", False))

    @QtCore.Slot()
    def startPodcastRecording(self) -> None:
        try:
            self._runtime.start_podcast_recording()
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def stopPodcastRecording(self) -> None:
        try:
            self._runtime.stop_podcast_recording()
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
            self.refreshRecordings()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Property(bool, notify=runtimeChanged)
    def recording(self) -> bool:
        return bool(self._value("recording", False))

    @QtCore.Property(int, notify=runtimeChanged)
    def streamQueueDepth(self) -> int:
        return int(self._value("broadcast", {}).get("queue_depth", 0))

    @QtCore.Property(int, notify=runtimeChanged)
    def streamDroppedChunks(self) -> int:
        return int(self._value("broadcast", {}).get("dropped_chunks", 0))

    @QtCore.Property(bool, notify=runtimeChanged)
    def goLive(self) -> bool:
        return bool(self._value("go_live", False))

    @QtCore.Property(str, notify=runtimeChanged)
    def playerUrl(self) -> str:
        return str(self._value("player_url", ""))

    @QtCore.Property(str, notify=runtimeChanged)
    def lastError(self) -> str:
        return str(self._value("last_error", ""))

    @QtCore.Property(list, notify=runtimeChanged)
    def devices(self):
        rows = []
        for index, item in enumerate(self._value("devices", []) or []):
            try:
                channels = int(item.get("max_input_channels", 0) or 0)
            except Exception:
                channels = 0
            if channels <= 0:
                continue
            rows.append(
                {
                    "id": index,
                    "name": str(item.get("name", f"Device {index}")),
                    "sampleRate": int(float(item.get("default_samplerate", 0) or 0)),
                    "channels": channels,
                }
            )
        return rows

    @QtCore.Property(list, notify=runtimeChanged)
    def spectrumDb(self):
        return list(self._value("spectrum_db", []) or [])

    @QtCore.Property(list, notify=runtimeChanged)
    def spectrumHz(self):
        return list(self._value("spectrum_hz", []) or [])

    @QtCore.Property(list, notify=recordingsChanged)
    def recordings(self):
        return list(self._recordings)

    @QtCore.Property(list, notify=telemetryChanged)
    def telemetryEvents(self):
        return list(self._telemetry)

    @QtCore.Property(str, notify=transcriptChanged)
    def transcriptText(self) -> str:
        return self._transcript_text

    @QtCore.Property(str, notify=transcriptChanged)
    def transcriptStatus(self) -> str:
        return self._transcript_status

    @QtCore.Property(str, notify=transcriptChanged)
    def transcriptBackend(self) -> str:
        return self._transcript_backend

    @QtCore.Property(str, notify=transcriptChanged)
    def transcriptModel(self) -> str:
        return self._transcript_model

    @QtCore.Property(list, notify=runtimeChanged)
    def episodeTracks(self):
        return list(self._episode.tracks)

    @QtCore.Property(list, notify=runtimeChanged)
    def episodeMarkers(self):
        return list(self._episode.markers)

    @QtCore.Slot(str)
    def importEpisodeTrack(self, path: str) -> None:
        try:
            self._episode.import_wav(path)
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot(int, float, float)
    def trimEpisodeTrack(self, index: int, start: float, end: float) -> None:
        try:
            self._episode.trim(index, start, end)
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot(str)
    def saveEpisode(self, filename: str) -> None:
        try:
            self._episode.save(filename)
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot(str)
    def loadEpisode(self, filename: str) -> None:
        try:
            self._episode = EpisodeTimeline.load(filename)
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot(int, float, bool)
    def setEpisodeTrackMix(self, index: int, gain: float, muted: bool) -> None:
        try:
            self._episode.set_mix(index, gain, muted)
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot(float, str)
    def addEpisodeMarker(self, seconds: float, text: str) -> None:
        try:
            self._episode.add_transcript_marker(seconds, text)
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Property(bool, notify=runtimeChanged)
    def publisherConfigured(self) -> bool:
        from bciwhisper.broadcast.service import _publisher_credential
        try:
            return bool(_publisher_credential())
        except (OSError, PermissionError):
            return False

    @QtCore.Property(str, constant=True)
    def renderPlayerUrl(self) -> str:
        return "https://bciwhisper-live.onrender.com/player"

    @QtCore.Slot(str)
    def savePublisherToken(self, token: str) -> None:
        token = token.strip()
        if not token or any(ch.isspace() for ch in token):
            self._set_local_error("Enter a nonempty publisher token without spaces")
            return
        path = Path.home() / ".config" / "BCIWhisper" / "publisher.token"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=".publisher-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            self._runtime.broadcast.publisher_token = token
            self._snapshot["last_error"] = ""
            self.runtimeChanged.emit()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @QtCore.Slot()
    def startRuntime(self) -> None:
        if self._started:
            return
        self._runtime.start()
        self._started = True

    @QtCore.Slot()
    def recalibrateBaseline(self) -> None:
        try:
            self._runtime.recalibrate_baseline()
            self._snapshot = self._runtime.snapshot()
            self.runtimeChanged.emit()
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def refreshDevices(self) -> None:
        self._runtime.refresh_devices()

    @QtCore.Slot(int, str, str)
    def selectDevice(self, device_id: int, device_name: str, mode: str) -> None:
        self._runtime.select_device(device_id, device_name, mode)

    @QtCore.Slot(float, float, float, float)
    def configureAudio(self, lowcut: float, highcut: float, gain: float, sensitivity: float) -> None:
        self._runtime.configure_audio(
            lowcut=lowcut,
            highcut=highcut,
            gain=gain,
            sensitivity=sensitivity,
        )

    @QtCore.Slot()
    def refreshRecordings(self) -> None:
        self._recordings = self._runtime.recordings()
        self.recordingsChanged.emit()

    @QtCore.Slot(str)
    def playRecording(self, path: str) -> None:
        try:
            self._runtime.play(path)
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def stopPlayback(self) -> None:
        self._runtime.stop_playback()

    @QtCore.Slot(str, str)
    def reconstruct(self, raw_path: str, isolated_path: str) -> None:
        self._runtime.reconstruct(raw_path, isolated_path)

    @QtCore.Slot(str)
    def master(self, path: str) -> None:
        self._runtime.master(path)

    @QtCore.Slot(str)
    def transcribe(self, path: str) -> None:
        self._transcript_status = "TRANSCRIBING"
        self._transcript_text = ""
        self.transcriptChanged.emit()

        def completed(result: dict) -> None:
            self.transcriptionResultReady.emit(dict(result))

        self._runtime.transcribe(path, completed)

    def _apply_transcription_result(self, result: dict) -> None:
        if result.get("ok"):
            self._transcript_status = "READY"
            self._transcript_text = str(result.get("text", ""))
            self._transcript_backend = str(result.get("backend", ""))
            self._transcript_model = str(result.get("model", ""))
        else:
            self._transcript_status = "ERROR"
            self._transcript_text = str(result.get("error", "transcription failed"))
        self.transcriptChanged.emit()

    @QtCore.Slot(bool)
    def setGoLive(self, enabled: bool) -> None:
        try:
            self._runtime.set_go_live(bool(enabled))
        except Exception as exc:
            self._set_local_error(str(exc))

    @QtCore.Slot()
    def refreshTelemetry(self) -> None:
        self._telemetry = self._runtime.recent_telemetry(100)
        self.telemetryChanged.emit()

    @QtCore.Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._timer.stop()
        self._slow_timer.stop()
        if self._started:
            self._runtime.stop()
            self._started = False

    def _poll_runtime(self) -> None:
        self._snapshot = self._runtime.snapshot()
        self.runtimeChanged.emit()

    def _poll_slow(self) -> None:
        self.refreshRecordings()
        self.refreshTelemetry()

    def _set_local_error(self, message: str) -> None:
        self._snapshot["last_error"] = str(message)
        self.runtimeChanged.emit()
