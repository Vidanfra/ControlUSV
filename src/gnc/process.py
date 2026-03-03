#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNC Process — runs guidance, navigation and control at 20 Hz.

Subscribes to sensor data (GNSS, IMU), computes path following and
heading control, publishes motor commands and debug data.

Only active when mode == 'AUTO' and is_armed == True.
"""

import math
import time
import json
import numpy as np
from loguru import logger

from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import (
    CommandMessage, CommandType, ControlDebugMessage, MissionPayload, Waypoint
)
from src.core.config import settings
from src.gnc.gnc_utils import latlon_to_ned, ssa
from src.gnc.autopilot import GNCController

# Salpa 1 vehicle parameters (for controller initialization)
# These match the vehicle model constants
SALPA1_IZZ = 60.0       # Approximate yaw inertia [kg·m²] (computed at runtime)
SALPA1_K_POS = 0.00365
SALPA1_L1 = -0.673      # left propeller lever arm
SALPA1_L2 = 0.673       # right propeller lever arm
SALPA1_N_MAX = 175.9    # max prop speed [rad/s]
SALPA1_N_MIN = -175.0   # min prop speed [rad/s]


def _make_default_controller():
    """Create a GNCController with Salpa 1 defaults."""
    import numpy as np
    B = SALPA1_K_POS * np.array([[1, 1], [-SALPA1_L1, -SALPA1_L2]])
    B_inv = np.linalg.inv(B)
    return GNCController(
        m_yaw=SALPA1_IZZ,
        B_inv=B_inv,
        n_max=SALPA1_N_MAX,
        n_min=SALPA1_N_MIN,
        wn=4.0, zeta=0.5,
        wn_d=1.0, zeta_d=1.0,
        delta=5.0, gamma=0.0,
        tau_X=150.0,
    )


class GNCProcess(ServiceProcess):
    """
    GNC process: guidance + control at 20 Hz.

    Subscribes to:
        - sensor/gnss: for position and heading
        - sensor/imu: for yaw rate and attitude
        - command/user: for mission upload, arm/disarm, mode changes

    Publishes to:
        - gnc/control_debug: target heading, heading error, CTE
        - gnc/control_output: motor commands (port/starboard %)
    """

    def setup(self):
        # Subscribers
        self.gnss_sub = Subscriber([Topics.SENSOR_GNSS])
        self.imu_sub = Subscriber([Topics.SENSOR_IMU])
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        self.status_sub = Subscriber([Topics.SYSTEM_STATUS])

        # Publishers
        self.control_debug_pub = Publisher(Topics.CONTROL_DEBUG)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)

        # Controller
        self.controller = _make_default_controller()

        # Navigation state (from sensors)
        self.lat = 0.0
        self.lon = 0.0
        self.heading_rad = 0.0
        self.yaw_rate = 0.0
        self.sog_ms = 0.0
        self.gnss_heading_valid = False

        # IMU fallback heading
        self.imu_heading_rad = 0.0

        # Mission state
        self.is_armed = False
        self.mode = "MANUAL"
        self.mission_waypoints = []  # list of Waypoint (lat/lon/radius/speed)
        self.mission_origin = None   # (lat0, lon0) for NED conversion
        self.mission_loaded = False

        # Timing
        self.last_gnss_time = 0.0

        logger.info("GNC Process initialized (waiting for AUTO mode)")

    def loop(self):
        """Main loop — runs at 20 Hz."""
        now = time.time()

        # 1. Consume all pending sensor data (non-blocking)
        self._consume_gnss()
        self._consume_imu()
        self._consume_commands()
        self._consume_status()

        # 2. Only run control in AUTO + ARMED
        if self.mode != "AUTO" or not self.is_armed:
            return

        # 3. Need GNSS data to navigate
        if self.lat == 0.0 and self.lon == 0.0:
            return

        # 4. Need a loaded mission
        if not self.mission_loaded:
            return

        # 5. Build eta/nu from sensor data
        # Use GNSS heading if valid, else IMU magnetic heading
        heading = self.heading_rad if self.gnss_heading_valid else self.imu_heading_rad

        # Convert to local NED
        lat0, lon0 = self.mission_origin
        N, E = latlon_to_ned(self.lat, self.lon, lat0, lon0)

        eta = np.array([N, E, 0.0, 0.0, 0.0, heading], float)
        # Approximate nu from SOG (assuming mostly surge)
        nu = np.array([self.sog_ms, 0.0, 0.0, 0.0, 0.0, self.yaw_rate], float)

        # Sample time
        h = 1.0 / settings.LOOP_RATES.get('gnc', 20)

        # 6. GNC step
        n1, n2, debug = self.controller.step(eta, nu, h)

        # 7. Publish control commands (as percentage of max)
        port_pct = (n1 / SALPA1_N_MAX) * 100.0 if SALPA1_N_MAX != 0 else 0.0
        stbd_pct = (n2 / SALPA1_N_MAX) * 100.0 if SALPA1_N_MAX != 0 else 0.0

        self.control_cmd_pub.publish({
            'timestamp': now,
            'port_pct': max(-100, min(100, port_pct)),
            'starboard_pct': max(-100, min(100, stbd_pct)),
            'n1_rads': n1,
            'n2_rads': n2,
        })

        # 8. Publish debug data
        self.control_debug_pub.publish(
            ControlDebugMessage(
                timestamp=now,
                target_heading=debug['psi_d'],
                heading_error=debug['heading_error'],
                cross_track_error=debug['cross_track_error'],
            ).model_dump()
        )

        # 9. Check mission completion
        if self.controller.is_mission_complete():
            logger.info("GNC: Mission complete — holding position")

    # ---- Sensor consumption ----

    def _consume_gnss(self):
        while True:
            msg = self.gnss_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.lat = data.get('lat', self.lat)
            self.lon = data.get('lon', self.lon)
            self.sog_ms = data.get('sog_knots', 0.0) * 0.514444
            heading_status = data.get('heading_status', '')
            if heading_status == 'A':
                self.heading_rad = math.radians(data.get('heading', 0.0))
                self.gnss_heading_valid = True
            else:
                self.gnss_heading_valid = False
            self.last_gnss_time = time.time()

    def _consume_imu(self):
        while True:
            msg = self.imu_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.imu_heading_rad = math.radians(data.get('mag_heading', 0.0))
            self.yaw_rate = math.radians(data.get('wz', 0.0))

    def _consume_commands(self):
        while True:
            msg = self.cmd_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, payload = msg
            try:
                cmd = CommandMessage(**payload)
                self._handle_command(cmd)
            except Exception as e:
                logger.error(f"GNC: failed to parse command: {e}")

    def _consume_status(self):
        while True:
            msg = self.status_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.is_armed = data.get('is_armed', self.is_armed)
            self.mode = data.get('mode', self.mode)

    def _handle_command(self, cmd: CommandMessage):
        if cmd.type == CommandType.UPLOAD_MISSION:
            try:
                mission = MissionPayload(**cmd.payload)
                self.mission_waypoints = mission.waypoints
                self._load_mission()
                logger.info(
                    f"GNC: Mission uploaded with {len(mission.waypoints)} waypoints"
                )
            except Exception as e:
                logger.error(f"GNC: Failed to parse mission: {e}")

        elif cmd.type == CommandType.ARM:
            self.is_armed = True
            logger.info("GNC: Armed")

        elif cmd.type == CommandType.DISARM:
            self.is_armed = False
            self.controller.reset()
            logger.info("GNC: Disarmed — controller reset")

        elif cmd.type == CommandType.SET_MODE:
            new_mode = cmd.payload.get('mode', self.mode)
            self.mode = new_mode
            if new_mode == 'AUTO' and self.mission_loaded:
                # Reset controller for fresh start
                heading = self.heading_rad if self.gnss_heading_valid else self.imu_heading_rad
                self.controller.reset(psi_init=heading)
                logger.info("GNC: AUTO mode — controller activated")

    def _load_mission(self):
        """Convert waypoints from lat/lon to NED and load into controller."""
        if not self.mission_waypoints:
            self.mission_loaded = False
            return

        # Origin = first waypoint
        wp0 = self.mission_waypoints[0]
        lat0, lon0 = wp0.lat, wp0.lon
        self.mission_origin = (lat0, lon0)

        waypoints_ned = []
        for wp in self.mission_waypoints:
            N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
            waypoints_ned.append({
                'N': N,
                'E': E,
                'radius': wp.radius,
                'speed': getattr(wp, 'speed', 1.0),
            })

        self.controller.set_waypoints(waypoints_ned)
        self.mission_loaded = True

        logger.info(
            f"GNC: Mission loaded — origin ({lat0:.6f}, {lon0:.6f}), "
            f"{len(waypoints_ned)} waypoints in NED"
        )
