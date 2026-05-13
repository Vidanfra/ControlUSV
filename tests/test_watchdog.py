"""
Unit tests for the B-03 watchdog supervisor in main.py.

All tests call _watchdog_tick() directly with mock process objects so no
real child processes, ZMQ sockets, or hardware are needed.
"""

import sys
import os
import time
from collections import defaultdict
from unittest.mock import MagicMock

# Make sure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import _watchdog_tick, _MAX_RESTARTS, _CRASH_WINDOW, _MAX_BACKOFF


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dead_proc(exitcode=1):
    p = MagicMock()
    p.is_alive.return_value = False
    p.exitcode = exitcode
    p.pid = 9999
    return p

def _alive_proc():
    p = MagicMock()
    p.is_alive.return_value = True
    p.exitcode = None
    p.pid = 1111
    return p

class _FakeClass:
    """Stands in for a service class. Records how many times it was instantiated."""
    instances = 0
    def __init__(self, **kw):
        _FakeClass.instances += 1
        self._alive = True
    def start(self):   pass
    def stop(self):    pass
    def is_alive(self): return self._alive
    @property
    def pid(self): return 42

def _make_state(names=("SvcA",), critical_names=()):
    """Return a fresh watchdog state dictionary ready for _watchdog_tick calls."""
    processes   = {n: _alive_proc() for n in names}
    catalogue   = {n: (_FakeClass, {}) for n in names}
    critical    = {n: (n in critical_names) for n in names}
    crash_times = defaultdict(list)
    backoff     = defaultdict(float)
    restart_at  = defaultdict(float)
    gave_up     = set()
    pending     = set()
    alerts      = []

    def alert_fn(level, name, msg):
        alerts.append({"level": level, "name": name, "msg": msg})

    spawned = []
    def spawn_fn(cls, kw):
        p = _FakeClass(**kw)
        spawned.append(p)
        return p

    return dict(
        processes=processes, catalogue=catalogue, critical=critical,
        crash_times=crash_times, backoff_secs=backoff, restart_at=restart_at,
        gave_up=gave_up, pending=pending,
        spawn_fn=spawn_fn, alert_fn=alert_fn,
        alerts=alerts, spawned=spawned,
    )

def _tick(st, now=None):
    if now is None:
        now = time.time()
    _watchdog_tick(
        now,
        st["processes"], st["catalogue"], st["critical"],
        st["crash_times"], st["backoff_secs"], st["restart_at"],
        st["gave_up"], st["pending"],
        spawn_fn=st["spawn_fn"], alert_fn=st["alert_fn"],
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestWatchdogDetection:

    def test_alive_process_raises_no_alert(self):
        st = _make_state()
        # SvcA is alive → nothing should happen
        _tick(st)
        assert len(st["alerts"]) == 0
        assert len(st["pending"]) == 0
        assert len(st["gave_up"]) == 0

    def test_dead_process_adds_to_pending(self):
        st = _make_state()
        st["processes"]["SvcA"] = _dead_proc(exitcode=1)
        _tick(st)
        assert "SvcA" in st["pending"]

    def test_dead_process_emits_alert(self):
        st = _make_state()
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st)
        assert len(st["alerts"]) == 1

    def test_critical_process_emits_critical_alert(self):
        st = _make_state(critical_names=("SvcA",))
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st)
        assert st["alerts"][0]["level"] == "critical"

    def test_non_critical_process_emits_warning_alert(self):
        st = _make_state()  # SvcA is NOT critical
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st)
        assert st["alerts"][0]["level"] == "warning"

    def test_dead_process_increments_crash_count(self):
        st = _make_state()
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st)
        assert len(st["crash_times"]["SvcA"]) == 1


class TestWatchdogBackoff:

    def test_first_restart_delay_is_one_second(self):
        st = _make_state()
        now = time.time()
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)
        # restart_at should be now + 1
        assert abs(st["restart_at"]["SvcA"] - (now + 1.0)) < 0.01

    def test_second_crash_doubles_delay(self):
        st = _make_state()
        now = 1000.0

        # First crash
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)
        # Simulate restart happening (clear pending, restore alive process)
        st["pending"].discard("SvcA")
        st["processes"]["SvcA"] = _dead_proc()

        # Second crash
        _tick(st, now=now + 2)
        assert abs(st["restart_at"]["SvcA"] - (now + 2 + 2.0)) < 0.01  # delay = 2s

    def test_backoff_caps_at_max_backoff(self):
        st = _make_state()
        now = 1000.0
        # Manually push backoff_secs to just below cap
        st["backoff_secs"]["SvcA"] = _MAX_BACKOFF

        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)
        # delay should be _MAX_BACKOFF (not double)
        assert abs(st["restart_at"]["SvcA"] - (now + _MAX_BACKOFF)) < 0.01


