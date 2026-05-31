"""Smoke tests for the Logs feature: catalog, CSV rotation, JSON broadcaster UDP."""
import csv
import json
import os
import socket
import threading
import time

import pytest

from src.comms.log_fields import (
    ALL_TOPICS, FIELD_INDEX, LOG_FIELD_GROUPS, resolve_path,
)
from src.comms.logger_process import (
    CsvLoggerTask, JsonBroadcasterTask, _period_seconds, _now_iso,
)
from src.core.models import CsvLoggerConfig, JsonBroadcasterConfig


# ── catalog ──────────────────────────────────────────────────────────────
def test_catalog_groups_have_unique_ids():
    seen = set()
    for g in LOG_FIELD_GROUPS:
        assert g["id"] and g["label"]
        for f in g["fields"]:
            assert f["id"] not in seen, f"duplicate id {f['id']}"
            seen.add(f["id"])
            assert f["topic"] in ALL_TOPICS
            assert f["id"] in FIELD_INDEX


def test_resolve_path_simple_and_nested():
    payload = {"lat": 39.5, "config": {"cruise_speed_kn": 3.2}}
    assert resolve_path(payload, "lat") == 39.5
    assert resolve_path(payload, "config.cruise_speed_kn") == 3.2
    assert resolve_path(payload, "missing") is None
    assert resolve_path(None, "anything") is None


def test_period_seconds():
    assert _period_seconds(1.0, "hz") == pytest.approx(1.0)
    assert _period_seconds(10.0, "hz") == pytest.approx(0.1)
    assert _period_seconds(2.0, "s") == pytest.approx(2.0)


def test_now_iso_format():
    s = _now_iso()
    # YYYY-MM-DDTHH:MM:SS.mmmZ
    assert len(s) == 24
    assert s.endswith("Z")
    assert s[10] == "T"


# ── CSV logger ───────────────────────────────────────────────────────────
def test_csv_logger_writes_header_and_rotates(tmp_path):
    # Pick any two real fields so the header includes [unit] formatting
    field_ids = [f["id"] for f in LOG_FIELD_GROUPS[0]["fields"][:2]]
    cfg = CsvLoggerConfig(
        id="t1", name="unit_test", enabled=True,
        frequency_value=20.0, frequency_unit="hz",  # 50 ms period
        rotation_hours=2.0 / 3600.0,                # rotate after 2 s
        output_path=str(tmp_path), fields=field_ids,
    )
    snaps = {}
    lock = threading.Lock()
    # Pre-populate snapshots so resolve never returns None for first field
    for fid in field_ids:
        topic = FIELD_INDEX[fid]["topic"]
        snaps[topic] = {FIELD_INDEX[fid]["path"].split(".")[0]: 1.23}

    task = CsvLoggerTask(cfg, snaps, lock)
    task.start()
    time.sleep(3.0)   # enough to write rows + cause at least 1 rotation
    task.stop()
    task.join(timeout=2.0)

    files = sorted(p for p in os.listdir(tmp_path) if p.endswith(".csv"))
    assert len(files) >= 2, f"expected rotation, got: {files}"

    # First file: header must include "timestamp_utc" + label([unit]) for each
    with open(tmp_path / files[0], newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0] == "timestamp_utc"
    assert len(rows[0]) == 1 + len(field_ids)
    assert len(rows) >= 2  # header + at least one data row


# ── JSON broadcaster (UDP) ───────────────────────────────────────────────
def test_json_broadcaster_udp_loopback(tmp_path):
    # Bind a UDP receiver on an ephemeral port
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    port = rx.getsockname()[1]

    field_id = LOG_FIELD_GROUPS[0]["fields"][0]["id"]
    topic = FIELD_INDEX[field_id]["topic"]
    cfg = JsonBroadcasterConfig(
        id="b1", name="udp_test", enabled=True,
        frequency_value=20.0, frequency_unit="hz",
        protocol="udp", host="127.0.0.1", port=port,
        fields=[field_id],
    )
    snaps = {topic: {FIELD_INDEX[field_id]["path"].split(".")[0]: 42.0}}
    lock = threading.Lock()
    task = JsonBroadcasterTask(cfg, snaps, lock)
    task.start()

    try:
        data, _ = rx.recvfrom(8192)
        payload = json.loads(data.decode("utf-8"))
        assert "timestamp_utc" in payload
        assert field_id in payload
    finally:
        task.stop()
        task.join(timeout=2.0)
        rx.close()
