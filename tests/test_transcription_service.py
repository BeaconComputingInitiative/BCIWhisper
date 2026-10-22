# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: e21b572bfe8a4bfc26ae39aeb8b1c613be27878fac864a32b328ba8c1ddd9ac5
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bciwhisper.services.transcription import TranscriptionService, TranscriptionServiceState
from bciwhisper.transcription.contracts import TranscriptResult


class FakeBackend:
    def __init__(self, name: str, available: bool, text: str = "ok", fail: bool = False) -> None:
        self.name = name
        self._available = available
        self.text = text
        self.fail = fail
        self.model = "test-model"

    def available(self) -> bool:
        return self._available

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        if self.fail:
            raise RuntimeError("forced test failure")
        return TranscriptResult(
            backend=self.name,
            audio_path=audio_path,
            text=self.text,
            language="en",
            model=self.model,
        )


class TranscriptionServiceTests(unittest.TestCase):
    def test_ready_if_and_only_if_backend_selected(self) -> None:
        service = TranscriptionService([FakeBackend("openai-whisper", True)])
        self.assertEqual(
            service.state is TranscriptionServiceState.READY,
            service.available,
        )

    def test_fallback_after_backend_failure(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            service = TranscriptionService(
                [
                    FakeBackend("openai-whisper", True, fail=True),
                    FakeBackend("faster-whisper", True, text="fallback"),
                ]
            )
            result = service.transcribe(Path(handle.name))
            self.assertEqual(result.backend, "faster-whisper")
            self.assertEqual(result.text, "fallback")
            self.assertEqual(
                service.state is TranscriptionServiceState.READY,
                service.available,
            )


if __name__ == "__main__":
    unittest.main()
