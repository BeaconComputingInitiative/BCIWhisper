# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
from websockets.sync.client import connect

from bciwhisper.broadcast.protocol import PROTOCOL, DEFAULT_STREAM_ID, publisher_hello
from bciwhisper.config.paths import GATEWAY_DATA_DIR, GATEWAY_ENTRYPOINT, GATEWAY_ROOT

RENDER_GATEWAY = "wss://bciwhisper-live.onrender.com"
RENDER_PUBLIC_BASE = "https://bciwhisper-live.onrender.com"


def _publisher_credential() -> str:
    """Environment takes precedence over a private local user credential file."""
    token = os.environ.get("BCI_PUBLISHER_TOKEN", "").strip()
    if token:
        return token
    path = Path.home() / ".config" / "BCIWhisper" / "publisher.token"
    if not path.is_file():
        return ""
    if path.stat().st_mode & 0o077:
        raise PermissionError("BCI publisher token file must be private (chmod 600)")
    return path.read_text(encoding="utf-8").strip()



class BroadcastService:
    """Qt-independent Go Live publisher + optional local Bun gateway owner."""

    def __init__(self) -> None:
        self.host = os.environ.get("BCI_GATEWAY_HOST", "127.0.0.1")
        self.port = int(os.environ.get("BCI_GATEWAY_PORT", "8766"))
        self.stream_id = os.environ.get("BCI_STREAM_ID", DEFAULT_STREAM_ID)
        self.gateway_url = os.environ.get("BCI_GATEWAY_URL", RENDER_GATEWAY).strip().rstrip("/")
        self.publisher_token = _publisher_credential()
        if not self.gateway_url and not self.publisher_token:
            self.publisher_token = secrets.token_urlsafe(32)
        self.admin_token = os.environ.get("BCI_ADMIN_TOKEN", "") or secrets.token_urlsafe(32)
        if self.admin_token == self.publisher_token:
            self.admin_token = secrets.token_urlsafe(32)

        self.public_base = os.environ.get(
            "BCI_PUBLIC_BASE_URL",
            RENDER_PUBLIC_BASE if self.gateway_url else f"http://{self.host}:{self.port}",
        ).rstrip("/")
        self._gateway: subprocess.Popen | None = None
        self._socket = None
        self._lock = threading.RLock()
        self._sample_rate = 0
        self._live = False
        self._bytes_sent = 0
        self._chunks_sent = 0
        self._last_error = ""
        self._send_queue = queue.Queue(maxsize=128)
        self._sender = None
        self._dropped_chunks = 0

    @property
    def live(self) -> bool:
        with self._lock:
            return self._live

    @property
    def player_url(self) -> str:
        return f"{self.public_base}/player"

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "live": self._live,
                "bytes_sent": self._bytes_sent,
                "chunks_sent": self._chunks_sent,
                "queue_depth": self._send_queue.qsize(),
                "dropped_chunks": self._dropped_chunks,
                "player_url": self.player_url,
                "last_error": self._last_error,
            }

    def _start_local_gateway(self) -> None:
        if self.gateway_url:
            return
        if os.environ.get("BCI_MANAGE_LOCAL_GATEWAY", "1").strip() not in {"1", "true", "yes"}:
            return
        if self._gateway is not None and self._gateway.poll() is None:
            return

        bun = shutil.which("bun")
        if not bun:
            raise RuntimeError("Bun executable not found; cannot start local BCI Broadcast Gateway")
        if not Path(GATEWAY_ENTRYPOINT).is_file():
            raise RuntimeError(f"Broadcast gateway entrypoint missing: {GATEWAY_ENTRYPOINT}")

        GATEWAY_DATA_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "BCI_HOST": self.host,
                "BCI_PORT": str(self.port),
                "BCI_STREAM_ID": self.stream_id,
                "BCI_PUBLISHER_TOKEN": self.publisher_token,
                "BCI_ADMIN_TOKEN": self.admin_token,
                "BCI_PUBLIC_BASE_URL": self.public_base,
                "BCI_DB_PATH": str(GATEWAY_DATA_DIR / "bci_gateway.db"),
            }
        )
        self._gateway = subprocess.Popen(
            [bun, "run", str(GATEWAY_ENTRYPOINT)],
            cwd=str(GATEWAY_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if self._gateway.poll() is not None:
                stderr = self._gateway.stderr.read() if self._gateway.stderr else ""
                raise RuntimeError(f"Broadcast gateway exited during startup: {stderr.strip()}")
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://{self.host}:{self.port}/health", timeout=0.35) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Broadcast gateway did not become healthy")

    def start(self, sample_rate: int) -> str:
        with self._lock:
            if self._live:
                return self.player_url

        self.publisher_token = _publisher_credential() or self.publisher_token
        if int(sample_rate) <= 0:
            raise ValueError("A positive sample rate is required")
        if self.gateway_url and not self.publisher_token:
            raise RuntimeError(
                "Render publisher credential missing. Set BCI_PUBLISHER_TOKEN or "
                "create ~/.config/BCIWhisper/publisher.token with mode 0600."
            )
        self._start_local_gateway()

        base = self.gateway_url or f"ws://{self.host}:{self.port}"
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        if not base.startswith(("ws://", "wss://")):
            raise ValueError("BCI_GATEWAY_URL must use https:// or wss:// (or http/ws for local testing)")
        url = f"{base}/api/v1/publish/{self.stream_id}"
        ws = connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {self.publisher_token}",
                "X-BCI-Publisher-Id": "bciwhisper-desktop-58.3",
            },
            open_timeout=4.0,
            close_timeout=2.0,
        )
        ws.send(
            json.dumps(
                publisher_hello(
                    sample_rate=int(sample_rate),
                    channels=1,
                    bitrate_kbps=128,
                    codec="pcm_s16le",
                )
            )
        )
        ack = json.loads(ws.recv(timeout=4.0))
        if ack.get("type") != "hello_ack" or ack.get("protocol") != PROTOCOL:
            ws.close()
            raise RuntimeError(f"Broadcast gateway hello rejected: {ack}")

        with self._lock:
            self._socket = ws
            self._sample_rate = int(sample_rate)
            self._live = True
            self._bytes_sent = 0
            self._chunks_sent = 0
            self._last_error = ""
            self._dropped_chunks = 0
            self._send_queue = queue.Queue(maxsize=128)
            self._sender = threading.Thread(target=self._send_loop, args=(ws, self._send_queue), daemon=True, name="BCI-StreamPublisher")
            self._sender.start()
        return self.player_url

    def _send_loop(self, ws, send_queue) -> None:
        """Network transmission runs outside the capture callback."""
        while True:
            with self._lock:
                if not self._live or self._socket is not ws:
                    break
            try:
                pcm = send_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                ws.send(pcm)
                with self._lock:
                    self._bytes_sent += len(pcm)
                    self._chunks_sent += 1
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    if self._socket is ws:
                        self._socket = None
                        self._live = False
                        self._sample_rate = 0
                break
            finally:
                send_queue.task_done()
        try:
            ws.close()
        except Exception:
            pass

    def publish(self, samples: np.ndarray, sample_rate: int) -> None:
        with self._lock:
            if not self._live:
                return
            configured_rate = self._sample_rate
        if int(sample_rate) != configured_rate:
            with self._lock:
                self._last_error = "capture sample rate changed"
                self._live = False
            return
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        try:
            self._send_queue.put_nowait(pcm)
        except queue.Full:
            with self._lock:
                self._dropped_chunks += 1

    def stop(self) -> None:
        with self._lock:
            ws = self._socket
            self._socket = None
            self._live = False
            self._sample_rate = 0
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.stop()
        gateway = self._gateway
        self._gateway = None
        if gateway is not None and gateway.poll() is None:
            gateway.terminate()
            try:
                gateway.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                gateway.kill()
                gateway.wait(timeout=2.0)
