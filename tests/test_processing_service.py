from __future__ import annotations

import math
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from bciwhisper.processing.service import ProcessingService


def write_wav(path: Path, rate: int = 8000) -> None:
    t = np.arange(rate, dtype=np.float32) / rate
    signal = 0.2 * np.sin(2 * math.pi * 440 * t)
    noise = 0.01 * np.sin(2 * math.pi * 60 * t)
    pcm = (np.clip(signal + noise, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


class ProcessingServiceTests(unittest.TestCase):
    def test_reconstruct_and_master_create_valid_wav_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "sample_raw.wav"
            isolated = root / "sample_isolated.wav"
            write_wav(raw)
            isolated.write_bytes(raw.read_bytes())

            service = ProcessingService()
            rebuilt = service.reconstruct(raw, isolated)
            master = service.master(rebuilt)

            self.assertTrue(rebuilt.is_file())
            self.assertTrue(master.is_file())
            with wave.open(str(master), "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertGreater(wf.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
