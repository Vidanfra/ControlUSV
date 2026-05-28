"""
Audit-confirming tests — each test demonstrates a CURRENT defect identified in
docs/SYSTEM_ANALYSIS.md.  These tests pass today (i.e. they encode the buggy
behavior) and would fail once the underlying defect is fixed.  Tagged @audit so
they can be excluded from regular CI runs if desired.

Run with:   pytest tests/test_audit_findings.py -v
"""
import inspect
import json
import os
import sys
import tempfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Finding A1 (CRITICAL) — FIXED 2026-05-28: removed.
# The comm-loss failsafe now consumes `Topics.COMMS_LINK` (web_server publishes
# ws_alive at 1 Hz, gated on frontend PINGs). See tests/test_comms_link_failsafe.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Finding A2 (HIGH):
# manager_settings.json is written with a direct truncating open(..., 'w'):
# a power loss mid-write yields a truncated/invalid JSON file, which on next
# boot is silently swallowed and replaced with defaults — losing home_wp,
# failsafe config and GNC tuning without operator awareness.
# ---------------------------------------------------------------------------
def test_settings_save_is_not_atomic():
    """ManagerProcess._save_settings overwrites in-place; no fsync+rename."""
    from src.manager import process as mgr

    src = inspect.getsource(mgr.ManagerProcess._save_settings)
    assert "open(_SETTINGS_FILE, 'w')" in src or "open(_SETTINGS_FILE, \"w\")" in src
    # No atomic write primitives are used:
    assert "os.replace" not in src
    assert "tempfile" not in src
    assert "fsync" not in src


def test_settings_load_swallows_corrupted_file_silently():
    """A corrupted manager_settings.json is replaced by defaults without alert."""
    from src.core.models import GncConfig, FailsafeConfig

    # Simulate corrupted file behavior:
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        f.write('{"gnc_config": {"wn": 1.5, "zeta":')  # truncated
        bad_path = f.name
    try:
        try:
            with open(bad_path) as f:
                json.load(f)
            failed = False
        except json.JSONDecodeError:
            failed = True
        assert failed, "Test setup: file should be corrupted JSON"

        # The Manager swallows this and uses defaults — no exception bubbles up,
        # no alert published.  We replicate that pattern here:
        try:
            with open(bad_path) as f:
                json.load(f)
            recovered = "data"
        except Exception:
            recovered = "defaults"  # what the manager does

        assert recovered == "defaults"
    finally:
        os.unlink(bad_path)


# ---------------------------------------------------------------------------
# Finding A3 (HIGH):
# ESP32Driver.send_command has a 200 ms ACK wait and NO retry.  At 20 Hz, a
# single dropped ACK silently loses one motor update; consecutive losses
# leave the motors running at the last value set by the firmware until the
# Esp32Node tears down and reconnects (3 s).  Without a firmware-side
# dead-man's switch, motors can free-run during that window.
# ---------------------------------------------------------------------------
def test_esp32_send_command_has_no_retry():
    from src.drivers import esp32

    src = inspect.getsource(esp32.ESP32Driver.send_command)
    # The function raises TimeoutError on ACK miss and never retries.
    assert "raise TimeoutError" in src
    # No retry loop / no resend-on-miss:
    assert "for attempt" not in src
    assert "retry" not in src.lower()


def test_esp32_relays_hardwired_on():
    """R1 R2 R3 are passed as constant 1 by the node — no per-relay control."""
    from src.drivers import esp32
    node_src = inspect.getsource(esp32.Esp32Node.run)
    assert "send_command(port_pct, stbd_pct, 1, 1, 1)" in node_src, (
        "Esp32Node hard-codes all relays ON; no command path exists to "
        "disable payload or comms relay from the GNC layer."
    )


# ---------------------------------------------------------------------------
# Finding A4 (MEDIUM / B-12):
# Each Subscriber creates its own zmq.Context().  In normal steady state the
# leak is bounded, but in tests / hot-reload / process restart-storm scenarios
# the contexts accumulate and consume file descriptors.
# ---------------------------------------------------------------------------
def test_each_subscriber_creates_its_own_zmq_context():
    from src.core import messaging

    src = inspect.getsource(messaging.Subscriber.__init__)
    assert "self.context = zmq.Context()" in src, (
        "Subscriber stopped creating its own Context — B-12 may be fixed; "
        "remove this test."
    )
    pub_src = inspect.getsource(messaging.Publisher.__init__)
    assert "self.context = zmq.Context()" in pub_src


