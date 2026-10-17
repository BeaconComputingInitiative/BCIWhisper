from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

def design_bandpass(lowcut, highcut, sample_rate, order=4):
    nyquist = float(sample_rate) * 0.5
    low = max(1.0, float(lowcut)) / nyquist
    high = min(float(highcut), nyquist - 1.0) / nyquist
    if not 0.0 < low < high < 1.0:
        raise ValueError(
            f"invalid bandpass: low={lowcut}, high={highcut}, rate={sample_rate}"
        )
    return butter(order, [low, high], btype="bandpass", output="sos")

class StatefulBandpass:
    def __init__(self):
        self.signature = None
        self.sos = None
        self.zi = None

    def configure(self, sample_rate, lowcut, highcut, gain=1.0):
        signature = (
            int(sample_rate),
            round(float(lowcut), 3),
            round(float(highcut), 3),
            round(float(gain), 3),
        )
        if signature == self.signature:
            return False
        self.sos = design_bandpass(lowcut, highcut, sample_rate)
        self.zi = sosfilt_zi(self.sos) * 0.0
        self.signature = signature
        return True

    def process(self, samples):
        if self.sos is None:
            raise RuntimeError("filter is not configured")
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y.astype(np.float32, copy=False)
