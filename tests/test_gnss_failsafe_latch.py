"""
Test B-01 fix: GNSS failsafe latch prevents re-trigger loop.

The bug: after the failsafe fired, gnss_lost_since was reset to None.
On the very next loop (GNSS still absent) the timer would restart and
fire again after ins_timeout seconds, repeating indefinitely.

The fix: a gnss_failsafe_active latch is set to True when the failsafe
fires. Subsequent loops skip the action while the latch is set.
The latch is cleared only when GNSS fix is restored.
"""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_gnc_class():
    """Import GNCProcess with all ZMQ / config side-effects patched out."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    with patch("zmq.Context"), \
         patch("src.core.messaging.Publisher"), \
         patch("src.core.messaging.Subscriber"):
        from src.gnc.process import GNCProcess
    return GNCProcess


def _make_mock_gnc(ins_action="station_keeping", ins_timeout=5.0, min_gnss_fix=1):
    """
    Return a minimal mock object with the attributes _check_failsafes reads/writes.
    Does NOT instantiate the real GNCProcess (no ZMQ required).
    """
    obj = MagicMock()

    # Failsafe config
    obj.failsafe_config = SimpleNamespace(
        min_gnss_fix=min_gnss_fix,
        ins_timeout=ins_timeout,
        ins_action=ins_action,
        comm_timeout=30.0,   # large — keep comm-loss check silent in these tests
        comm_action="station_keeping",
    )

    # Fail-safe state (mirrors __init__)
    obj.gnss_lost_since = None
    obj.gnss_failsafe_active = False
    obj.last_gnss_fix_type = 0          # bad fix → failsafe should eventually trigger
    obj.last_heartbeat_time = time.time()
    obj.home_wp = None

    # Side-effect trackers
    obj._emergency_stop = MagicMock()
    obj._failsafe_station_keeping = MagicMock()
    obj._failsafe_return_home = MagicMock()

    return obj


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestGNSSFailsafeLatch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Store the class itself (not the method) to avoid Python's descriptor
        # protocol silently binding _check_failsafes as a test-instance method.
        cls._GNC = _load_gnc_class()

    def _call(self, obj, now):
        """Thin wrapper so test methods stay readable."""
        self._GNC._check_failsafes(obj, now)

    def _run_loops(self, obj, n_loops, dt=0.05, t0=None):
        if t0 is None:
            t0 = time.time()
        for i in range(n_loops):
            self._call(obj, t0 + i * dt)

    # ------------------------------------------------------------------
    # TEST 1 — Failsafe fires exactly ONCE while GNSS remains absent
    # ------------------------------------------------------------------
    def test_failsafe_fires_exactly_once(self):
        """
        With ins_timeout=1 s and a 20 Hz loop (dt=0.05 s):
        - Run 100 loops (~5 s) with GNSS fix absent the whole time.
        - The station-keeping failsafe should fire exactly once (not 80 times).
        """
        obj = _make_mock_gnc(ins_action="station_keeping", ins_timeout=1.0)
        self._run_loops(obj, n_loops=100, dt=0.05, t0=1_000.0)
        count = obj._failsafe_station_keeping.call_count
        self.assertEqual(count, 1, f"Failsafe should fire exactly once, fired {count} times.")

    # ------------------------------------------------------------------
    # TEST 2 — Failsafe does NOT fire before ins_timeout elapses
    # ------------------------------------------------------------------
    def test_failsafe_does_not_fire_early(self):
        """Failsafe must NOT fire during the timeout window."""
        obj = _make_mock_gnc(ins_action="station_keeping", ins_timeout=2.0)
        self._run_loops(obj, n_loops=38, dt=0.05, t0=1_000.0)  # 1.9 s < 2 s timeout
        self.assertEqual(obj._failsafe_station_keeping.call_count, 0,
                         "Failsafe fired before ins_timeout elapsed.")

    # ------------------------------------------------------------------
    # TEST 3 — Latch clears on GNSS restore; fires again on next loss
    # ------------------------------------------------------------------
    def test_latch_resets_on_gnss_restore(self):
        """
        After GNSS is restored the latch must clear so a future loss can
        trigger the failsafe a second time.
        """
        obj = _make_mock_gnc(ins_action="station_keeping", ins_timeout=1.0)
        t0, dt = 1_000.0, 0.05

        # Phase 1 — GNSS absent for 3 s → fires once
        self._run_loops(obj, n_loops=60, dt=dt, t0=t0)
        self.assertEqual(obj._failsafe_station_keeping.call_count, 1,
                         "Phase 1: failsafe should fire once.")
        self.assertTrue(obj.gnss_failsafe_active, "Latch must be set after firing.")

        # Phase 2 — GNSS restored for 1 s → latch clears
        obj.last_gnss_fix_type = 2
        t1 = t0 + 60 * dt
        self._run_loops(obj, n_loops=20, dt=dt, t0=t1)
        self.assertFalse(obj.gnss_failsafe_active,
                         "Latch must clear when GNSS fix is restored.")
        self.assertIsNone(obj.gnss_lost_since,
                          "gnss_lost_since must be None after GNSS restore.")

        # Phase 3 — GNSS lost again for 3 s → fires a second time
        obj.last_gnss_fix_type = 0
        t2 = t1 + 20 * dt
        self._run_loops(obj, n_loops=60, dt=dt, t0=t2)
        self.assertEqual(obj._failsafe_station_keeping.call_count, 2,
                         "Phase 3: failsafe should fire a second time.")

    # ------------------------------------------------------------------
    # TEST 4 — emergency_stop action is also latched
    # ------------------------------------------------------------------
    def test_emergency_stop_latches(self):
        """emergency_stop must also fire exactly once, not on every loop."""
        obj = _make_mock_gnc(ins_action="emergency_stop", ins_timeout=1.0)
        self._run_loops(obj, n_loops=100, dt=0.05, t0=1_000.0)
        count = obj._emergency_stop.call_count
        self.assertEqual(count, 1, f"emergency_stop should fire exactly once, fired {count} times.")

    # ------------------------------------------------------------------
    # TEST 5 — Initial state sanity check (regression guard)
    # ------------------------------------------------------------------
    def test_initial_state(self):
        """Mock object starts with correct initial state."""
        obj = _make_mock_gnc()
        self.assertFalse(obj.gnss_failsafe_active)
        self.assertIsNone(obj.gnss_lost_since)


if __name__ == "__main__":
    unittest.main(verbosity=2)
