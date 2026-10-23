from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from bciwhisper.recording.service import RecordingService


class RecordingServiceTests(unittest.TestCase):
    def test_keeps_capture_after_confirmed_lock_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = RecordingService(
                tmp,
                keep_locked_seconds=0.10,
                release_seconds=0.05,
            )
            rate = 1000
            block = np.full(100, 0.1, dtype=np.float32)

            service.feed(raw=block, isolated=block, sample_rate=rate, locked=True)
            result = service.feed(raw=block, isolated=block, sample_rate=rate, locked=False)

            self.assertIsNotNone(result)
            self.assertTrue(Path(result.raw_path).is_file())
            self.assertTrue(Path(result.isolated_path).is_file())
            self.assertGreaterEqual(result.locked_seconds, 0.10)

    def test_discards_short_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = RecordingService(
                tmp,
                keep_locked_seconds=1.0,
                release_seconds=0.05,
            )
            rate = 1000
            block = np.full(100, 0.1, dtype=np.float32)

            service.feed(raw=block, isolated=block, sample_rate=rate, locked=True)
            result = service.feed(raw=block, isolated=block, sample_rate=rate, locked=False)

            self.assertIsNone(result)
            self.assertEqual(list(Path(tmp).glob("*.wav")), [])


if __name__ == "__main__":
    unittest.main()
