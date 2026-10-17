#!/usr/bin/env python3
"""Beacon Computing Initiative — isolated audio hardware boundary.

This module owns PortAudio *input* discovery/open/capture in a dedicated child
process.  The Qt/UI process never enumerates or opens capture devices through
sounddevice.  If a native PortAudio/ALSA/PipeWire call wedges, the supervisor
can terminate the child process and create a clean audio runtime without
blocking the GUI or DSP worker.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import platform
import re
import queue
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

BOUNDARY_PROTOCOL_VERSION = 1
DEFAULT_HEARTBEAT_INTERVAL = 0.50
DEFAULT_WATCHDOG_SECONDS = 7.0
DEFAULT_ROUTE_CHECK_SECONDS = 2.0
DEFAULT_CALLBACK_QUEUE_BLOCKS = 96
DEFAULT_AUDIO_QUEUE_BLOCKS = 96
DEFAULT_FIRST_FRAME_SECONDS = 4.0
DEFAULT_STALL_SECONDS = 4.0


def _safe_capture_name(device_name: Any) -> bool:
    name = str(device_name or "").strip().lower()
    if name in {
        "upmix",
        "vdownmix",
        "lavrate",
        "samplerate",
        "speexrate",
        "speex",
    }:
        return False
    if ".monitor" in name or name.endswith(" monitor"):
        return False
    if name.startswith("bluez_output."):
        return False
    return True


def _stable_capture_identity(device_name: Any) -> str:
    """Normalize volatile ALSA card/device numbering out of an endpoint name.

    PortAudio indices and ALSA ``hw:X,Y`` coordinates are runtime locators, not
    hardware identity. BlueZ MAC material is intentionally preserved.
    """
    name = " ".join(str(device_name or "").strip().casefold().split())
    name = re.sub(r"\((?:plug)?hw:\d+,\d+\)", "", name)
    name = re.sub(r"(?<![a-z])(?:plug)?hw:\d+,\d+(?![a-z])", "", name)
    return " ".join(name.split()).strip(" -:")


def _plain_devices(sd) -> List[Dict[str, Any]]:
    raw = sd.query_devices()
    out: List[Dict[str, Any]] = []
    for item in raw:
        try:
            out.append(dict(item))
        except Exception:
            out.append(
                {
                    "name": str(getattr(item, "name", "")),
                    "max_input_channels": int(
                        getattr(item, "max_input_channels", 0) or 0
                    ),
                    "max_output_channels": int(
                        getattr(item, "max_output_channels", 0) or 0
                    ),
                    "default_samplerate": float(
                        getattr(item, "default_samplerate", 0.0) or 0.0
                    ),
                    "hostapi": int(getattr(item, "hostapi", -1)),
                }
            )
    return out


def _paired_bluetooth_devices() -> List[Dict[str, Any]]:
    if platform.system().lower() != "linux":
        return []
    bluetoothctl = shutil.which("bluetoothctl")
    if not bluetoothctl:
        return []

    try:
        result = subprocess.run(
            [bluetoothctl, "devices", "Paired"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return []

    devices: List[Dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith("Device "):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        address = parts[1].strip().upper()
        name = parts[2].strip() if len(parts) >= 3 else address
        connected = False
        try:
            info = subprocess.run(
                [bluetoothctl, "info", address],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            connected = "Connected: yes" in info.stdout
        except Exception:
            connected = False
        devices.append(
            {
                "address": address,
                "name": name,
                "connected": connected,
            }
        )
    return devices


def _linux_default_source_name() -> str:
    if platform.system().lower() != "linux":
        return ""
    pactl = shutil.which("pactl")
    if not pactl:
        return ""
    try:
        result = subprocess.run(
            [pactl, "get-default-source"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _linux_sources_signature() -> str:
    """Cheap topology signal that does not touch PortAudio."""
    if platform.system().lower() != "linux":
        return ""
    pactl = shutil.which("pactl")
    if not pactl:
        return ""
    try:
        result = subprocess.run(
            [pactl, "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if result.returncode != 0:
            return ""
        rows = []
        for raw in result.stdout.splitlines():
            fields = raw.split("\t")
            if len(fields) >= 2:
                rows.append(fields[1].strip())
        return "|".join(sorted(rows))
    except Exception:
        return ""


def _default_signature(sd, devices: List[Dict[str, Any]]) -> str:
    os_default = _linux_default_source_name()
    pa_default = ""
    try:
        idx = int(sd.default.device[0])
        if 0 <= idx < len(devices):
            pa_default = str(devices[idx].get("name", ""))
    except Exception:
        pa_default = ""
    return f"{os_default}|{pa_default}"


def _fingerprint(
    devices: List[Dict[str, Any]],
    paired_devices: List[Dict[str, Any]],
) -> Tuple[Any, ...]:
    fingerprint = []
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0) or 0) <= 0:
            continue
        name = str(device.get("name", ""))
        if not _safe_capture_name(name):
            continue
        lowered = name.lower()
        if "usb" not in lowered and not lowered.startswith("bluez_input."):
            continue
        try:
            rate = int(float(device.get("default_samplerate", 0) or 0))
        except Exception:
            rate = 0
        fingerprint.append(
            (
                int(index),
                name,
                int(device.get("max_input_channels", 0) or 0),
                rate,
            )
        )
    paired = tuple(
        (
            str(item.get("address", "")),
            str(item.get("name", "")),
            bool(item.get("connected", False)),
        )
        for item in paired_devices
    )
    return (tuple(fingerprint), paired)


def _make_snapshot(sd) -> Dict[str, Any]:
    # IMPORTANT: one immutable PortAudio enumeration per transaction.
    devices = _plain_devices(sd)
    paired = _paired_bluetooth_devices()
    return {
        "devices": devices,
        "paired_devices": paired,
        "fingerprint": _fingerprint(devices, paired),
        "default_signature": _default_signature(sd, devices),
        "probed_at": time.monotonic(),
    }


def _candidate_ids(
    sd,
    devices: List[Dict[str, Any]],
    selection: Dict[str, Any],
    excluded_device_ids: Iterable[int] = (),
) -> List[int]:
    candidates: List[int] = []
    excluded = {int(item) for item in excluded_device_ids}

    def add(index: Any) -> None:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if (
            index < 0
            or index >= len(devices)
            or index in candidates
            or index in excluded
        ):
            return
        info = devices[index]
        if int(info.get("max_input_channels", 0) or 0) <= 0:
            return
        if not _safe_capture_name(info.get("name", "")):
            return
        candidates.append(index)

    mode = str(selection.get("mode", "auto") or "auto").lower()
    requested_name = str(selection.get("device_name", "") or "").strip()
    requested_id = selection.get("device_id", -1)

    if mode == "explicit":
        # Stable name is authoritative. Runtime PortAudio index is only a hint.
        if requested_name:
            exact = requested_name.casefold()
            for index, info in enumerate(devices):
                if str(info.get("name", "")).strip().casefold() == exact:
                    add(index)
            if candidates:
                return candidates

            # USB/BlueZ names occasionally gain harmless whitespace/case changes.
            normalized = " ".join(requested_name.casefold().split())
            for index, info in enumerate(devices):
                name = " ".join(
                    str(info.get("name", "")).strip().casefold().split()
                )
                if name == normalized:
                    add(index)
            if candidates:
                return candidates

            # ALSA card numbers are volatile across unplug/replug. Rebind only
            # when exactly one endpoint has the same normalized hardware name.
            stable_wanted = _stable_capture_identity(requested_name)
            stable_matches = []
            if stable_wanted:
                for index, info in enumerate(devices):
                    if (
                        _stable_capture_identity(info.get("name", ""))
                        == stable_wanted
                    ):
                        stable_matches.append(index)
            if len(stable_matches) == 1:
                add(stable_matches[0])
                return candidates

        # If a stable name was supplied and is absent, wait for that same
        # physical/logical endpoint. Never reinterpret a stale PortAudio index
        # as a different microphone. Legacy ID fallback is used only when no
        # stable name exists at all.
        if not requested_name:
            add(requested_id)
        return candidates

    # System Default / AUTO. Prefer route aliases that follow the OS mixer.
    preferred_names = (
        "pipewire",
        "pulse",
        "default source",
        "default",
    )
    for preferred in preferred_names:
        for index, info in enumerate(devices):
            if str(info.get("name", "")).strip().casefold() == preferred:
                add(index)

    try:
        add(sd.default.device[0])
    except Exception:
        pass
    return candidates


def _put_latest(q, item) -> None:
    try:
        q.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        q.get_nowait()
    except Exception:
        pass
    try:
        q.put_nowait(item)
    except Exception:
        pass


def _capture_process_main(
    command_queue,
    event_queue,
    audio_queue,
    initial_selection: Dict[str, Any],
    block_size: int,
    heartbeat_interval: float,
    route_check_seconds: float,
) -> None:
    """Child process: sole owner of PortAudio input discovery/open/callback."""
    import sounddevice as sd  # intentionally child-only input ownership

    selection = dict(initial_selection or {})
    selection.setdefault("mode", "auto")
    callback_queue: "queue.Queue[Tuple[bytes, int, str]]" = queue.Queue(
        maxsize=DEFAULT_CALLBACK_QUEUE_BLOCKS
    )

    stream = None
    active_meta: Optional[Dict[str, Any]] = None
    last_snapshot: Optional[Dict[str, Any]] = None
    running = True
    reopen_requested = True
    refresh_requested = True
    last_heartbeat = 0.0
    last_route_check = 0.0
    last_route_signature = ""
    generation = 0
    callback_drop_count = 0
    stream_opened_at = 0.0
    last_callback_at = 0.0
    failed_auto_candidates = set()
    retry_delay = 1.0
    next_retry_at = 0.0
    last_sources_signature = _linux_sources_signature()

    def emit(kind: str, **payload: Any) -> None:
        message = {
            "type": kind,
            "protocol": BOUNDARY_PROTOCOL_VERSION,
            "pid": os.getpid(),
            "at": time.monotonic(),
        }
        message.update(payload)
        _put_latest(event_queue, message)

    def close_stream(reason: str = "") -> None:
        nonlocal stream, active_meta
        old_meta = active_meta
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        stream = None
        active_meta = None
        while True:
            try:
                callback_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
        if old_meta is not None and reason:
            emit(
                "stream_closed",
                reason=reason,
                generation=int(old_meta.get("generation", generation)),
            )

    def callback(indata, frames, time_info, status) -> None:
        nonlocal callback_drop_count, last_callback_at
        try:
            last_callback_at = time.monotonic()
            samples = np.asarray(indata, dtype=np.float32)
            if samples.ndim == 1:
                samples = samples.reshape(-1, 1)
            if samples.size <= 0 or samples.shape[1] <= 0:
                return
            mono = np.ascontiguousarray(samples[:, :1], dtype=np.float32)
            item = (
                mono.tobytes(order="C"),
                int(mono.shape[0]),
                str(status) if status else "",
            )
            try:
                callback_queue.put_nowait(item)
            except queue.Full:
                callback_drop_count += 1
        except Exception:
            return

    def refresh_snapshot() -> Dict[str, Any]:
        nonlocal last_snapshot, last_route_signature
        snapshot = _make_snapshot(sd)
        last_snapshot = snapshot
        last_route_signature = str(snapshot.get("default_signature", ""))
        emit("snapshot", snapshot=snapshot)
        return snapshot

    def open_stream() -> None:
        nonlocal stream, active_meta, generation, reopen_requested, refresh_requested
        nonlocal stream_opened_at, last_callback_at, retry_delay, next_retry_at
        nonlocal failed_auto_candidates
        close_stream("")
        snapshot = refresh_snapshot()
        devices = list(snapshot.get("devices", []) or [])
        mode = str(selection.get("mode", "auto") or "auto").lower()
        candidates = _candidate_ids(
            sd,
            devices,
            selection,
            excluded_device_ids=(
                failed_auto_candidates if mode == "auto" else ()
            ),
        )
        if not candidates and mode == "auto" and failed_auto_candidates:
            # All aliases were retired in this pass. Start a fresh pass after
            # backoff so a recovered default route can be reconsidered.
            failed_auto_candidates.clear()
            candidates = _candidate_ids(sd, devices, selection)

        if not candidates:
            if str(selection.get("mode", "auto")) == "explicit":
                wanted = str(selection.get("device_name", "") or "selected microphone")
                emit(
                    "waiting",
                    message=f"Selected microphone unavailable: {wanted}",
                )
            else:
                emit("waiting", message="System Default microphone unavailable")
            reopen_requested = False
            refresh_requested = False
            next_retry_at = time.monotonic() + retry_delay
            retry_delay = min(retry_delay * 2.0, 8.0)
            return

        errors: List[str] = []
        for device_id in candidates:
            info = devices[device_id]
            name = str(info.get("name", f"Device {device_id}"))
            try:
                default_rate = int(
                    float(info.get("default_samplerate", 48000) or 48000)
                )
            except Exception:
                default_rate = 48000
            rates: List[int] = []
            for rate in (default_rate, 48000, 44100):
                if rate > 0 and rate not in rates:
                    rates.append(rate)

            for rate in rates:
                try:
                    sd.check_input_settings(
                        device=device_id,
                        channels=1,
                        samplerate=rate,
                        dtype="float32",
                    )
                    candidate_stream = sd.InputStream(
                        device=device_id,
                        channels=1,
                        samplerate=rate,
                        blocksize=int(block_size),
                        dtype="float32",
                        latency="high",
                        callback=callback,
                    )
                    candidate_stream.start()
                    generation += 1
                    stream = candidate_stream
                    stream_opened_at = time.monotonic()
                    last_callback_at = 0.0
                    retry_delay = 1.0
                    next_retry_at = 0.0
                    active_meta = {
                        "generation": generation,
                        "device_id": int(device_id),
                        "device_name": name,
                        "sample_rate": int(rate),
                        "selection_mode": str(selection.get("mode", "auto")),
                    }
                    emit("stream_opened", **active_meta)
                    emit(
                        "status",
                        message=(
                            f"AUDIO BOUNDARY -> {device_id}: {name} @ {rate} Hz "
                            "[ISOLATED PORTAUDIO PROCESS]"
                        ),
                        success=True,
                    )
                    reopen_requested = False
                    refresh_requested = False
                    return
                except Exception as exc:
                    errors.append(f"{device_id}:{name} @ {rate} Hz -> {exc}")
                    lowered = str(exc).lower()
                    if (
                        "device unavailable" in lowered
                        or "-9985" in lowered
                        or "invalid device" in lowered
                    ):
                        break

        emit(
            "open_error",
            message=(
                "Unable to open an input device. "
                + (" | ".join(errors[-6:]) if errors else "No candidates")
            ),
        )
        reopen_requested = False
        refresh_requested = False
        next_retry_at = time.monotonic() + retry_delay
        retry_delay = min(retry_delay * 2.0, 8.0)

    emit("process_started", message="BCI isolated audio process started")

    try:
        while running:
            now = time.monotonic()

            if now - last_heartbeat >= heartbeat_interval:
                last_heartbeat = now
                emit("heartbeat", generation=generation)

            # Commands are consumed only by this child, so capture selection and
            # PortAudio lifecycle have one authority.
            while True:
                try:
                    command = command_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    command = None
                    break

                if not isinstance(command, dict):
                    continue
                kind = str(command.get("type", ""))
                if kind == "shutdown":
                    running = False
                    break
                if kind == "select":
                    selection = {
                        "mode": str(command.get("mode", "auto") or "auto"),
                        "device_name": str(command.get("device_name", "") or ""),
                        "device_id": int(command.get("device_id", -1)),
                    }
                    reopen_requested = True
                    refresh_requested = True
                elif kind == "refresh":
                    # A manual refresh is an orderly boundary transaction: close,
                    # enumerate once, then reopen. No second PortAudio owner exists.
                    reopen_requested = True
                    refresh_requested = True
                elif kind == "reopen":
                    reopen_requested = True
                elif kind == "ping":
                    emit("heartbeat", generation=generation)

            if not running:
                break

            if (
                stream is None
                and not reopen_requested
                and next_retry_at > 0.0
                and now >= next_retry_at
            ):
                reopen_requested = True

            if reopen_requested:
                close_stream("boundary_reopen")
                open_stream()

            # Drain callback frames and publish them to the parent. The callback
            # itself never touches multiprocessing primitives.
            drained = 0
            while drained < 16:
                try:
                    pcm_bytes, frame_count, callback_status = callback_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
                # A real callback proves this candidate is live.
                failed_auto_candidates.clear()
                packet = {
                    "generation": int(
                        (active_meta or {}).get("generation", generation)
                    ),
                    "sample_rate": int(
                        (active_meta or {}).get("sample_rate", 0)
                    ),
                    "frames": int(frame_count),
                    "status": callback_status,
                    "pcm": pcm_bytes,
                }
                _put_latest(audio_queue, packet)
                drained += 1

            if callback_drop_count:
                emit(
                    "callback_drop",
                    dropped=int(callback_drop_count),
                )
                callback_drop_count = 0

            # Inactive/no-frame/stalled streams are controlled losses. The
            # boundary, not Qt or the DSP worker, owns candidate retirement.
            if stream is not None:
                try:
                    stream_active = bool(stream.active)
                except Exception:
                    stream_active = False

                loss_reason = ""
                if not stream_active:
                    loss_reason = "PortAudio input stream became inactive"
                elif last_callback_at <= 0.0:
                    if now - stream_opened_at >= DEFAULT_FIRST_FRAME_SECONDS:
                        loss_reason = (
                            "PortAudio stream opened but delivered no frames "
                            f"for {DEFAULT_FIRST_FRAME_SECONDS:.1f}s"
                        )
                elif now - last_callback_at >= DEFAULT_STALL_SECONDS:
                    loss_reason = (
                        "PortAudio callback stalled for "
                        f"{now - last_callback_at:.1f}s"
                    )

                if loss_reason:
                    meta = dict(active_meta or {})
                    lost_id = int(meta.get("device_id", -1))
                    if (
                        str(selection.get("mode", "auto")).lower() == "auto"
                        and lost_id >= 0
                    ):
                        failed_auto_candidates.add(lost_id)
                    close_stream("stream_lost")
                    emit(
                        "stream_lost",
                        reason=loss_reason,
                        generation=int(meta.get("generation", generation)),
                    )
                    next_retry_at = time.monotonic() + retry_delay
                    retry_delay = min(retry_delay * 2.0, 8.0)
                    reopen_requested = False

            # AUTO default-route monitoring uses pactl/CoreAudio/WASAPI metadata;
            # it does NOT enumerate PortAudio while a capture stream is live.
            if now - last_route_check >= route_check_seconds:
                last_route_check = now
                mode = str(selection.get("mode", "auto") or "auto").lower()
                current_sources = _linux_sources_signature()
                sources_changed = bool(
                    current_sources
                    and last_sources_signature
                    and current_sources != last_sources_signature
                )
                if current_sources:
                    last_sources_signature = current_sources

                current_os_default = _linux_default_source_name()
                previous_os_default = last_route_signature.split("|", 1)[0]
                default_changed = bool(
                    current_os_default
                    and previous_os_default
                    and current_os_default != previous_os_default
                )

                if stream is not None and (sources_changed or (mode == "auto" and default_changed)):
                    reason = (
                        "System audio source topology changed"
                        if sources_changed
                        else (
                            f"System default source changed: "
                            f"{previous_os_default} -> {current_os_default}"
                        )
                    )
                    emit("route_changed", message=reason)
                    reopen_requested = True

            time.sleep(0.01)

    except BaseException as exc:
        emit("process_error", message=f"Audio process fatal error: {exc!r}")
    finally:
        close_stream("shutdown")
        emit("process_stopped", message="BCI isolated audio process stopped")


@dataclass
class BoundaryPollResult:
    events: List[Dict[str, Any]]
    audio: List[Dict[str, Any]]
    restarted: bool = False
    restart_reason: str = ""


class BCIAudioCaptureSupervisor:
    """Parent-side lifecycle manager for the isolated capture process."""

    def __init__(
        self,
        *,
        block_size: int,
        watchdog_seconds: float = DEFAULT_WATCHDOG_SECONDS,
    ) -> None:
        self.block_size = int(block_size)
        self.watchdog_seconds = float(watchdog_seconds)
        self._ctx = mp.get_context("spawn")
        self._process = None
        self._command_queue = None
        self._event_queue = None
        self._audio_queue = None
        self._selection: Dict[str, Any] = {
            "mode": "auto",
            "device_name": "",
            "device_id": -1,
        }
        self._last_heartbeat = 0.0
        self._last_start = 0.0
        self._restart_count = 0

    @property
    def pid(self) -> Optional[int]:
        process = self._process
        return int(process.pid) if process is not None and process.pid else None

    @property
    def selection(self) -> Dict[str, Any]:
        return dict(self._selection)

    def _new_runtime(self) -> None:
        self._command_queue = self._ctx.Queue(maxsize=32)
        self._event_queue = self._ctx.Queue(maxsize=128)
        self._audio_queue = self._ctx.Queue(maxsize=DEFAULT_AUDIO_QUEUE_BLOCKS)
        self._process = self._ctx.Process(
            target=_capture_process_main,
            name="BCI-AudioHardware",
            args=(
                self._command_queue,
                self._event_queue,
                self._audio_queue,
                dict(self._selection),
                self.block_size,
                DEFAULT_HEARTBEAT_INTERVAL,
                DEFAULT_ROUTE_CHECK_SECONDS,
            ),
            daemon=True,
        )
        self._process.start()
        self._last_start = time.monotonic()
        self._last_heartbeat = self._last_start

    def start(self, selection: Optional[Dict[str, Any]] = None) -> None:
        if selection:
            self._selection.update(selection)
        if self._process is not None and self._process.is_alive():
            return
        self._new_runtime()

    def send(self, command: Dict[str, Any]) -> None:
        kind = str(command.get("type", ""))
        if kind == "select":
            self._selection = {
                "mode": str(command.get("mode", "auto") or "auto"),
                "device_name": str(command.get("device_name", "") or ""),
                "device_id": int(command.get("device_id", -1)),
            }
        if self._command_queue is None:
            return
        try:
            self._command_queue.put_nowait(dict(command))
        except queue.Full:
            # Control commands are idempotent. Drop one stale command and keep
            # the newest operator intent.
            try:
                self._command_queue.get_nowait()
            except Exception:
                pass
            try:
                self._command_queue.put_nowait(dict(command))
            except Exception:
                pass

    def poll(self, max_events: int = 64, max_audio: int = 64) -> BoundaryPollResult:
        events: List[Dict[str, Any]] = []
        audio: List[Dict[str, Any]] = []
        if self._event_queue is not None:
            for _ in range(max_events):
                try:
                    item = self._event_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
                if isinstance(item, dict):
                    events.append(item)
                    if item.get("type") == "heartbeat":
                        self._last_heartbeat = time.monotonic()
        if self._audio_queue is not None:
            for _ in range(max_audio):
                try:
                    item = self._audio_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
                if isinstance(item, dict):
                    audio.append(item)
        return BoundaryPollResult(events=events, audio=audio)

    def watchdog_expired(self) -> Tuple[bool, str]:
        process = self._process
        if process is None:
            return True, "audio process missing"
        if not process.is_alive():
            return True, f"audio process exited with code {process.exitcode}"
        age = time.monotonic() - self._last_heartbeat
        if age > self.watchdog_seconds:
            return True, f"audio process heartbeat stalled for {age:.1f}s"
        return False, ""

    def restart(self, reason: str) -> None:
        self._restart_count += 1
        self._terminate_runtime()
        self._new_runtime()

    def _terminate_runtime(self) -> None:
        process = self._process
        if process is not None:
            if process.is_alive() and self._command_queue is not None:
                try:
                    self._command_queue.put_nowait({"type": "shutdown"})
                except Exception:
                    pass
                process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2.0)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=1.0)
        for q in (self._command_queue, self._event_queue, self._audio_queue):
            if q is not None:
                try:
                    q.close()
                except Exception:
                    pass
        self._process = None
        self._command_queue = None
        self._event_queue = None
        self._audio_queue = None

    def stop(self) -> None:
        self._terminate_runtime()


__all__ = [
    "BOUNDARY_PROTOCOL_VERSION",
    "BCIAudioCaptureSupervisor",
    "BoundaryPollResult",
]