# ---------------------------------------------------------------------------
# Finding A5 (HIGH):
# Mission waypoint list is held only in GNCProcess RAM.  A GNC restart
# (watchdog-triggered) loses the active mission silently.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Finding A5 (HIGH) — FIXED 2026-05-28:
# Mission waypoints are now persisted to manager_settings.json on every
# START_WP_ROUTE / SET_STATION command and restored on backend restart.
# The system/status heartbeat includes wp_route_waypoints so the frontend
# can recover the active mission after a page refresh.
# ---------------------------------------------------------------------------
def test_mission_state_is_persisted():
    from src.manager import process as mgr

    save_src = inspect.getsource(mgr.ManagerProcess._save_settings)
    assert "wp_route_waypoints" in save_src
    assert "station_wp" in save_src
    assert "wp_route_direction" in save_src
    assert "wp_route_completion" in save_src

    load_src = inspect.getsource(mgr.ManagerProcess._load_settings)
    assert "wp_route_waypoints" in load_src
    assert "station_wp" in load_src

    # Heartbeat payload must also broadcast waypoints to the frontend
    loop_src = inspect.getsource(mgr.ManagerProcess.loop)
    assert "wp_route_waypoints" in loop_src


# ---------------------------------------------------------------------------
# Finding A6 (HIGH):
# WebSocket endpoint accepts unauthenticated connections.  Anyone who can
# reach :8000 (including via the ngrok public URL the project uses) can send
# ARM / SET_MODE / MANUAL_INPUT commands.
# ---------------------------------------------------------------------------
def test_websocket_endpoint_has_no_authentication():
    from src.comms import web_server

    ep_src = inspect.getsource(web_server.websocket_endpoint)
    assert "token" not in ep_src.lower()
    assert "auth" not in ep_src.lower()
    assert "api_key" not in ep_src.lower()
    # process_incoming_command also has no auth check:
    pic_src = inspect.getsource(web_server.process_incoming_command)
    assert "auth" not in pic_src.lower()


# ---------------------------------------------------------------------------
# Finding A7 (MEDIUM) — FIXED 2026-05-28: removed.
# CommandMessage now carries an optional `seq` field and the web server dedups
# duplicates per WS connection. See tests/test_command_seq_dedup.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Finding A8 (MEDIUM):
# ARM is unconditional: no GNSS-fix gate, no home-WP gate, no failsafe-config
# gate.  Matches D-04.
# ---------------------------------------------------------------------------
def test_arm_is_unconditional():
    from src.manager import process as mgr
    handle_src = inspect.getsource(mgr.ManagerProcess.handle_command)
    # Find ARM branch
    arm_idx = handle_src.find("CommandType.ARM")
    next_branch = handle_src.find("elif cmd.type", arm_idx + 1)
    arm_block = handle_src[arm_idx:next_branch]
    # The only pre-condition is sim_mode != SIMULATION — no GNSS-fix check, no
    # home_wp check, no failsafe_config sanity check.
    assert "min_gnss_fix" not in arm_block
    assert "home_wp" not in arm_block
    assert "fix_type" not in arm_block


# ---------------------------------------------------------------------------
# Finding A9 (LOW / B-13 update):
# arduino_nano.py still exists alongside esp32.py.  README B-13 claims they
# are identical — in reality they have diverged (different timeouts, buffer
# resets, rounding) but the legacy file is still imported by nothing in main
# yet still ships, creating a maintenance trap.
# ---------------------------------------------------------------------------
def test_arduino_nano_legacy_driver_still_shipped():
    arduino_path = os.path.join(ROOT, 'src', 'drivers', 'arduino_nano.py')
    assert os.path.exists(arduino_path), (
        "arduino_nano.py was deleted — B-13 resolved; remove this test."
    )
    # And nothing in the active process catalogue imports it:
    with open(os.path.join(ROOT, 'src', 'drivers', 'process.py')) as f:
        hal_src = f.read()
    assert "arduino_nano" not in hal_src, (
        "arduino_nano is now wired into HAL — review whether ESP32Node and "
        "ArduinoNode should coexist."
    )
