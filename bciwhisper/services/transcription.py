# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: f332fb20de1ee30e95f050864edbdb2faca257d5ad03f8d6465ec9027325c8b3
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from bciwhisper.transcription.contracts import TranscriptResult, TranscriptionBackend


class TranscriptionServiceState(str, Enum):
    NEW = "NEW"
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class BackendDescriptor:
    name: str
    model: str
    available: bool
    detail: str = ""


class _OpenAIWhisperBackend:
    name = "openai-whisper"

    def __init__(self) -> None:
        self.model_name = os.environ.get("BCI_OPENAI_WHISPER_MODEL", "small.en").strip() or "small.en"
        self.device = os.environ.get("BCI_OPENAI_WHISPER_DEVICE", "cpu").strip() or "cpu"
        self.download_root = os.environ.get(
            "BCI_OPENAI_WHISPER_DOWNLOAD_ROOT",
            str(Path.home() / "Audio" / "models" / "openai-whisper"),
        ).strip()
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return importlib.util.find_spec("whisper") is not None

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        import whisper  # type: ignore

        with self._lock:
            if self._model is None:
                self._model = whisper.load_model(
                    self.model_name,
                    device=self.device,
                    download_root=self.download_root or None,
                )
            model = self._model

        result = model.transcribe(str(audio_path), language="en", fp16=False)
        text = str(result.get("text", "")).strip()
        language = str(result.get("language", "en") or "en")
        return TranscriptResult(
            backend=self.name,
            audio_path=audio_path,
            text=text,
            language=language,
            model=self.model_name,
        )