class TestWatchdogRestart:

    def test_restart_spawns_new_process_when_delay_elapsed(self):
        st = _make_state()
        now = 1000.0

        # Detect crash → schedule restart 1s later
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)
        assert "SvcA" in st["pending"]

        # Tick after delay — restart should fire
        _tick(st, now=now + 2.0)
        assert "SvcA" not in st["pending"]
        assert len(st["spawned"]) == 1

    def test_restart_not_spawned_before_delay(self):
        st = _make_state()
        now = 1000.0
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)

        # Tick only 0.1s later — too early
        _tick(st, now=now + 0.1)
        assert "SvcA" in st["pending"]
        assert len(st["spawned"]) == 0

    def test_restart_replaces_process_in_dict(self):
        st = _make_state()
        now = 1000.0
        old_proc = _dead_proc()
        st["processes"]["SvcA"] = old_proc
        _tick(st, now=now)
        _tick(st, now=now + 2.0)
        assert st["processes"]["SvcA"] is not old_proc

    def test_restart_emits_warning_alert(self):
        st = _make_state()
        now = 1000.0
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)
        alert_count_after_crash = len(st["alerts"])
        _tick(st, now=now + 2.0)
        # One more alert for the "restarted" notification
        assert len(st["alerts"]) == alert_count_after_crash + 1
        assert st["alerts"][-1]["level"] == "warning"


class TestWatchdogCrashLoop:

    def test_gives_up_after_max_restarts(self):
        st = _make_state()
        now = 1000.0

        for i in range(_MAX_RESTARTS):
            st["processes"]["SvcA"] = _dead_proc()
            st["pending"].discard("SvcA")
            _tick(st, now=now + i * 5)

        assert "SvcA" in st["gave_up"]

    def test_critical_alert_on_crash_loop(self):
        st = _make_state(critical_names=("SvcA",))
        now = 1000.0

        for i in range(_MAX_RESTARTS):
            st["processes"]["SvcA"] = _dead_proc()
            st["pending"].discard("SvcA")
            _tick(st, now=now + i * 5)

        critical_alerts = [a for a in st["alerts"] if a["level"] == "critical"]
        # At least one critical alert (the crash-loop message)
        assert len(critical_alerts) >= 1
        assert "CRASH LOOP" in critical_alerts[-1]["msg"]

    def test_no_more_restarts_after_gave_up(self):
        st = _make_state()
        now = 1000.0

        for i in range(_MAX_RESTARTS):
            st["processes"]["SvcA"] = _dead_proc()
            st["pending"].discard("SvcA")
            _tick(st, now=now + i * 5)

        assert "SvcA" in st["gave_up"]
        spawned_before = len(st["spawned"])

        # Another dead tick — should be ignored
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now + 100)
        assert len(st["spawned"]) == spawned_before

    def test_old_crashes_outside_window_dont_count(self):
        """Crashes older than _CRASH_WINDOW should be pruned and not trigger gave_up."""
        st = _make_state()
        now = 1000.0

        # Inject _MAX_RESTARTS - 1 old crashes, all outside the window
        old = now - _CRASH_WINDOW - 10
        for _ in range(_MAX_RESTARTS - 1):
            st["crash_times"]["SvcA"].append(old)

        # One new crash — should be allowed (total within window = 1)
        st["processes"]["SvcA"] = _dead_proc()
        _tick(st, now=now)

        assert "SvcA" not in st["gave_up"]
        assert "SvcA" in st["pending"]


class TestWatchdogMultiProcess:

    def test_only_dead_process_is_restarted(self):
        st = _make_state(names=("SvcA", "SvcB"))
        st["processes"]["SvcA"] = _dead_proc()
        # SvcB stays alive
        _tick(st)
        assert "SvcA" in st["pending"]
        assert "SvcB" not in st["pending"]

    def test_two_simultaneous_crashes_both_scheduled(self):
        st = _make_state(names=("SvcA", "SvcB"))
        st["processes"]["SvcA"] = _dead_proc()
        st["processes"]["SvcB"] = _dead_proc()
        _tick(st)
        assert "SvcA" in st["pending"]
        assert "SvcB" in st["pending"]
        assert len(st["alerts"]) == 2
