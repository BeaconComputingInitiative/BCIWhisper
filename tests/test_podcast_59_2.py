# BEACON COMPUTING INITIATIVE
# BCIWhisper 59.2 Podcast Transport Sequence Tests
# Developer Seal: CJB-DEV-2026
# SHA-256: computed by CI release manifest
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from bciwhisper.recording.service import RecordingService
from bciwhisper.broadcast.service import BroadcastService


class PodcastSequenceTests(unittest.TestCase):
    def test_manual_take_retains_silence_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RecordingService(root=tmp, keep_locked_seconds=15)
            block = np.zeros(4800, dtype=np.float32)
            recorder.start_manual(48000)
            for _ in range(4):
                self.assertIsNone(recorder.feed(raw=block, isolated=block, sample_rate=48000, locked=False))
            result = recorder.stop_manual()
            self.assertIsNotNone(result)
            self.assertTrue(result.raw_path.exists())
            self.assertTrue(result.isolated_path.exists())
            self.assertFalse(recorder.manual)
            self.assertFalse(recorder.recording)

    def test_auto_short_take_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RecordingService(root=tmp, keep_locked_seconds=15, release_seconds=0.1)
            block = np.zeros(4800, dtype=np.float32)
            recorder.feed(raw=block, isolated=block, sample_rate=48000, locked=True)
            result = recorder.feed(raw=block, isolated=block, sample_rate=48000, locked=False)
            self.assertIsNone(result)
            self.assertFalse(recorder.recording)

    def test_stream_queue_full_is_nonblocking(self):
        with patch.dict(os.environ, {"BCI_GATEWAY_URL":"wss://example.test", "BCI_PUBLISHER_TOKEN":"test-token"}):
            service = BroadcastService()
            service._live = True
            service._sample_rate = 48000
            service._send_queue = __import__("queue").Queue(maxsize=1)
            block = np.zeros(480, dtype=np.float32)
            service.publish(block, 48000)
            service.publish(block, 48000)
            self.assertEqual(service.stats["queue_depth"], 1)
            self.assertEqual(service.stats["dropped_chunks"], 1)
            service._live = False

    def test_network_error_does_not_modify_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RecordingService(root=tmp)
            recorder.start_manual(48000)
            block = np.zeros(4800, dtype=np.float32)
            with patch.dict(os.environ, {"BCI_GATEWAY_URL":"wss://example.test", "BCI_PUBLISHER_TOKEN":"test-token"}):
                service = BroadcastService()
                service._live = True
                service._sample_rate = 48000
                service._send_queue = __import__("queue").Queue(maxsize=1)
                for _ in range(3):
                    recorder.feed(raw=block, isolated=block, sample_rate=48000, locked=False)
                    service.publish(block, 48000)
                self.assertGreater(service.stats["dropped_chunks"], 0)
            saved = recorder.stop_manual()
            self.assertIsNotNone(saved)
            self.assertTrue(saved.raw_path.exists())


if __name__ == "__main__":
    unittest.main()
