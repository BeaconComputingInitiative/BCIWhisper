# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 59.6 — Dual Track Sequence Tests
# Developer Seal: CJB-DEV-2026
import tempfile
import unittest
import wave
from pathlib import Path
import numpy as np
from bciwhisper.recording.multitrack import MultitrackRecorder


class TestMultitrack(unittest.TestCase):
    def test_two_wavs_shared_length_and_silence_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = MultitrackRecorder(directory)
            recorder.start(48000)
            start = recorder._origin
            signal = np.ones(4800, dtype=np.float32) * .25
            recorder.feed("primary", signal, 48000, start + .1)
            recorder.feed("secondary", signal, 48000, start + .2)
            result = recorder.stop()
            self.assertEqual(len(result["tracks"]), 2)
            self.assertTrue(Path(result["manifest"]).is_file())
            lengths = []
            for path in result["tracks"].values():
                with wave.open(path, "rb") as wav:
                    self.assertEqual(wav.getframerate(), 48000)
                    self.assertEqual(wav.getnchannels(), 1)
                    lengths.append(wav.getnframes())
            self.assertEqual(lengths[0], lengths[1])
            self.assertGreaterEqual(lengths[0], 9600)

    def test_reject_mismatched_sample_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = MultitrackRecorder(directory)
            recorder.start(48000)
            with self.assertRaises(ValueError):
                recorder.feed("secondary", np.ones(64, dtype=np.float32), 44100, recorder._origin + .1)
            recorder.stop()


if __name__ == "__main__":
    unittest.main()
