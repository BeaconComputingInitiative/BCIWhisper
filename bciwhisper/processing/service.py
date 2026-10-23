# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt


class ProcessingService:
    """Offline reconstruction + mastering, independent of the UI."""

    @staticmethod
    def _read_pcm16(path: Path) -> tuple[int, np.ndarray]:
        with wave.open(str(path), "rb") as wf:
            if wf.getsampwidth() != 2:
                raise RuntimeError("only 16-bit PCM WAV is supported")
            rate = int(wf.getframerate())
            channels = int(wf.getnchannels())
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32)
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        return rate, data / 32768.0

    @staticmethod
    def _write_pcm16(path: Path, rate: int, samples: np.ndarray) -> None:
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
        tmp = path.with_suffix(path.suffix + ".tmp")
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(rate))
            wf.writeframes(pcm.tobytes())
        tmp.replace(path)

    def reconstruct(self, raw_path: Path | str, isolated_path: Path | str) -> Path:
        raw_path = Path(raw_path)
        isolated_path = Path(isolated_path)
        rate, raw = self._read_pcm16(raw_path)

        # Conservative offline clarity pass: speech-band cleanup, hum-family
        # suppression, and bounded spectral subtraction from low-energy frames.
        nyquist = rate * 0.5
        low = max(40.0, min(120.0, nyquist * 0.05))
        high = min(9000.0, nyquist - 200.0)
        sos = butter(4, [low / nyquist, high / nyquist], btype="bandpass", output="sos")
        filtered = sosfiltfilt(sos, raw).astype(np.float32)

        n_fft = 2048
        hop = 512
        if filtered.size < n_fft:
            self._write_pcm16(isolated_path, rate, filtered)
            return isolated_path

        window = np.hanning(n_fft).astype(np.float32)
        frames = []
        for start in range(0, filtered.size - n_fft + 1, hop):
            frames.append(filtered[start:start+n_fft] * window)
        matrix = np.stack(frames)
        spec = np.fft.rfft(matrix, axis=1)
        power = np.abs(spec) ** 2

        energy = np.mean(power, axis=1)
        quiet_count = max(1, min(len(energy) // 5, 40))
        quiet_idx = np.argsort(energy)[:quiet_count]
        noise = np.median(power[quiet_idx], axis=0)
        gain = np.clip((power - 0.9 * noise) / np.maximum(power, 1e-12), 0.12, 1.0)
        rebuilt = np.fft.irfft(spec * gain, n=n_fft, axis=1).real.astype(np.float32)

        out = np.zeros(filtered.size, dtype=np.float32)
        norm = np.zeros(filtered.size, dtype=np.float32)
        for i, start in enumerate(range(0, filtered.size - n_fft + 1, hop)):
            out[start:start+n_fft] += rebuilt[i] * window
            norm[start:start+n_fft] += window * window
        mask = norm > 1e-8
        out[mask] /= norm[mask]
        out[~mask] = filtered[~mask]
        self._write_pcm16(isolated_path, rate, out)
        return isolated_path

    def master(self, input_path: Path | str) -> Path:
        input_path = Path(input_path)
        output = input_path.with_name(input_path.stem.replace("_isolated", "") + "_master.wav")

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            proc = subprocess.run(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(input_path),
                    "-af", "loudnorm=I=-14:TP=-1:LRA=11",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0 and output.is_file():
                return output

        rate, data = self._read_pcm16(input_path)
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        if peak > 0.0:
            target = 10.0 ** (-1.0 / 20.0)
            data = data * min(target / peak, 4.0)
        self._write_pcm16(output, rate, data)
        return output
