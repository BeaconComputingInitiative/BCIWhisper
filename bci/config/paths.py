from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_ROOT = PROJECT_ROOT / "services" / "broadcast-gateway"
GATEWAY_ENTRYPOINT = GATEWAY_ROOT / "src" / "server.ts"
GATEWAY_DATA_DIR = GATEWAY_ROOT / "data"
