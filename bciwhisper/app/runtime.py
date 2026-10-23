# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from bci_core.state import BCIApplicationStateMachine
from bciwhisper.audio.service import AudioBlock, AudioService
from bciwhisper.audio.program_bus import StudioProgramBus
from bciwhisper.audio.secondary import SecondaryMicrophone
from bciwhisper.recording.multitrack import MultitrackRecorder
from bciwhisper.config.paths import AUDIO_LOG_DIR
from bciwhisper.broadcast.service import BroadcastService
from bciwhisper.config.runtime import RUNTIME
from bciwhisper.dsp.engine import DSPEngine
from bciwhisper.playback.service import PlaybackService
from bciwhisper.processing.service import ProcessingService
from bciwhisper.recording.library import RecordingLibrary
from bciwhisper.recording.service import RecordingResult, RecordingService
from bciwhisper.services.transcription import TranscriptionService
from bciwhisper.settings.service import SettingsService
from bciwhisper.telemetry.database import TelemetryDatabase


class ApplicationRuntime:
    """Single application-domain authority for the rewritten 58.3 runtime."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dsp_lock = threading.RLock()
        self._recording_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="BCI-Service")
        self.state_machine = BCIApplicationStateMachine()
        self.settings = SettingsService()
        self.telemetry = TelemetryDatabase()
        self.dsp = DSPEngine(baseline_seconds=RUNTIME.baseline_seconds)
        self.recording = RecordingService()
        self.program_bus = StudioProgramBus()
        self.library = RecordingLibrary()
        self.processing = ProcessingService()
        self.transcription = TranscriptionService()
        self.playback = PlaybackService()
        self.broadcast = BroadcastService()
        self.audio = AudioService(on_block=self._on_audio_block, on_event=self._on_audio_event)
        self.secondary_audio = SecondaryMicrophone(on_block=self._on_secondary_block, on_event=self._on_secondary_event)
        self.multitrack = MultitrackRecorder(AUDIO_LOG_DIR)

        audio_settings = self.settings.section("audio")
        self.dsp.configure(
            lowcut=float(audio_settings.get("lowcut_hz", 80.0)),
            highcut=float(audio_settings.get("highcut_hz", 8000.0)),
            gain=float(audio_settings.get("gain", 1.0)),
            sensitivity=float(audio_settings.get("sensitivity", 1.0)),
        )

        self._snapshot: dict[str, Any] = {
            "phase": "starting",
            "phase_reason": "runtime created",
            "audio_pid": 0,
            "device_name": "",
            "device_id": -1,
            "sample_rate": 0,
            "devices": [],
            "paired_devices": [],
            "rms": 0.0,
            "peak": 0.0,
            "peak_freq": 0.0,
            "noise_floor_db": -120.0,
            "snr_db": 0.0,
            "active": False,
            "baseline_progress": 0.0,
            "baseline_complete": False,
            "dsp_backend": "",
            "spectrum_db": [],
            "spectrum_hz": [],
            "recording": False,
            "last_recording": "",
            "last_multitrack_manifest": "",
            "go_live": False,
            "player_url": "",
            "last_error": "",
        }

    def snapshot(self) -> dict:
        with self._lock:
            result = dict(self._snapshot)
        result["phase"] = self.state_machine.phase.value
        result["phase_reason"] = self.state_machine.reason
        result["audio_pid"] = int(self.audio.pid or 0)
        result["recording"] = self.recording.recording
        result["manual_recording"] = self.recording.manual
        result["go_live"] = self.broadcast.live
        result["player_url"] = self.broadcast.player_url if self.broadcast.live else ""
        result["broadcast"] = self.broadcast.stats
        result["program_bus"] = self.program_bus.settings()
        result["secondary_running"] = self.secondary_audio.running
        result["secondary_session"] = self.secondary_audio.session
        result["multitrack_recording"] = self.multitrack.active
        return result

    def start(self) -> None:
        audio = self.settings.section("audio")
        selection = {
            "mode": str(audio.get("selection_mode", "auto")),
            "device_id": int(audio.get("device_id", -1)),
            "device_name": str(audio.get("device_name", "")),
        }
        self.state_machine.mark_waiting_for_audio("starting isolated capture")
        self.audio.start(selection)
        self.telemetry.log("RUNTIME_STARTED", {"selection": selection})

    def stop(self) -> None:
        self.state_machine.mark_stopping("runtime stop requested")
        try:
            with self._recording_lock:
                result = self.recording.stop()
            if result is not None:
                self._handle_recording_complete(result)
        finally:
            self.stop_multitrack_recording()
            self.secondary_audio.stop()
            self.broadcast.shutdown()
            self.playback.stop()
            self.audio.stop()
            self.telemetry.log("RUNTIME_STOPPED", {})
            self.telemetry.close()
            self._executor.shutdown(wait=False, cancel_futures=True)

    def configure_audio(self, *, lowcut: float, highcut: float, gain: float, sensitivity: float) -> None:
        self.dsp.configure(lowcut=lowcut, highcut=highcut, gain=gain, sensitivity=sensitivity)
        self.settings.update_section(
            "audio",
            {
                "lowcut_hz": float(lowcut),
                "highcut_hz": float(highcut),
                "gain": float(gain),
                "sensitivity": float(sensitivity),
            },
        )
        self.telemetry.log(
            "DSP_PARAMETERS_UPDATED",
            {"lowcut": lowcut, "highcut": highcut, "gain": gain, "sensitivity": sensitivity},
        )

    def select_device(self, device_id: int, device_name: str, mode: str) -> None:
        self.broadcast.stop()
        with self._dsp_lock:
            self.dsp.reset_baseline()
        self.audio.select_device(device_id=device_id, device_name=device_name, mode=mode)
        self.settings.update_section(
            "audio",
            {
                "selection_mode": str(mode),
                "device_id": int(device_id),
                "device_name": str(device_name),
            },
        )
        self.state_machine.mark_recovering("microphone selection changed")

    def recalibrate_baseline(self) -> None:
        """Restart acoustic calibration on the current capture stream."""
        if not self.audio.running or not self.audio.session:
            raise RuntimeError("A live microphone session is required to recalibrate")
        with self._dsp_lock:
            self.dsp.reset_baseline()
        with self._lock:
            self._snapshot["baseline_progress"] = 0.0
            self._snapshot["baseline_complete"] = False
            self._snapshot["noise_floor_db"] = -120.0
        self.state_machine.mark_calibrating("manual room baseline recalibration")
        self.telemetry.log("BASELINE_RECALIBRATION_REQUESTED", {
            "device_name": self.audio.session.get("device_name", ""),
            "sample_rate": self.audio.session.get("sample_rate", 0),
        })

    def refresh_devices(self) -> None:
        self.audio.request_probe()

    def configure_program_bus(self, gain: float, muted: bool) -> None:
        self.program_bus.configure(gain, muted)
        self.telemetry.log("PROGRAM_BUS_UPDATED", self.program_bus.settings())

    def start_secondary_microphone(self, device_id: int, device_name: str = "") -> None:
        if self.audio.session and int(self.audio.session.get("device_id", -1)) == int(device_id):
            raise ValueError("Secondary device must differ from primary device")
        self.secondary_audio.start(device_id, device_name)
        self.telemetry.log("SECONDARY_CAPTURE_REQUESTED", {"id": device_id, "name": device_name})

    def stop_secondary_microphone(self) -> None:
        if self.multitrack.active:
            raise RuntimeError("Stop the multitrack take before disconnecting the secondary microphone")
        self.secondary_audio.stop()

    def start_multitrack_recording(self) -> None:
        if not self.audio.session or not self.secondary_audio.session:
            raise RuntimeError("Both microphone streams must be open")
        primary_rate = int(self.audio.session.get("sample_rate", 0))
        secondary_rate = int(self.secondary_audio.session.get("sample_rate", 0))
        if primary_rate <= 0 or primary_rate != secondary_rate:
            raise RuntimeError("Both microphones must have the same sample rate")
        self.multitrack.start(primary_rate)
        self.telemetry.log("MULTITRACK_STARTED", {"rate": primary_rate})

    def stop_multitrack_recording(self) -> dict:
        result = self.multitrack.stop()
        if result:
            with self._lock:
                self._snapshot["last_multitrack_manifest"] = result["manifest"]
            self.telemetry.log("MULTITRACK_SAVED", result)
        return result

    def _on_secondary_event(self, event: dict) -> None:
        if event.get("type") in {"open_error", "audio_consumer_error", "stream_closed"}:
            self._record_error("secondary_capture", RuntimeError(str(event)))
        self.telemetry.log("SECONDARY_AUDIO_EVENT", event)

    def _on_secondary_block(self, block: AudioBlock) -> None:
        try:
            self.multitrack.feed("secondary", block.samples, block.sample_rate, block.monotonic)
        except Exception as exc:
            self._record_error("secondary_multitrack", exc)

    def start_podcast_recording(self) -> None:
        with self._recording_lock:
            rate = int(self.snapshot().get("sample_rate") or 0)
            if not self.audio.running or rate <= 0:
                raise RuntimeError("Microphone must be connected before recording")
            self.recording.start_manual(rate)
        self.telemetry.log("PODCAST_RECORDING_STARTED", {"sample_rate": rate})

    def stop_podcast_recording(self) -> None:
        with self._recording_lock:
            result = self.recording.stop_manual()
        if result is not None:
            self._handle_recording_complete(result)
            self.telemetry.log("PODCAST_RECORDING_STOPPED", {"path": str(result.raw_path)})

    def recordings(self) -> list[dict]:
        return self.library.rows()

    def play(self, path: str) -> None:
        self.playback.play(path)

    def stop_playback(self) -> None:
        self.playback.stop()

    def reconstruct(self, raw_path: str, isolated_path: str) -> None:
        self._executor.submit(self._reconstruct_job, raw_path, isolated_path)

    def _reconstruct_job(self, raw_path: str, isolated_path: str) -> None:
        try:
            result = self.processing.reconstruct(raw_path, isolated_path)
            self.telemetry.log("RECONSTRUCTION_COMPLETE", {"path": str(result)})
        except Exception as exc:
            self._record_error("reconstruction", exc)

    def master(self, path: str) -> None:
        self._executor.submit(self._master_job, path)

    def _master_job(self, path: str) -> None:
        try:
            result = self.processing.master(path)
            self.telemetry.log("MASTERING_COMPLETE", {"path": str(result)})
        except Exception as exc:
            self._record_error("mastering", exc)

    def transcribe(self, path: str, callback) -> None:
        def job() -> None:
            try:
                result = self.transcription.transcribe(Path(path))
                callback({"ok": True, "text": result.text, "backend": result.backend, "model": result.model})
                self.telemetry.log("TRANSCRIPTION_COMPLETE", {"path": path, "backend": result.backend})
            except Exception as exc:
                callback({"ok": False, "error": str(exc)})
                self._record_error("transcription", exc)
        self._executor.submit(job)

    def set_go_live(self, enabled: bool) -> str:
        if enabled:
            snap = self.snapshot()
            rate = int(snap.get("sample_rate", 0) or 0)
            if rate <= 0:
                raise RuntimeError("cannot go live before an audio capture session is open")
            url = self.broadcast.start(rate)
            self.telemetry.log("LIVE_STARTED", {"url": url, "sample_rate": rate})
            return url
        self.broadcast.stop()
        self.telemetry.log("LIVE_STOPPED", {})
        return ""

    def recent_telemetry(self, limit: int = 100) -> list[dict]:
        return self.telemetry.recent(limit)

    def _on_audio_event(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        with self._lock:
            if kind == "snapshot":
                snap = event.get("snapshot", {}) or {}
                self._snapshot["devices"] = list(snap.get("devices", []) or [])
                self._snapshot["paired_devices"] = list(snap.get("paired_devices", []) or [])
            elif kind == "stream_opened":
                self._snapshot["device_name"] = str(event.get("device_name", ""))
                self._snapshot["device_id"] = int(event.get("device_id", -1))
                self._snapshot["sample_rate"] = int(event.get("sample_rate", 0))
                self._snapshot["last_error"] = ""
                with self._dsp_lock:
                    self.dsp.reset_baseline()
                self._snapshot["baseline_progress"] = 0.0
                self._snapshot["baseline_complete"] = False
                self.state_machine.mark_calibrating("first capture session opened")
            elif kind in {"open_error", "audio_consumer_error"}:
                self._snapshot["last_error"] = str(event.get("message", "audio error"))
                self.state_machine.mark_error(self._snapshot["last_error"])
            elif kind in {"stream_closed", "audio_restarting", "waiting"}:
                self.state_machine.mark_recovering(str(event.get("reason") or event.get("message") or kind))
        self.telemetry.log("AUDIO_EVENT", event)

    def _on_audio_block(self, block: AudioBlock) -> None:
        try:
            with self._dsp_lock:
                frame = self.dsp.process(block.samples, block.sample_rate)
            if frame.baseline_complete:
                self.state_machine.mark_ready("room baseline complete")

            program = self.program_bus.process(frame.filtered)
            self.multitrack.feed("primary", block.samples, block.sample_rate, block.monotonic)
            with self._recording_lock:
                result = self.recording.feed(
                    raw=block.samples,
                    isolated=program,
                    sample_rate=block.sample_rate,
                    locked=frame.active,
                )
            if result is not None:
                self._handle_recording_complete(result)

            if self.broadcast.live:
                self.broadcast.publish(program, block.sample_rate)

            stride = max(1, len(frame.spectrum_db) // 256)
            spectrum_db = frame.spectrum_db[::stride][:256].tolist()
            spectrum_hz = frame.frequencies_hz[::stride][:256].tolist()

            with self._lock:
                self._snapshot.update(
                    {
                        "sample_rate": block.sample_rate,
                        "device_id": block.device_id,
                        "device_name": block.device_name,
                        "rms": frame.rms,
                        "peak": frame.peak,
                        "peak_freq": frame.peak_freq,
                        "noise_floor_db": frame.noise_floor_db,
                        "snr_db": frame.snr_db,
                        "active": frame.active,
                        "baseline_progress": frame.baseline_progress,
                        "baseline_complete": frame.baseline_complete,
                        "dsp_backend": frame.backend,
                        "spectrum_db": spectrum_db,
                        "spectrum_hz": spectrum_hz,
                        "recording": self.recording.recording,
                    }
                )
        except Exception as exc:
            self._record_error("audio_pipeline", exc)

    def _handle_recording_complete(self, result: RecordingResult) -> None:
        with self._lock:
            self._snapshot["last_recording"] = str(result.isolated_path)
        self.telemetry.log(
            "RECORDING_SAVED",
            {
                "raw": str(result.raw_path),
                "isolated": str(result.isolated_path),
                "locked_seconds": result.locked_seconds,
                "duration_seconds": result.duration_seconds,
            },
        )
        self._executor.submit(self._reconstruct_job, str(result.raw_path), str(result.isolated_path))

    def _record_error(self, context: str, exc: Exception) -> None:
        message = f"{context}: {exc}"
        with self._lock:
            self._snapshot["last_error"] = message
        try:
            self.telemetry.log("RUNTIME_ERROR", {"context": context, "error": str(exc)})
        except Exception:
            pass
