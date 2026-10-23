# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import wave
from pathlib import Path

from bciwhisper.config.paths import AUDIO_LOG_DIR


class RecordingLibrary:
    def __init__(self, root: Path | str = AUDIO_LOG_DIR) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _logical_key(path: Path) -> str:
        stem = path.stem
        for suffix in ("_raw", "_isolated", "_master"):
            if stem.endswith(suffix):
                return stem[: -len(suffix)]
        return stem

    @staticmethod
    def _duration(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as wf:
                rate = wf.getframerate()
                return wf.getnframes() / float(rate) if rate else 0.0
        except Exception:
            return 0.0

    def rows(self) -> list[dict]:
        groups: dict[str, dict] = {}
        for path in self.root.glob("*.wav"):
            key = self._logical_key(path)
            row = groups.setdefault(key, {"key": key, "raw": None, "isolated": None, "master": None})
            if path.stem.endswith("_raw"):
                row["raw"] = path
            elif path.stem.endswith("_isolated"):
                row["isolated"] = path
            elif path.stem.endswith("_master"):
                row["master"] = path

        out = []
        for row in groups.values():
            preferred = row["master"] or row["isolated"] or row["raw"]
            if preferred is None:
                continue
            out.append(
                {
                    "key": row["key"],
                    "raw": str(row["raw"] or ""),
                    "isolated": str(row["isolated"] or ""),
                    "master": str(row["master"] or ""),
                    "preferred": str(preferred),
                    "duration": self._duration(preferred),
                    "modified": preferred.stat().st_mtime,
                }
            )
        out.sort(key=lambda item: item["modified"], reverse=True)
        return out
