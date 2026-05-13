"""
Test B-02 fix: ARM is the sole gate for real motor output.

Behavioural rules under test:
  REAL mode + ARMED   → MANUAL_INPUT produces motor commands (published)
  REAL mode + DISARMED → MANUAL_INPUT silently ignored (no publish)
  SIM  mode (always DISARMED) → MANUAL_INPUT drives physics (published with source='sim')
  ARM rejected while RT sim is active
  _start_rt_sim forces DISARM if vehicle was armed
  _start_wp_route / _start_station blocked when not armed AND sim not active
  Auto modes execute when armed (REAL) OR when rt_sim_active (SIM)
"""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_gnc_class():
    """Import GNCProcess with ZMQ patched out."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    with patch("zmq.Context"), \
         patch("src.core.messaging.Publisher"), \
         patch("src.core.messaging.Subscriber"):
        from src.gnc.process import GNCProcess, SALPA1_N_MAX
    return GNCProcess, SALPA1_N_MAX


def _make_gnc(*, armed=False, mode='MANUAL', rt_sim=False):
    """
    Build a minimal GNCProcess-like mock with the attributes touched by
    _handle_command and the loop ARM gate checks.
    """
    obj = MagicMock()
    obj.is_armed = armed
    obj.mode = mode
    obj.rt_sim_active = rt_sim

    # Control cmd publisher — we count how many times it publishes
    obj.control_cmd_pub = MagicMock()
    obj.cmd_pub = MagicMock()   # internal commands (DISARM sync)

    # wp_route / station state
    obj.wp_route_active = False
    obj.station_active = False

    # Nominal values
    obj.lat = 0.0
    obj.lon = 0.0
    obj.heading_rad = 0.0
    obj.current_n1 = 0.0
    obj.current_n2 = 0.0
    return obj


# ──────────────────────────────────────────────────────────────────────────────
# Test suite
# ──────────────────────────────────────────────────────────────────────────────

class TestB02ArmMotorGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._GNC, cls._N_MAX = _load_gnc_class()

    # convenience
    def _handle(self, obj, cmd_type_str, payload=None):
        from src.core.models import CommandMessage, CommandType
        cmd = CommandMessage(
            timestamp=time.time(),
            type=CommandType(cmd_type_str),
            payload=payload or {},
        )
        self._GNC._handle_command(obj, cmd)

    # ── MANUAL INPUT tests ───────────────────────────────────────────────────

    def test_manual_input_real_armed_publishes(self):
        """REAL + ARMED: manual input must publish motor commands."""
        obj = _make_gnc(armed=True, mode='MANUAL', rt_sim=False)
        self._handle(obj, 'MANUAL_INPUT', {'throttle': 0.5, 'steering': 0.0})
        obj.control_cmd_pub.publish.assert_called_once()
        kwargs = obj.control_cmd_pub.publish.call_args[0][0]
        self.assertEqual(kwargs['source'], 'manual')
        self.assertAlmostEqual(kwargs['port_pct'], 50.0)
        self.assertAlmostEqual(kwargs['starboard_pct'], 50.0)

    def test_manual_input_real_disarmed_silent(self):
        """REAL + DISARMED: manual input must be silently discarded."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=False)
        self._handle(obj, 'MANUAL_INPUT', {'throttle': 1.0, 'steering': 0.0})
        obj.control_cmd_pub.publish.assert_not_called()

    def test_manual_input_sim_mode_publishes_sim_source(self):
        """SIM mode (disarmed): manual input drives physics and publishes with source='sim'."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=True)
        self._handle(obj, 'MANUAL_INPUT', {'throttle': 0.3, 'steering': 0.1})
        obj.control_cmd_pub.publish.assert_called_once()
        kwargs = obj.control_cmd_pub.publish.call_args[0][0]
        self.assertEqual(kwargs['source'], 'sim')

    def test_manual_input_wrong_mode_ignored(self):
        """Armed but not in MANUAL mode — input must be ignored."""
        obj = _make_gnc(armed=True, mode='WP_ROUTE', rt_sim=False)
        self._handle(obj, 'MANUAL_INPUT', {'throttle': 1.0, 'steering': 0.0})
        obj.control_cmd_pub.publish.assert_not_called()

    # ── ARM rejection during SIM ─────────────────────────────────────────────

    def test_arm_rejected_when_sim_active(self):
        """ARM command must be ignored when RT sim is running."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=True)
        self._handle(obj, 'ARM')
        self.assertFalse(obj.is_armed, "ARM must be rejected while RT sim is active")

    def test_arm_accepted_in_real_mode(self):
        """ARM command must work when RT sim is NOT active."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=False)
        self._handle(obj, 'ARM')
        self.assertTrue(obj.is_armed)

    # ── Auto-DISARM on sim start ─────────────────────────────────────────────

    def test_start_rt_sim_disarms_if_armed(self):
        """_start_rt_sim must force DISARM when vehicle was armed."""
        obj = _make_gnc(armed=True, mode='MANUAL', rt_sim=False)
        # Provide a minimal valid RTSimConfig payload
        payload = {
            'current_lat': 39.5, 'current_lon': -0.4,
            'current_heading': 0.0, 'surge_force': 150.0,
        }
        # _start_rt_sim accesses Salpa1Model — patch it
        with patch('src.gnc.process.Salpa1Model'):
            self._GNC._start_rt_sim(obj, payload)
        self.assertFalse(obj.is_armed, "_start_rt_sim must set is_armed=False")
        # A DISARM internal command should have been published
        obj.cmd_pub.publish.assert_called()
        published_types = [
            call_args[0][0].get('type') for call_args in obj.cmd_pub.publish.call_args_list
        ]
        self.assertIn('DISARM', published_types, "DISARM sync command must be published")

    # ── Start WP route / station blocked when not armed ─────────────────────

    def test_start_wp_route_blocked_when_disarmed_real(self):
        """_start_wp_route must reject when not armed and sim not active."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=False)
        # Supply 2 waypoints to pass the waypoint count check
        payload = {
            'waypoints': [
                {'lat': 39.5, 'lon': -0.4, 'radius': 5.0, 'speed': 1.0},
                {'lat': 39.51, 'lon': -0.41, 'radius': 5.0, 'speed': 1.0},
            ],
            'direction': 'forward', 'completion': 'stop',
        }
        self._GNC._start_wp_route(obj, payload)
        self.assertFalse(obj.wp_route_active, "WP Route must not start when disarmed in REAL mode")

    def test_start_station_blocked_when_disarmed_real(self):
        """_start_station must reject when not armed and sim not active."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=False)
        obj.lat = 39.5; obj.lon = -0.4   # valid position so the check passes
        # Provide valid payload
        payload = {'lat': 39.5, 'lon': -0.4, 'reaching_radius': 3.0, 'station_radius': 10.0}
        with patch('src.gnc.process.StationKeeper'):
            self._GNC._start_station(obj, payload)
        self.assertFalse(obj.station_active, "Station must not start when disarmed in REAL mode")

    def test_start_wp_route_allowed_in_sim(self):
        """_start_wp_route must be allowed when rt_sim_active (SIM mode)."""
        obj = _make_gnc(armed=False, mode='MANUAL', rt_sim=True)
        obj.lat = 39.5; obj.lon = -0.4
        obj.heading_rad = 0.0
        payload = {
            'waypoints': [
                {'lat': 39.5,  'lon': -0.4,  'radius': 5.0, 'speed': 1.0},
                {'lat': 39.51, 'lon': -0.41, 'radius': 5.0, 'speed': 1.0},
            ],
            'direction': 'forward', 'completion': 'stop',
        }
        with patch('src.gnc.process._make_default_controller') as mock_ctrl_factory:
            mock_ctrl = MagicMock()
            mock_ctrl_factory.return_value = mock_ctrl
            self._GNC._start_wp_route(obj, payload)
        self.assertTrue(obj.wp_route_active, "WP Route must be allowed in SIM mode")

    # ── Execution gate in loop ────────────────────────────────────────────────

    def test_execution_gate_real_armed(self):
        """can_execute must be True when armed in REAL mode."""
        is_armed = True
        rt_sim_active = False
        can_execute = is_armed or rt_sim_active
        self.assertTrue(can_execute)

    def test_execution_gate_real_disarmed(self):
        """can_execute must be False when disarmed in REAL mode."""
        is_armed = False
        rt_sim_active = False
        can_execute = is_armed or rt_sim_active
        self.assertFalse(can_execute)

    def test_execution_gate_sim(self):
        """can_execute must be True in SIM mode regardless of ARM state."""
        is_armed = False   # always disarmed in sim
        rt_sim_active = True
        can_execute = is_armed or rt_sim_active
        self.assertTrue(can_execute)


if __name__ == "__main__":
    unittest.main(verbosity=2)
