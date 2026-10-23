# BEACON COMPUTING INITIATIVE
# BCIWhisper 59.7–60.0 | Nondestructive Timeline Metadata
# Developer Seal: CJB-DEV-2026
from __future__ import annotations
import json
import wave
from pathlib import Path


class EpisodeTimeline:
    """Metadata-only edit decisions; original WAV sources are never overwritten."""
    def __init__(self):
        self.tracks: list[dict] = []
        self.markers: list[dict] = []

    def import_wav(self, filename: str) -> dict:
        path = Path(filename).expanduser().resolve(strict=True)
        if path.suffix.lower() != ".wav":
            raise ValueError("Only WAV sources are supported")
        with wave.open(str(path), "rb") as source:
            rate = source.getframerate()
            frames = source.getnframes()
            channels = source.getnchannels()
        if rate <= 0 or channels != 1:
            raise ValueError("Timeline requires valid mono WAV sources")
        track = {"source": str(path), "rate": rate, "frames": frames,
                 "start": 0.0, "in": 0.0, "out": frames / rate, "muted": False, "gain": 1.0}
        self.tracks.append(track)
        return dict(track)

    def trim(self, index: int, start_seconds: float, end_seconds: float) -> None:
        track = self.tracks[index]
        maximum = track["frames"] / track["rate"]
        if not 0 <= start_seconds < end_seconds <= maximum:
            raise ValueError("Trim must lie inside the source and have positive duration")
        track["in"], track["out"] = float(start_seconds), float(end_seconds)

    def set_mix(self, index: int, gain: float, muted: bool) -> None:
        if not 0.0 <= gain <= 2.0:
            raise ValueError("Track gain must be between 0 and 2")
        self.tracks[index]["gain"] = float(gain)
        self.tracks[index]["muted"] = bool(muted)

    def add_transcript_marker(self, seconds: float, text: str) -> None:
        if seconds < 0 or not text.strip():
            raise ValueError("Marker requires a nonnegative time and text")
        self.markers.append({"time": float(seconds), "text": text.strip()})

    def save(self, filename: str) -> None:
        destination = Path(filename).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "bci-episode-v1", "tracks": self.tracks, "markers": self.markers}
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def load(cls, filename: str) -> "EpisodeTimeline":
        data = json.loads(Path(filename).expanduser().read_text(encoding="utf-8"))
        if data.get("schema") != "bci-episode-v1":
            raise ValueError("Unsupported episode format")
        obj = cls()
        for item in data.get("tracks", []):
            track = obj.import_wav(item["source"])
            obj.trim(len(obj.tracks)-1, float(item["in"]), float(item["out"]))
            track = obj.tracks[-1]
            track["start"] = max(0.0, float(item["start"]))
            obj.set_mix(len(obj.tracks)-1, float(item.get("gain", 1.0)), bool(item.get("muted", False)))
        for marker in data.get("markers", []):
            obj.add_transcript_marker(float(marker["time"]), str(marker["text"]))
        return obj
