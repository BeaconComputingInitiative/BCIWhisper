# BEACON COMPUTING INITIATIVE
# BCIWhisper Podcast Lab 59.3 Sequence Tests
# Developer Seal: CJB-DEV-2026
# SHA-256: release manifest computed after packaging
import unittest
import numpy as np
from bciwhisper.audio.program_bus import StudioProgramBus

class ProgramBusSequenceTests(unittest.TestCase):
    def test_passthrough(self):
        bus = StudioProgramBus()
        x = np.array([0.1, -0.3], dtype=np.float32)
        np.testing.assert_allclose(bus.process(x), x)

    def test_gain_and_clip(self):
        bus = StudioProgramBus()
        bus.configure(2.0, False)
        np.testing.assert_allclose(bus.process(np.array([0.4, -0.8], dtype=np.float32)), [0.8, -1.0])

    def test_mute_and_restore(self):
        bus = StudioProgramBus()
        bus.configure(1.0, True)
        self.assertTrue(np.all(bus.process(np.ones(128, dtype=np.float32)) == 0))
        bus.configure(1.0, False)
        self.assertTrue(np.all(bus.process(np.ones(128, dtype=np.float32)) == 1))

    def test_gain_bounds(self):
        bus = StudioProgramBus()
        with self.assertRaises(ValueError):
            bus.configure(2.5, False)

if __name__ == "__main__":
    unittest.main()
