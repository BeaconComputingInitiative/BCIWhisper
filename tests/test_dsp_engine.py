from __future__ import annotations

import math
import unittest

import numpy as np

from bciwhisper.dsp.engine import DSPEngine


class DSPEngineTests(unittest.TestCase):
    def test_baseline_and_spectrum_pipeline(self) -> None:
        rate = 4000
        engine = DSPEngine(baseline_seconds=0.05)
        engine.configure(lowcut=40, highcut=1500, gain=1.0, sensitivity=1.0)

        t = np.arange(400, dtype=np.float32) / rate
        signal = (0.15 * np.sin(2 * math.pi * 400 * t)).astype(np.float32)
        frame = engine.process(signal, rate)

        self.assertTrue(frame.baseline_complete)
        self.assertEqual(frame.sample_rate, rate)
        self.assertGreater(frame.rms, 0.01)
        self.assertGreater(len(frame.spectrum_db), 10)
        self.assertAlmostEqual(frame.peak_freq, 400.0, delta=40.0)


if __name__ == "__main__":
    unittest.main()
