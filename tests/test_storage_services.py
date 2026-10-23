from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bciwhisper.settings.service import SettingsService
from bciwhisper.telemetry.database import TelemetryDatabase


class StorageServiceTests(unittest.TestCase):
    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            service = SettingsService(path)
            service.update_section("audio", {"gain": 2.5})
            second = SettingsService(path)
            self.assertEqual(second.section("audio")["gain"], 2.5)

    def test_telemetry_wal_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = TelemetryDatabase(Path(tmp) / "telemetry.db")
            db.log("TEST", {"value": 7})
            rows = db.recent(5)
            self.assertEqual(rows[0]["name"], "TEST")
            self.assertEqual(rows[0]["payload"]["value"], 7)
            db.close()


if __name__ == "__main__":
    unittest.main()
