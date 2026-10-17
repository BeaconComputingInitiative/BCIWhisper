from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from .paths import (
    GATEWAY_ROOT,
    GATEWAY_ENTRYPOINT,
    GATEWAY_DATA_DIR,
)

_SECRETS_FILE = Path(GATEWAY_DATA_DIR) / "local_secrets.json"


def _local_tokens() -> tuple[str, str]:
    pub = os.environ.get("BCI_PUBLISHER_TOKEN", "").strip()
    adm = os.environ.get("BCI_ADMIN_TOKEN", "").strip()

    if pub and adm and pub != adm:
        return pub, adm

    try:
        if _SECRETS_FILE.is_file():
            data = json.loads(_SECRETS_FILE.read_text())
            p = str(data.get("publisher_token", "")).strip()
            a = str(data.get("admin_token", "")).strip()
            if p and a and p != a:
                return p, a
    except Exception:
        pass

    _SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    p = secrets.token_urlsafe(48)
    a = secrets.token_urlsafe(48)
    _SECRETS_FILE.write_text(
        json.dumps(
            {"publisher_token": p, "admin_token": a},
            indent=2,
        )
        + "\n"
    )
    try:
        _SECRETS_FILE.chmod(0o600)
    except Exception:
        pass
    return p, a


_MODE = os.environ.get("BCI_GATEWAY_MODE", "local").strip().lower()

if _MODE == "local":
    _PUB, _ADMIN = _local_tokens()
else:
    _PUB = os.environ.get("BCI_PUBLISHER_TOKEN", "").strip()
    _ADMIN = os.environ.get("BCI_ADMIN_TOKEN", "").strip()


@dataclass(frozen=True)
class GatewayConfig:
    mode: str = _MODE
    host: str = os.environ.get("BCI_GATEWAY_HOST", "127.0.0.1").strip()
    port: int = int(os.environ.get("BCI_GATEWAY_PORT", "8766"))
    stream_id: str = os.environ.get(
        "BCI_GATEWAY_STREAM_ID",
        "bciwhisper-main",
    ).strip()
    publisher_token: str = _PUB
    admin_token: str = _ADMIN
    public_base_url: str = os.environ.get(
        "BCI_PUBLIC_BASE_URL",
        "",
    ).strip()

    @property
    def locally_managed(self) -> bool:
        return self.mode == "local"

    @property
    def http_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> str:
        return f"{self.http_base_url}/health"

    @property
    def publish_url(self) -> str:
        return (
            f"ws://{self.host}:{self.port}"
            f"/api/v1/publish/{self.stream_id}"
        )

    @property
    def admin_url(self) -> str:
        return f"{self.http_base_url}/api/v1/admin"

    @property
    def player_url(self) -> str:
        return f"{self.http_base_url}/player"


GATEWAY_CONFIG = GatewayConfig()

# ---------------------------------------------------------------------------
# Compatibility path contract
# ---------------------------------------------------------------------------
# bci.broadcast.gateway_process consumes these names through this module.
# Filesystem topology remains owned by bci.config.paths.
GATEWAY_ROOT_PATH = GATEWAY_ROOT
GATEWAY_ENTRYPOINT_PATH = GATEWAY_ENTRYPOINT
GATEWAY_DATA_PATH = GATEWAY_DATA_DIR

