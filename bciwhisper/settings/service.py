# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import json
from pathlib import Path

from bciwhisper.config.paths import DATA_ROOT


class SettingsService:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DATA_ROOT / "settings.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = {
            "audio": {
                "selection_mode": "auto",
                "device_id": -1,
                "device_name": "",
                "lowcut_hz": 80.0,
                "highcut_hz": 8000.0,
                "gain": 1.0,
                "sensitivity": 1.0,
            },
            "ui": {"tab": 0},
        }
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            incoming = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(incoming, dict):
                for section, values in incoming.items():
                    if isinstance(values, dict) and isinstance(self._data.get(section), dict):
                        self._data[section].update(values)
                    else:
                        self._data[section] = values
        except Exception:
            return

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def section(self, name: str) -> dict:
        value = self._data.setdefault(name, {})
        return dict(value) if isinstance(value, dict) else {}

    def update_section(self, name: str, values: dict) -> None:
        section = self._data.setdefault(name, {})
        if not isinstance(section, dict):
            section = {}
            self._data[name] = section
        section.update(dict(values))
        self.save()
