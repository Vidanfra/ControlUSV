"""
LoggerProcess — hosts arbitrary CSV file loggers and JSON network broadcasters.

Subscribes to every telemetry topic referenced by LOG_FIELD_CATALOG and keeps
the latest payload per topic in memory. Each configured CSV logger (thread)
and JSON broadcaster (thread) reads from that snapshot at its own configured
period, resolves the requested fields via dot-paths, and writes/sends a row.

Loggers are reconfigured live via Topics.GNC_SYNC (ManagerProcess publishes
{op: "logging_config", logging_config: {...}} whenever the operator pushes a
new LoggingConfig).
"""
import csv
import json
import math
import os
import socket
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger

from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import (
    CsvLoggerConfig,
    JsonBroadcasterConfig,
    LoggingConfig,
)
from src.core.process import ServiceProcess
from src.comms.log_fields import ALL_TOPICS, FIELD_INDEX, resolve_path


_TIMESTAMP_FIELD = "timestamp_utc"
_MIN_FREE_MB = 100.0  # pause CSV logger if disk free space below this


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def _iso_for_filename(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _period_seconds(value: float, unit: str) -> float:
    unit = (unit or "hz").lower()
    if unit == "hz":
        return 1.0 / max(value, 1e-6)
    return max(float(value), 1e-3)  # "s"


# Field ids whose source payload is in radians but should be logged/broadcast
# as degrees (EKF state attitude/heading/course and GNC headings).
_RAD_TO_DEG_IDS = {
    "state_course", "state_heading", "state_roll", "state_pitch", "state_yaw",
    "gnc_target_heading", "gnc_heading_error",
}


def _resolve_field_value(field_id: str, snapshots: Dict[str, dict]):
    """Look up a field id in the catalog and resolve its value from snapshots."""
    fdef = FIELD_INDEX.get(field_id)
    if fdef is None:
        return None
    payload = snapshots.get(fdef["topic"])
    val = resolve_path(payload, fdef["path"])
    if val is not None and field_id in _RAD_TO_DEG_IDS:
        try:
            val = math.degrees(float(val))
        except (TypeError, ValueError):
            pass
    return val


# Field ids that need full floating-point precision (latitude / longitude).
# Every other float is rounded to 3 decimals to keep CSV files compact and
# JSON broadcast payloads small.
_FULL_PRECISION_IDS = {
    fid for fid, fdef in FIELD_INDEX.items()
    if fdef["path"].split(".")[-1] in ("lat", "lon")
}


def _format_value(field_id: str, value):
    """Round floats to 3 decimals unless the field is lat/lon. Non-floats pass through."""
    if value is None or not isinstance(value, float):
        return value
    if field_id in _FULL_PRECISION_IDS:
        return value
    # round(); avoid printing -0.0
    r = round(value, 3)
    return 0.0 if r == 0 else r


def _free_space_mb(path: str) -> float:
    try:
        st = os.statvfs(path) if hasattr(os, "statvfs") else None
        if st is not None:
            return (st.f_bavail * st.f_frsize) / (1024 * 1024)
    except Exception:
        pass
    # Windows fallback
    try:
        import shutil
        return shutil.disk_usage(path).free / (1024 * 1024)
    except Exception:
        return float("inf")


# ────────────────────────────────────────────────────────────────────────────
# CsvLoggerTask
# ────────────────────────────────────────────────────────────────────────────

class CsvLoggerTask(threading.Thread):
    """One CSV logger running as a daemon thread."""

    def __init__(self, cfg: CsvLoggerConfig, snapshots: Dict[str, dict],
                 snapshots_lock: threading.Lock):
        super().__init__(name=f"csv-{cfg.id}", daemon=True)
        self.cfg = cfg
        self.snapshots = snapshots
        self.snapshots_lock = snapshots_lock
        self.stop_event = threading.Event()
        self.period = _period_seconds(cfg.frequency_value, cfg.frequency_unit)
        self.fields = [_TIMESTAMP_FIELD] + list(cfg.fields)
        self.headers = [_TIMESTAMP_FIELD] + [
            (FIELD_INDEX[f]["label"] + (f" [{FIELD_INDEX[f]['unit']}]" if FIELD_INDEX[f]["unit"] else ""))
            if f in FIELD_INDEX else f
            for f in cfg.fields
        ]
        self._file = None
        self._writer = None
        self._current_path = None
        self._file_start_ts = 0.0
        self._file_rotation_ts = 0.0
        self._last_fsync = 0.0
        self.last_row: Dict[str, object] = {}  # for live preview
        self.paused_reason: Optional[str] = None

    # ── file lifecycle ────────────────────────────────────────────────────
    def _open_file(self, now: float):
        try:
            os.makedirs(self.cfg.output_path, exist_ok=True)
        except Exception as e:
            self.paused_reason = f"mkdir failed: {e}"
            logger.error(f"[Logger {self.cfg.name}] {self.paused_reason}")
            return False

        if _free_space_mb(self.cfg.output_path) < _MIN_FREE_MB:
            self.paused_reason = f"low disk space (<{_MIN_FREE_MB:.0f} MB)"
            logger.warning(f"[Logger {self.cfg.name}] {self.paused_reason}")
            return False

        self._file_start_ts = now
        self._file_rotation_ts = now + self.cfg.rotation_hours * 3600.0
        start_iso = _iso_for_filename(now)
        safe_name = "".join(c if (c.isalnum() or c in "-_") else "_" for c in self.cfg.name)
        fname = f"{safe_name}_{start_iso}.csv"
        self._current_path = os.path.join(self.cfg.output_path, fname)

        try:
            self._file = open(self._current_path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file, delimiter=",")
            self._writer.writerow(self.headers)
            self._file.flush()
            self.paused_reason = None
            logger.info(f"[Logger {self.cfg.name}] opened {self._current_path}")
            return True
        except Exception as e:
            self.paused_reason = f"open failed: {e}"
            logger.error(f"[Logger {self.cfg.name}] {self.paused_reason}")
            return False

    def _close_file(self, now: float):
        if self._file is None:
            return
        try:
            self._file.flush()
            self._file.close()
        except Exception:
            pass

        # Rename file: append actual close time to filename.
        # Original: <name>_<start_iso>.csv
        # After close: <name>_<start_iso>_<end_iso>.csv
        if self._current_path:
            actual_end_iso = _iso_for_filename(now)
            try:
                stem, ext = os.path.splitext(self._current_path)
                new_path = f"{stem}_{actual_end_iso}{ext}"
                if new_path != self._current_path and not os.path.exists(new_path):
                    os.rename(self._current_path, new_path)
                    self._current_path = new_path
            except Exception:
                pass
        self._file = None
        self._writer = None

    def _write_row(self, now: float):
        with self.snapshots_lock:
            snaps = self.snapshots  # dict reference — we read only
            row_vals = []
            preview = {}
            ts_str = _now_iso()
            preview[_TIMESTAMP_FIELD] = ts_str
            row_vals.append(ts_str)
            for fid in self.cfg.fields:
                val = _format_value(fid, _resolve_field_value(fid, snaps))
                preview[fid] = val
                row_vals.append("" if val is None else val)

        try:
            self._writer.writerow(row_vals)
            if now - self._last_fsync >= 5.0:
                self._file.flush()
                try:
                    os.fsync(self._file.fileno())
                except Exception:
                    pass
                self._last_fsync = now
            self.last_row = preview
        except Exception as e:
            logger.error(f"[Logger {self.cfg.name}] write failed: {e}")
            self._close_file(now)

    # ── main loop ─────────────────────────────────────────────────────────
    def run(self):
        next_tick = time.time()
        while not self.stop_event.is_set():
            now = time.time()
            if self._file is None:
                if not self._open_file(now):
                    # Back off; retry every 5 s
                    self.stop_event.wait(5.0)
                    continue

            if now >= self._file_rotation_ts:
                self._close_file(now)
                continue  # next iteration reopens

            self._write_row(now)

            next_tick += self.period
            sleep_for = next_tick - time.time()
            if sleep_for < -self.period:
                # We're more than one period behind; resync to avoid burst-catchup
                next_tick = time.time() + self.period
                sleep_for = self.period
            if sleep_for > 0:
                self.stop_event.wait(sleep_for)

        self._close_file(time.time())

    def stop(self):
        self.stop_event.set()


# ────────────────────────────────────────────────────────────────────────────
# JsonBroadcasterTask
# ────────────────────────────────────────────────────────────────────────────

class JsonBroadcasterTask(threading.Thread):
    """One UDP or TCP-server JSON broadcaster running as a daemon thread."""

    def __init__(self, cfg: JsonBroadcasterConfig, snapshots: Dict[str, dict],
                 snapshots_lock: threading.Lock):
        super().__init__(name=f"json-{cfg.id}", daemon=True)
        self.cfg = cfg
        self.snapshots = snapshots
        self.snapshots_lock = snapshots_lock
        self.stop_event = threading.Event()
        self.period = _period_seconds(cfg.frequency_value, cfg.frequency_unit)
        self.last_payload: dict = {}
        self.error: Optional[str] = None
        self._sock = None
        self._tcp_clients: List[socket.socket] = []

    # ── socket setup ──────────────────────────────────────────────────────
    def _open_socket(self) -> bool:
        try:
            if self.cfg.protocol == "udp":
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            elif self.cfg.protocol == "tcp":
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind((self.cfg.host, self.cfg.port))
                self._sock.listen(8)
                self._sock.setblocking(False)
            else:
                self.error = f"unknown protocol: {self.cfg.protocol}"
                return False
            self.error = None
            return True
        except Exception as e:
            self.error = f"socket open failed: {e}"
            logger.error(f"[Broadcaster {self.cfg.name}] {self.error}")
            return False

    def _accept_tcp(self):
        if self._sock is None:
            return
        try:
            while True:
                client, _ = self._sock.accept()
                client.setblocking(False)
                self._tcp_clients.append(client)
                logger.info(f"[Broadcaster {self.cfg.name}] TCP client connected ({len(self._tcp_clients)} total)")
        except BlockingIOError:
            pass
        except Exception:
            pass

    def _send(self, data: bytes):
        if self.cfg.protocol == "udp":
            try:
                self._sock.sendto(data, (self.cfg.host, self.cfg.port))
            except Exception as e:
                self.error = f"UDP send failed: {e}"
        else:  # tcp
            self._accept_tcp()
            dead = []
            for c in self._tcp_clients:
                try:
                    c.sendall(data + b"\n")
                except Exception:
                    dead.append(c)
            for c in dead:
                try:
                    c.close()
                except Exception:
                    pass
                self._tcp_clients.remove(c)
            if dead:
                logger.info(f"[Broadcaster {self.cfg.name}] {len(dead)} TCP client(s) dropped")

    def _resolve_payload(self) -> dict:
        with self.snapshots_lock:
            snaps = self.snapshots
            payload = {_TIMESTAMP_FIELD: _now_iso()}
            for fid in self.cfg.fields:
                payload[fid] = _format_value(fid, _resolve_field_value(fid, snaps))
        return payload

    def run(self):
        if not self._open_socket():
            return
        next_tick = time.time()
        while not self.stop_event.is_set():
            now = time.time()
            payload = self._resolve_payload()
            self.last_payload = payload
            try:
                data = json.dumps(payload, default=str).encode("utf-8")
                self._send(data)
            except Exception as e:
                self.error = f"send failed: {e}"

            next_tick += self.period
            sleep_for = next_tick - time.time()
            if sleep_for < -self.period:
                next_tick = time.time() + self.period
                sleep_for = self.period
            if sleep_for > 0:
                self.stop_event.wait(sleep_for)

        # cleanup
        for c in self._tcp_clients:
            try: c.close()
            except Exception: pass
        if self._sock is not None:
            try: self._sock.close()
            except Exception: pass

    def stop(self):
        self.stop_event.set()


# ────────────────────────────────────────────────────────────────────────────
# LoggerProcess
# ────────────────────────────────────────────────────────────────────────────

class LoggerProcess(ServiceProcess):
    """
    Service process hosting all CSV loggers and JSON broadcasters.

    Loop ticks at 50 Hz: drains every subscribed ZMQ topic into the latest-
    payload snapshot, applies any pending LoggingConfig from the manager, and
    publishes live preview rows on Topics.LOGGER_PREVIEW for any loggers /
    broadcasters that the frontend has opened a preview on.
    """

    def setup(self):
        # Subscribe to every telemetry topic that the catalog references
        topic_enums = [t for t in Topics if t.value in ALL_TOPICS]
        # Also listen for logging_config updates from the manager
        topic_enums.append(Topics.GNC_SYNC)
        # And for direct LOGGER_*_PREVIEW commands
        topic_enums.append(Topics.COMMAND_USER)
        self.sub = Subscriber(topic_enums)
        self.preview_pub = Publisher(Topics.LOGGER_PREVIEW)

        self.snapshots: Dict[str, dict] = {}
        self.snapshots_lock = threading.Lock()

        self.csv_tasks: Dict[str, CsvLoggerTask] = {}
        self.json_tasks: Dict[str, JsonBroadcasterTask] = {}
        self.current_config = LoggingConfig()

        # Live-preview registrations: id → unix-timestamp (last open or refresh)
        # Previews auto-stop after 10 s of no refresh from the frontend.
        self.previews: Dict[str, float] = {}
        self._last_preview_publish = 0.0
        logger.info("LoggerProcess initialized")

    def cleanup(self):
        for t in list(self.csv_tasks.values()) + list(self.json_tasks.values()):
            t.stop()
        for t in list(self.csv_tasks.values()) + list(self.json_tasks.values()):
            try: t.join(timeout=2.0)
            except Exception: pass
        try: self.sub.close()
        except Exception: pass
        try: self.preview_pub.close()
        except Exception: pass

    # ── topic ingestion ──────────────────────────────────────────────────
    def loop(self):
        # Drain ZMQ messages (bounded so we always make progress)
        for _ in range(500):
            msg = self.sub.receive(timeout_ms=0)
            if msg is None:
                break
            topic, payload = msg

            if topic == Topics.GNC_SYNC.value:
                if isinstance(payload, dict) and payload.get("op") == "logging_config":
                    cfg_dict = payload.get("logging_config") or {}
                    self._apply_config(cfg_dict)
                continue

            if topic == Topics.COMMAND_USER.value:
                self._handle_command(payload)
                continue

            # Telemetry topic → snapshot
            with self.snapshots_lock:
                self.snapshots[topic] = payload

        # Publish previews (throttled to ~5 Hz so we never overwhelm WS clients)
        now = time.time()
        if self.previews and now - self._last_preview_publish >= 0.2:
            self._last_preview_publish = now
            # Drop stale previews (frontend stopped refreshing)
            self.previews = {k: t for k, t in self.previews.items() if now - t < 10.0}
            for key in list(self.previews.keys()):
                self._publish_preview(key)

    # ── command handling ──────────────────────────────────────────────────
    def _handle_command(self, payload: dict):
        try:
            ctype = payload.get("type")
            if ctype == "SET_LOGGING_CONFIG":
                self._apply_config(payload.get("payload", {}))
            elif ctype == "LOGGER_START_PREVIEW":
                pid = (payload.get("payload") or {}).get("id")
                if pid:
                    self.previews[pid] = time.time()
            elif ctype == "LOGGER_STOP_PREVIEW":
                pid = (payload.get("payload") or {}).get("id")
                if pid:
                    self.previews.pop(pid, None)
        except Exception as e:
            logger.warning(f"LoggerProcess: bad command: {e}")

    # ── config apply (full-replace) ───────────────────────────────────────
    def _apply_config(self, cfg_dict: dict):
        try:
            new_cfg = LoggingConfig(**(cfg_dict or {}))
        except Exception as e:
            logger.error(f"LoggerProcess: invalid LoggingConfig: {e}")
            return

        # CSV tasks
        new_ids = {c.id for c in new_cfg.csv_loggers}
        for tid in list(self.csv_tasks.keys()):
            if tid not in new_ids:
                self.csv_tasks[tid].stop()
                self.csv_tasks.pop(tid, None)
        existing_by_id = {c.id: c for c in self.current_config.csv_loggers}
        for c in new_cfg.csv_loggers:
            old = existing_by_id.get(c.id)
            changed = (old is None) or (old.model_dump() != c.model_dump())
            running = c.id in self.csv_tasks
            if not c.enabled:
                if running:
                    self.csv_tasks[c.id].stop()
                    self.csv_tasks.pop(c.id, None)
                continue
            if running and changed:
                self.csv_tasks[c.id].stop()
                self.csv_tasks.pop(c.id, None)
                running = False
            if not running:
                t = CsvLoggerTask(c, self.snapshots, self.snapshots_lock)
                t.start()
                self.csv_tasks[c.id] = t

        # JSON tasks
        new_ids_j = {c.id for c in new_cfg.json_broadcasters}
        for tid in list(self.json_tasks.keys()):
            if tid not in new_ids_j:
                self.json_tasks[tid].stop()
                self.json_tasks.pop(tid, None)
        existing_by_id_j = {c.id: c for c in self.current_config.json_broadcasters}
        for c in new_cfg.json_broadcasters:
            old = existing_by_id_j.get(c.id)
            changed = (old is None) or (old.model_dump() != c.model_dump())
            running = c.id in self.json_tasks
            if not c.enabled:
                if running:
                    self.json_tasks[c.id].stop()
                    self.json_tasks.pop(c.id, None)
                continue
            if running and changed:
                self.json_tasks[c.id].stop()
                self.json_tasks.pop(c.id, None)
                running = False
            if not running:
                t = JsonBroadcasterTask(c, self.snapshots, self.snapshots_lock)
                t.start()
                self.json_tasks[c.id] = t

        self.current_config = deepcopy(new_cfg)
        logger.info(f"LoggerProcess: applied config "
                    f"(csv={len(self.csv_tasks)}, json={len(self.json_tasks)})")

    # ── preview publishing ────────────────────────────────────────────────
    def _publish_preview(self, key: str):
        t = self.csv_tasks.get(key)
        if t is not None:
            self.preview_pub.publish({
                "id": key,
                "kind": "csv",
                "headers": t.headers,
                "fields": [_TIMESTAMP_FIELD] + list(t.cfg.fields),
                "row": t.last_row,
                "current_file": os.path.basename(t._current_path) if t._current_path else "",
                "paused": t.paused_reason,
                "ts": time.time(),
            })
            return
        b = self.json_tasks.get(key)
        if b is not None:
            self.preview_pub.publish({
                "id": key,
                "kind": "json",
                "payload": b.last_payload,
                "error": b.error,
                "protocol": b.cfg.protocol,
                "host": b.cfg.host,
                "port": b.cfg.port,
                "ts": time.time(),
            })
