# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import math
import unittest

import numpy as np

from bciwhisper.native import NativeAudioAdapter
from bciwhisper.services.native_dsp import NativeDSPService


class NativeDSPTests(unittest.TestCase):
    def test_metrics_are_numerically_sane(self) -> None:
        sample_rate = 48_000
        t = np.arange(4800, dtype=np.float32) / sample_rate
        signal = (0.5 * np.sin(2 * math.pi * 1000 * t)).astype(np.float32)

        result = NativeAudioAdapter().analyze(signal)

        self.assertAlmostEqual(result.rms, 0.5 / math.sqrt(2), delta=0.01)
        self.assertAlmostEqual(result.peak, 0.5, delta=0.01)
        self.assertAlmostEqual(result.dc_offset, 0.0, delta=0.01)
        self.assertGreater(result.zero_crossing_rate, 0.02)
        self.assertLess(result.zero_crossing_rate, 0.06)

    def test_service_self_test(self) -> None:
        result = NativeDSPService().self_test()
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
