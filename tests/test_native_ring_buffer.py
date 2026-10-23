# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import unittest

import numpy as np

from bciwhisper.native import NativeAudioAdapter


class NativeRingBufferTests(unittest.TestCase):
    def test_native_ring_preserves_latest_samples(self) -> None:
        adapter = NativeAudioAdapter()
        if not adapter.native_loaded:
            self.skipTest("native extension not built")

        ring = adapter.create_ring_buffer(4)
        ring.write(np.array([1, 2, 3, 4, 5, 6], dtype=np.float32))

        self.assertEqual(ring.capacity, 4)
        self.assertEqual(ring.size, 4)
        self.assertEqual(ring.overwritten, 2)
        self.assertEqual(ring.snapshot_latest(4), [3.0, 4.0, 5.0, 6.0])
        self.assertEqual(ring.read(2), [3.0, 4.0])
        self.assertEqual(ring.size, 2)


if __name__ == "__main__":
    unittest.main()
