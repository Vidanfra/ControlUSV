"""Regression tests for the comm-loss failsafe wiring (finding 2.1 / B-16).

GNC's `_consume_link` must be the sole authority on `last_heartbeat_time`
(driven by the frontend PING-based `comms/link` topic). `_consume_status`
must NOT touch the heartbeat timer (Manager's local heartbeat is unrelated
to frontend liveness).

These tests exercise the methods directly with a fake subscriber so no ZMQ
broker or processes are needed.
"""
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.gnc import process as gnc_module
from src.core.messaging import Topics


class _FakeSub:
    """Minimal stand-in for messaging.Subscriber.receive."""
    def __init__(self, items):
        self._items = list(items)

    def receive(self, timeout_ms=0):
        if self._items:
            return self._items.pop(0)
        return None


def _make_gnc_stub():
    """Build a GNCProcess instance bypassing setup() (which needs ZMQ)."""
    gnc = gnc_module.GNCProcess.__new__(gnc_module.GNCProcess)
    gnc.last_heartbeat_time = None
    gnc.ws_alive = False
    gnc.link_sub = _FakeSub([])
    return gnc


def test_consume_link_bumps_heartbeat_only_when_ws_alive():
    gnc = _make_gnc_stub()
    gnc.link_sub = _FakeSub([
        (Topics.COMMS_LINK.value, {"ws_alive": True, "n_clients": 1, "ts": 0.0}),
    ])
    gnc._consume_link(mono_now=100.0)
    assert gnc.last_heartbeat_time == 100.0
    assert gnc.ws_alive is True

    # ws_alive=False does NOT update the timer (so the failsafe can fire).
    gnc.link_sub = _FakeSub([
        (Topics.COMMS_LINK.value, {"ws_alive": False, "n_clients": 0, "ts": 0.0}),
    ])
    gnc._consume_link(mono_now=200.0)
    assert gnc.last_heartbeat_time == 100.0   # unchanged
    assert gnc.ws_alive is False


def test_consume_status_does_not_touch_heartbeat():
    """Receiving a Manager SYSTEM_STATUS must not refresh comm-failsafe timer."""
    src = inspect.getsource(gnc_module.GNCProcess._consume_status)
    assert "self.last_heartbeat_time" not in src, (
        "_consume_status must not touch last_heartbeat_time; that timer is "
        "owned exclusively by _consume_link (frontend liveness)."
    )


def test_check_failsafes_cold_start_does_not_trigger():
    """Before any link event, comm-failsafe branch must NOT fire."""
    from src.core.models import FailsafeConfig
    gnc = _make_gnc_stub()
    gnc.failsafe_config = FailsafeConfig(comm_timeout=1.0, comm_action='station_keeping')
    gnc.last_gnss_fix_type = 4   # RTK fix, GNSS branch is happy
    gnc.gnss_lost_since = None
    gnc.gnss_failsafe_active = False
    gnc.home_wp = None
    # Track whether _failsafe_station_keeping is called
    called = {"v": False}
    gnc._failsafe_station_keeping = lambda: called.__setitem__("v", True)
    gnc._failsafe_return_home = lambda: called.__setitem__("v", True)
    gnc._emergency_stop = lambda: called.__setitem__("v", True)

    # No link event yet → last_heartbeat_time is None → comm branch skipped.
    gnc._check_failsafes(now=999_999.0)
    assert called["v"] is False


def test_check_failsafes_triggers_when_link_silent():
    """Once link is established then goes silent past comm_timeout, fire."""
    from src.core.models import FailsafeConfig
    gnc = _make_gnc_stub()
    gnc.failsafe_config = FailsafeConfig(comm_timeout=2.0, comm_action='station_keeping')
    gnc.last_gnss_fix_type = 4
    gnc.gnss_lost_since = None
    gnc.gnss_failsafe_active = False
    gnc.home_wp = None
    gnc.last_heartbeat_time = 100.0   # last ws_alive at t=100
    called = {"v": False}
    gnc._failsafe_station_keeping = lambda: called.__setitem__("v", True)
    gnc._failsafe_return_home = lambda: called.__setitem__("v", True)
    gnc._emergency_stop = lambda: called.__setitem__("v", True)

    # t=101 → only 1s elapsed, under threshold → no trigger
    gnc._check_failsafes(now=101.0)
    assert called["v"] is False

    # t=103 → 3s > 2s threshold → trigger
    gnc._check_failsafes(now=103.0)
    assert called["v"] is True


def test_web_server_publishes_comms_link():
    """The web server must publish a comms/link topic from PING data."""
    from src.comms import web_server as ws
    src = inspect.getsource(ws)
    assert "Topics.COMMS_LINK" in src
    assert "publish_link_status" in src
    assert "ws_alive" in src
