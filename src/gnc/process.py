#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNC Process — runs guidance, navigation and control at 20 Hz.

Subscribes to gnc/ekf_state (from navigation module) for position and attitude,
computes path following and heading control, publishes motor commands and debug data.

Also hosts the real-time simulation mode:
  - On START_RT_SIM: creates a vehicle model, mutes real sensors, runs the
    6-DOF dynamics at each loop tick, publishes simulated GNSS/IMU data on
    the sensor topics so the navigation module and frontend consume them.
  - On STOP_RT_SIM: stops the model, unmutes real sensors.
"""

import math
import time
import json
import numpy as np
from loguru import logger

from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import (
    CommandMessage, CommandType, ControlDebugMessage, MissionPayload, Waypoint,
    RTSimConfig, RTSimStatus,
)
from src.core.config import settings
from src.gnc.gnc_utils import latlon_to_ned, ned_to_latlon, ssa, attitudeEuler
from src.gnc.autopilot import GNCController
from src.gnc.vehicle_model import Salpa1Model
from src.gnc.sim_sensors import simulate_gnss, simulate_imu

# Salpa 1 vehicle parameters (for controller initialization)
SALPA1_IZZ = 60.0
SALPA1_K_POS = 0.00365
SALPA1_L1 = -0.673
SALPA1_L2 = 0.673
SALPA1_N_MAX = 175.9
SALPA1_N_MIN = -175.0


def _make_default_controller():
    """Create a GNCController with Salpa 1 defaults."""
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
        - gnc/ekf_state: unified navigation state (from NavigationProcess)
        - command/user: for mission upload, arm/disarm, mode changes, RT sim
        - system/status: for armed/mode state

    Publishes to:
        - gnc/control_debug: target heading, heading error, CTE
        - gnc/control_output: motor commands (port/starboard %)
        - sensor/gnss: simulated GNSS data (RT sim only)
        - sensor/imu: simulated IMU data (RT sim only)
        - sim/status: RT simulation status
    """

    def setup(self):
        # Subscribers
        self.nav_sub = Subscriber([Topics.STATE_ESTIMATION])
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        self.status_sub = Subscriber([Topics.SYSTEM_STATUS])

        # Publishers
        self.control_debug_pub = Publisher(Topics.CONTROL_DEBUG)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)

        # RT sim publishers (created on demand)
        self.sim_gnss_pub = Publisher(Topics.SENSOR_GNSS)
        self.sim_imu_pub = Publisher(Topics.SENSOR_IMU)
        self.sim_status_pub = Publisher(Topics.SIM_STATUS)

        # Command publisher (for MUTE/UNMUTE)
        self.cmd_pub = Publisher(Topics.COMMAND_USER)

        # Controller
        self.controller = _make_default_controller()

        # Navigation state (from gnc/ekf_state)
        self.lat = 0.0
        self.lon = 0.0
        self.heading_rad = 0.0
        self.yaw_rate = 0.0
        self.sog_ms = 0.0
        self.heading_status = ""
        self.nav_source = "sensor"

        # Mission state
        self.is_armed = False
        self.mode = "MANUAL"
        self.mission_waypoints = []
        self.mission_origin = None
        self.mission_loaded = False

        # Timing
        self.last_nav_time = 0.0

        # === Real-Time Simulation State ===
        self.rt_sim_active = False
        self.rt_sim_config = None       # RTSimConfig
        self.rt_sim_model = None        # Salpa1Model
        self.rt_sim_controller = None   # GNCController for sim
        self.rt_sim_eta = None          # [N, E, D, phi, theta, psi]
        self.rt_sim_nu = None           # [u, v, w, p, q, r]
        self.rt_sim_u_actual = None     # [n1, n2]
        self.rt_sim_t = 0.0            # simulation elapsed time
        self.rt_sim_start_time = 0.0   # wall-clock start
        self.rt_sim_origin = None      # (lat0, lon0)
        self.rt_sim_waypoints = []     # original waypoint list
        self.rt_sim_wp_ned = []        # waypoints in NED
        self.rt_sim_loops = 0          # loop counter
        self.rt_sim_forward = True     # current direction

        logger.info("GNC Process initialized (waiting for AUTO mode)")

    def loop(self):
        """Main loop — runs at 20 Hz."""
        now = time.time()

        # 1. Consume commands and system status
        self._consume_commands()
        self._consume_status()

        # 2. If RT sim is active, run the simulation step
        if self.rt_sim_active:
            self._rt_sim_step(now)
            return

        # 3. Consume navigation state (normal mode)
        self._consume_nav()

        # 4. Only run control in AUTO + ARMED
        if self.mode != "AUTO" or not self.is_armed:
            return

        if self.lat == 0.0 and self.lon == 0.0:
            return

        if not self.mission_loaded:
            return

        # 5. Build eta/nu from navigation state
        heading = self.heading_rad
        lat0, lon0 = self.mission_origin
        N, E = latlon_to_ned(self.lat, self.lon, lat0, lon0)

        eta = np.array([N, E, 0.0, 0.0, 0.0, heading], float)
        nu = np.array([self.sog_ms, 0.0, 0.0, 0.0, 0.0, self.yaw_rate], float)

        h = 1.0 / settings.LOOP_RATES.get('gnc', 20)

        # 6. GNC step
        n1, n2, debug = self.controller.step(eta, nu, h)

        # 7. Publish
        self._publish_control(n1, n2, debug, now)

        # 8. Check mission completion
        if self.controller.is_mission_complete():
            logger.info("GNC: Mission complete — holding position")

    # ---- Navigation consumption ----

    def _consume_nav(self):
        """Consume gnc/ekf_state from NavigationProcess."""
        while True:
            msg = self.nav_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.lat = data.get('lat', self.lat)
            self.lon = data.get('lon', self.lon)
            self.sog_ms = data.get('speed', self.sog_ms)
            self.heading_rad = data.get('heading', self.heading_rad)
            self.heading_status = data.get('heading_status', self.heading_status)
            self.nav_source = data.get('source', 'sensor')
            self.last_nav_time = time.time()

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
            if not self.rt_sim_active:
                self.is_armed = data.get('is_armed', self.is_armed)
                self.mode = data.get('mode', self.mode)

    def _handle_command(self, cmd: CommandMessage):
        if cmd.type == CommandType.UPLOAD_MISSION:
            try:
                mission = MissionPayload(**cmd.payload)
                self.mission_waypoints = mission.waypoints
                self._load_mission()
                logger.info(f"GNC: Mission uploaded with {len(mission.waypoints)} waypoints")
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
                heading = self.heading_rad
                self.controller.reset(psi_init=heading)
                logger.info("GNC: AUTO mode — controller activated")

        elif cmd.type == CommandType.START_RT_SIM:
            self._start_rt_sim(cmd.payload)

        elif cmd.type == CommandType.STOP_RT_SIM:
            self._stop_rt_sim()

    def _load_mission(self):
        """Convert waypoints from lat/lon to NED and load into controller."""
        if not self.mission_waypoints:
            self.mission_loaded = False
            return

        wp0 = self.mission_waypoints[0]
        lat0, lon0 = wp0.lat, wp0.lon
        self.mission_origin = (lat0, lon0)

        waypoints_ned = []
        for wp in self.mission_waypoints:
            N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
            waypoints_ned.append({
                'N': N, 'E': E,
                'radius': wp.radius,
                'speed': getattr(wp, 'speed', 1.0),
            })

        self.controller.set_waypoints(waypoints_ned)
        self.mission_loaded = True
        logger.info(
            f"GNC: Mission loaded — origin ({lat0:.6f}, {lon0:.6f}), "
            f"{len(waypoints_ned)} waypoints in NED"
        )

    def _publish_control(self, n1, n2, debug, now):
        """Publish motor commands and debug data."""
        port_pct = (n1 / SALPA1_N_MAX) * 100.0 if SALPA1_N_MAX != 0 else 0.0
        stbd_pct = (n2 / SALPA1_N_MAX) * 100.0 if SALPA1_N_MAX != 0 else 0.0

        self.control_cmd_pub.publish({
            'timestamp': now,
            'port_pct': max(-100, min(100, port_pct)),
            'starboard_pct': max(-100, min(100, stbd_pct)),
            'n1_rads': float(n1),
            'n2_rads': float(n2),
            'source': 'sim' if self.rt_sim_active else 'sensor',
        })

        self.control_debug_pub.publish(
            ControlDebugMessage(
                timestamp=now,
                target_heading=debug['psi_d'],
                heading_error=debug['heading_error'],
                cross_track_error=debug['cross_track_error'],
            ).model_dump()
        )

    # ================================================================
    #  REAL-TIME SIMULATION
    # ================================================================

    def _start_rt_sim(self, payload: dict):
        """Initialize and start the real-time simulation."""
        try:
            cfg = RTSimConfig(**payload)
        except Exception as e:
            logger.error(f"GNC: Invalid RT sim config: {e}")
            return

        if len(cfg.waypoints) < 2:
            logger.error("GNC: RT sim needs at least 2 waypoints")
            return

        logger.info(f"GNC: Starting RT simulation — {len(cfg.waypoints)} WPs, "
                     f"mode={cfg.gnss_mode}, completion={cfg.completion_mode}")

        # Store config
        self.rt_sim_config = cfg

        # Build waypoint list (possibly reversed)
        wps = list(cfg.waypoints)
        if cfg.start_mode == 'last_wp':
            wps = list(reversed(wps))
            self.rt_sim_forward = False
        else:
            self.rt_sim_forward = True

        self.rt_sim_waypoints = wps

        # Origin = first waypoint of the (possibly reversed) list
        lat0 = wps[0].lat
        lon0 = wps[0].lon
        self.rt_sim_origin = (lat0, lon0)

        # Convert to NED
        wp_ned = []
        for wp in wps:
            N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
            wp_ned.append({'N': N, 'E': E, 'radius': wp.radius, 'speed': wp.speed})
        self.rt_sim_wp_ned = wp_ned

        # Determine start heading
        dn = wp_ned[1]['N'] - wp_ned[0]['N']
        de = wp_ned[1]['E'] - wp_ned[0]['E']
        psi0 = math.atan2(de, dn)

        # Initial state
        self.rt_sim_eta = np.zeros(6)
        self.rt_sim_eta[0] = wp_ned[0]['N']
        self.rt_sim_eta[1] = wp_ned[0]['E']
        self.rt_sim_eta[5] = psi0
        self.rt_sim_nu = np.zeros(6)
        self.rt_sim_u_actual = np.array([0.0, 0.0])

        # Create vehicle model
        self.rt_sim_model = Salpa1Model(
            payload_mass=cfg.payload_kg,
            V_current=cfg.current_speed,
            beta_current=cfg.current_dir,
            tau_X=cfg.surge_force,
        )

        # Create dedicated controller for sim
        self.rt_sim_controller = GNCController(
            m_yaw=self.rt_sim_model.Izz_total,
            B_inv=self.rt_sim_model.Binv,
            n_max=self.rt_sim_model.n_max,
            n_min=self.rt_sim_model.n_min,
            wn=cfg.wn_pid, zeta=cfg.zeta_pid,
            wn_d=cfg.wn_ref, zeta_d=cfg.zeta_ref,
            delta=cfg.delta, gamma=cfg.gamma,
            tau_X=cfg.surge_force,
        )
        self.rt_sim_controller.set_waypoints(wp_ned)
        self.rt_sim_controller.reset(psi0)

        # Timing
        self.rt_sim_t = 0.0
        self.rt_sim_start_time = time.time()
        self.rt_sim_loops = 0

        # Mute real sensors
        self.cmd_pub.publish(CommandMessage(
            timestamp=time.time(),
            type=CommandType.MUTE_SENSORS,
            payload={},
        ).model_dump())

        # Auto-arm + AUTO
        self.is_armed = True
        self.mode = "AUTO"
        self.rt_sim_active = True

        logger.info("GNC: RT simulation started")

    def _stop_rt_sim(self):
        """Stop the real-time simulation and restore normal operation."""
        if not self.rt_sim_active:
            return

        self.rt_sim_active = False

        # Unmute real sensors
        self.cmd_pub.publish(CommandMessage(
            timestamp=time.time(),
            type=CommandType.UNMUTE_SENSORS,
            payload={},
        ).model_dump())

        # Disarm
        self.is_armed = False
        self.mode = "MANUAL"

        # Publish final status
        self.sim_status_pub.publish(RTSimStatus(
            timestamp=time.time(),
            running=False,
            elapsed_time=self.rt_sim_t,
        ).model_dump())

        # Clean up
        self.rt_sim_model = None
        self.rt_sim_controller = None
        self.rt_sim_eta = None
        self.rt_sim_nu = None

        logger.info(f"GNC: RT simulation stopped after {self.rt_sim_t:.1f}s")

    def _rt_sim_step(self, now):
        """Execute one RT simulation step: dynamics + GNC + publish."""
        cfg = self.rt_sim_config
        dt = cfg.time_step
        model = self.rt_sim_model
        ctrl = self.rt_sim_controller

        # --- GNC step with current state ---
        n1, n2, debug = ctrl.step(self.rt_sim_eta, self.rt_sim_nu, dt)
        u_control = np.array([n1, n2], dtype=float)

        # --- Physics step ---
        self.rt_sim_nu, self.rt_sim_u_actual = model.dynamics(
            self.rt_sim_eta, self.rt_sim_nu,
            self.rt_sim_u_actual, u_control, dt
        )

        # --- Kinematics — update position/attitude ---
        self.rt_sim_eta = attitudeEuler(self.rt_sim_eta, self.rt_sim_nu, dt)

        self.rt_sim_t += dt

        # --- Publish simulated sensor data ---
        lat0, lon0 = self.rt_sim_origin

        gnss_msg = simulate_gnss(
            self.rt_sim_eta, self.rt_sim_nu,
            lat0, lon0, cfg.gnss_mode,
            self.rt_sim_t, dt
        )
        self.sim_gnss_pub.publish(gnss_msg.model_dump())

        imu_msg = simulate_imu(self.rt_sim_eta, self.rt_sim_nu)
        self.sim_imu_pub.publish(imu_msg.model_dump())

        # --- Publish control output ---
        self._publish_control(n1, n2, debug, now)

        # --- Publish sim status ---
        self.sim_status_pub.publish(RTSimStatus(
            timestamp=now,
            running=True,
            elapsed_time=self.rt_sim_t,
            total_time=cfg.total_time,
            completion_mode=cfg.completion_mode,
            gnss_mode=cfg.gnss_mode,
            current_wp=debug.get('wp_index', 0),
            total_wp=len(self.rt_sim_waypoints),
            loops_completed=self.rt_sim_loops,
        ).model_dump())

        # --- Check completion ---
        self._check_rt_sim_completion(ctrl, cfg)

    def _check_rt_sim_completion(self, ctrl, cfg):
        """Handle completion modes for the RT simulation."""
        mode = cfg.completion_mode

        if mode == 'stop_time':
            if self.rt_sim_t >= cfg.total_time:
                logger.info("GNC: RT sim completed (time limit reached)")
                self._stop_rt_sim()

        elif mode == 'one_way':
            if ctrl.is_mission_complete():
                logger.info("GNC: RT sim completed (route finished)")
                self._stop_rt_sim()

        elif mode == 'loop':
            if ctrl.is_mission_complete():
                self.rt_sim_loops += 1
                logger.info(f"GNC: RT sim loop #{self.rt_sim_loops} complete, restarting")
                # Build a bridge from current vehicle position to WP[0] so the
                # vehicle drives back to the start instead of teleporting.
                wp_ned = self.rt_sim_wp_ned
                current_wp = {
                    'N': float(self.rt_sim_eta[0]),
                    'E': float(self.rt_sim_eta[1]),
                    'radius': wp_ned[0]['radius'],
                    'speed': wp_ned[0]['speed'],
                }
                bridge_wps = [current_wp] + list(wp_ned)
                ctrl.set_waypoints(bridge_wps)
                psi0 = math.atan2(
                    wp_ned[0]['E'] - float(self.rt_sim_eta[1]),
                    wp_ned[0]['N'] - float(self.rt_sim_eta[0]),
                )
                ctrl.reset(psi0)

        elif mode == 'loop_reverse':
            if ctrl.is_mission_complete():
                self.rt_sim_loops += 1
                self.rt_sim_forward = not self.rt_sim_forward
                logger.info(
                    f"GNC: RT sim loop #{self.rt_sim_loops} complete, "
                    f"reversing ({'forward' if self.rt_sim_forward else 'backward'})"
                )
                # Reverse waypoints
                wps_reversed = list(reversed(self.rt_sim_waypoints))
                self.rt_sim_waypoints = wps_reversed

                lat0, lon0 = self.rt_sim_origin
                wp_ned = []
                for wp in wps_reversed:
                    N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
                    wp_ned.append({'N': N, 'E': E, 'radius': wp.radius, 'speed': wp.speed})
                self.rt_sim_wp_ned = wp_ned

                # Bridge from current vehicle position to new WP[0]
                current_wp = {
                    'N': float(self.rt_sim_eta[0]),
                    'E': float(self.rt_sim_eta[1]),
                    'radius': wp_ned[0]['radius'],
                    'speed': wp_ned[0]['speed'],
                }
                bridge_wps = [current_wp] + list(wp_ned)
                ctrl.set_waypoints(bridge_wps)
                psi0 = math.atan2(
                    wp_ned[0]['E'] - float(self.rt_sim_eta[1]),
                    wp_ned[0]['N'] - float(self.rt_sim_eta[0]),
                )
                ctrl.reset(psi0)