class _FasterWhisperBackend:
    name = "faster-whisper"

    def __init__(self) -> None:
        legacy = os.environ.get("BCI_WHISPER_MODEL", "").strip()
        self.model_ref = os.environ.get(
            "BCI_FASTER_WHISPER_MODEL",
            legacy or str(Path.home() / "Audio" / "models" / "faster-whisper-small.en"),
        ).strip()
        self.device = os.environ.get("BCI_FASTER_WHISPER_DEVICE", "cpu").strip() or "cpu"
        self.compute_type = os.environ.get("BCI_FASTER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        from faster_whisper import WhisperModel  # type: ignore

        with self._lock:
            if self._model is None:
                self._model = WhisperModel(
                    self.model_ref,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            model = self._model

        segments, info = model.transcribe(
            str(audio_path),
            language="en",
            vad_filter=False,
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list if segment.text.strip()).strip()
        language = str(getattr(info, "language", "en") or "en")
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        return TranscriptResult(
            backend=self.name,
            audio_path=audio_path,
            text=text,
            language=language,
            model=self.model_ref,
            duration_seconds=duration,
        )


class _WhisperCppBackend:
    name = "whisper.cpp"

    def __init__(self) -> None:
        configured_bin = os.environ.get("BCI_WHISPER_CPP_BIN", "").strip()
        self.binary = configured_bin or (shutil.which("whisper-cli") or shutil.which("main") or "")
        self.model = os.environ.get("BCI_WHISPER_CPP_MODEL", "").strip()

    def available(self) -> bool:
        return bool(self.binary and self.model and Path(self.model).expanduser().exists())

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        if not self.available():
            raise RuntimeError("whisper.cpp backend is not configured")

        proc = subprocess.run(
            [self.binary, "-m", str(Path(self.model).expanduser()), "-f", str(audio_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "unknown whisper.cpp error").strip()
            raise RuntimeError(f"whisper.cpp failed: {detail}")

        text = proc.stdout.strip()
        return TranscriptResult(
            backend=self.name,
            audio_path=audio_path,
            text=text,
            language="en",
            model=str(Path(self.model).expanduser()),
        )


class TranscriptionService:
    """UI-independent local transcription service.

    The service is READY if and only if one backend is selected. The invariant is
    checked after discovery so a presentation layer cannot observe contradictory
    backend/state information.
    """

    DEFAULT_ORDER: Sequence[str] = (
        "openai-whisper",
        "faster-whisper",
        "whisper.cpp",
    )

    def __init__(self, backends: Iterable[TranscriptionBackend] | None = None) -> None:
        self._backends = list(backends) if backends is not None else [
            _OpenAIWhisperBackend(),
            _FasterWhisperBackend(),
            _WhisperCppBackend(),
        ]
        self._backend: TranscriptionBackend | None = None
        self._state = TranscriptionServiceState.NEW
        self._last_errors: list[str] = []
        self.discover()

    @property
    def state(self) -> TranscriptionServiceState:
        return self._state

    @property
    def backend_name(self) -> str:
        return str(getattr(self._backend, "name", "")) if self._backend is not None else ""

    @property
    def model_name(self) -> str:
        if self._backend is None:
            return ""
        return str(
            getattr(
                self._backend,
                "model_name",
                getattr(self._backend, "model_ref", getattr(self._backend, "model", "")),
            )
        )

    @property
    def available(self) -> bool:
        return self._backend is not None

    @property
    def last_errors(self) -> tuple[str, ...]:
        return tuple(self._last_errors)

    def descriptors(self) -> tuple[BackendDescriptor, ...]:
        rows: list[BackendDescriptor] = []
        for backend in self._backends:
            ok = False
            detail = ""
            try:
                ok = bool(backend.available())
            except Exception as exc:
                detail = str(exc)
            model = str(
                getattr(
                    backend,
                    "model_name",
                    getattr(backend, "model_ref", getattr(backend, "model", "")),
                )
            )
            rows.append(BackendDescriptor(str(getattr(backend, "name", type(backend).__name__)), model, ok, detail))
        return tuple(rows)

    def discover(self) -> None:
        self._backend = None
        self._last_errors.clear()

        order = [
            item.strip()
            for item in os.environ.get("BCI_TRANSCRIPTION_BACKENDS", ",".join(self.DEFAULT_ORDER)).split(",")
            if item.strip()
        ]
        by_name = {str(getattr(item, "name", "")): item for item in self._backends}

        for name in order:
            backend = by_name.get(name)
            if backend is None:
                self._last_errors.append(f"{name}: backend not registered")
                continue
            try:
                if backend.available():
                    self._backend = backend
                    break
                self._last_errors.append(f"{name}: unavailable")
            except Exception as exc:
                self._last_errors.append(f"{name}: {exc}")

        self._state = (
            TranscriptionServiceState.READY
            if self._backend is not None
            else TranscriptionServiceState.UNAVAILABLE
        )
        self._assert_ready_iff_backend_selected()

    def transcribe(self, audio_path: Path | str) -> TranscriptResult:
        source = Path(audio_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        candidates: list[TranscriptionBackend] = []
        if self._backend is not None:
            candidates.append(self._backend)
        candidates.extend(item for item in self._backends if item is not self._backend)

        errors: list[str] = []
        for backend in candidates:
            try:
                if not backend.available():
                    continue
                result = backend.transcribe(source)
                self._backend = backend
                self._state = TranscriptionServiceState.READY
                self._last_errors = errors
                self._assert_ready_iff_backend_selected()
                return result
            except Exception as exc:
                errors.append(f"{getattr(backend, 'name', type(backend).__name__)}: {exc}")

        self._backend = None
        self._state = TranscriptionServiceState.UNAVAILABLE
        self._last_errors = errors or ["No transcription backend is available"]
        self._assert_ready_iff_backend_selected()
        raise RuntimeError("; ".join(self._last_errors))

    def _assert_ready_iff_backend_selected(self) -> None:
        ready = self._state is TranscriptionServiceState.READY
        selected = self._backend is not None
        if ready != selected:
            raise RuntimeError(
                "Transcription invariant violated: service is READY if and only if a backend is selected"
            )
