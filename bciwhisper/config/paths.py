from __future__ import annotations
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_data_root() -> Path:
    """
    Resolve writable BCIWhisper application data.

    BCI_DATA_DIR overrides automatic path selection.

    Source mode preserves the historical project-local layout.
    Frozen/package mode uses the platform-native per-user data root.
    """
    override = os.environ.get("BCI_DATA_DIR", "").strip()

    if override:
        return Path(override).expanduser().resolve()

    import sys

    if not getattr(sys, "frozen", False):
        return PROJECT_ROOT

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")

        if base:
            return (
                Path(base)
                / "BCIWhisper"
            ).expanduser().resolve()

        return (
            Path.home()
            / "AppData"
            / "Local"
            / "BCIWhisper"
        ).resolve()

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "BCIWhisper"
        ).resolve()

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()

    if xdg_data_home:
        return (
            Path(xdg_data_home).expanduser()
            / "BCIWhisper"
        ).resolve()

    return (
        Path.home()
        / ".local"
        / "share"
        / "BCIWhisper"
    ).resolve()


DATA_ROOT = _default_data_root()
DATA_ROOT.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = PROJECT_ROOT / "assets"
MODELS_DIR = DATA_ROOT / "models"
VERSIONS_DIR = PROJECT_ROOT / "versions"
BACKUPS_DIR = VERSIONS_DIR / "backups"
SNAPSHOTS_DIR = VERSIONS_DIR / "revamp-snapshots"
TOOLS_DIR = PROJECT_ROOT / "tools"

AUDIO_LOG_DIR = DATA_ROOT / "bci_audio_logs"
ERROR_LOG = DATA_ROOT / "bci_error.log"
TELEMETRY_DB = DATA_ROOT / "bci_telemetry.db"
TELEMETRY_LOG = DATA_ROOT / "bci_telemetry.log"
SHORT_EVENT_LOG = DATA_ROOT / "bci_short_events.jsonl"
ROOM_PROFILE = DATA_ROOT / "bci_room_profile.npz"

SERVICES_DIR = PROJECT_ROOT / "services"
GATEWAY_ROOT = SERVICES_DIR / "broadcast-gateway"
GATEWAY_ENTRYPOINT = GATEWAY_ROOT / "src" / "server.ts"
GATEWAY_DATA_DIR = GATEWAY_ROOT / "data"

for directory in (
    AUDIO_LOG_DIR,
    VERSIONS_DIR,
    BACKUPS_DIR,
    SNAPSHOTS_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)
