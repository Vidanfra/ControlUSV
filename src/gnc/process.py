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
    RTSimConfig, RTSimStatus, FailsafeConfig, GncConfig
)
from src.core.config import settings
from src.gnc.gnc_utils import latlon_to_ned, ned_to_latlon, ssa, attitudeEuler
from src.gnc.autopilot import GNCController, StationKeeper
from src.gnc.salpa1_params import (
    IZZ_TOTAL  as SALPA1_IZZ,
    K_POS      as SALPA1_K_POS,
    L1         as SALPA1_L1,
    L2         as SALPA1_L2,
    N_MAX      as SALPA1_N_MAX,
    N_MIN      as SALPA1_N_MIN,
    XU_LIN, XU_QUAD,
)
from src.gnc.vehicle_model import Salpa1Model
from src.gnc.sim_sensors import simulate_gnss, simulate_imu

# Salpa 1 vehicle parameters (for controller initialization)
def _speed_kn_to_tau_x(speed_kn: float) -> float:
    """Convert cruise speed [knots] to the required surge force [N] via drag inversion."""
    v = max(speed_kn, 0.0) * 0.5144   # knots → m/s
    return XU_LIN * v + XU_QUAD * v * v


def _make_default_controller(config: GncConfig = None):
    """Create a GNCController with Salpa 1 defaults or given config."""
    B = SALPA1_K_POS * np.array([[1, 1], [-SALPA1_L1, -SALPA1_L2]])
    B_inv = np.linalg.inv(B)
    if config is None:
        config = GncConfig()
    return GNCController(
        m_yaw=SALPA1_IZZ,
        B_inv=B_inv,
        n_max=SALPA1_N_MAX,
        n_min=SALPA1_N_MIN,
        wn=config.wn, zeta=config.zeta,
        wn_d=config.wn_ref, zeta_d=config.zeta_ref,
        k_delta=config.k_delta, delta_min=config.delta_min, gamma=config.gamma,
        tau_X=_speed_kn_to_tau_x(config.cruise_speed_kn),
        e_x_threshold_deg=config.e_x_threshold_deg,
        vel_profiler_enabled=config.vel_profiler_enabled,
        accel_ms2=config.accel_ms2,
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
        self.link_sub = Subscriber([Topics.COMMS_LINK])

        # Publishers
        self.control_debug_pub = Publisher(Topics.CONTROL_DEBUG)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)

        # RT sim publishers (created on demand)
        self.sim_gnss_pub = Publisher(Topics.SENSOR_GNSS)
        self.sim_imu_pub = Publisher(Topics.SENSOR_IMU)
        self.sim_status_pub = Publisher(Topics.SIM_STATUS)

        # Internal state-sync to Manager (failsafe-driven). Uses a dedicated
        # topic that GNC does NOT subscribe to, eliminating the self-loop
        # that previously sent synthesized commands back on COMMAND_USER.
        self.sync_pub = Publisher(Topics.GNC_SYNC)

        # Command publisher (RT-sim only: MUTE/UNMUTE sensors and the
        # auto-DISARM that happens when entering simulation).
        self.cmd_pub = Publisher(Topics.COMMAND_USER)

        # GNC Config
        self.gnc_config = GncConfig()

        # Controller
        self.controller = _make_default_controller(self.gnc_config)

        # Motor Output Memory for physical sim
        self.current_n1 = 0.0
        self.current_n2 = 0.0

        # Previous nu for acceleration estimation (du/dt, dv/dt)
        self.prev_nu = np.zeros(6)
        self.prev_nu_valid = False  # False until first step

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

        # WP Route state (real mode)
        self.wp_route_active = False
        self.wp_route_waypoints = []
        self.wp_route_origin = None
        self.wp_route_direction = 'forward'
        self.wp_route_completion = 'stop'
        self.wp_route_loops = 0
        self.wp_route_forward = True

        # Station keeping state (real mode)
        self.station_active = False
        self.station_keeper = None
        self._station_origin = None

        # Fail-safe state
        self.failsafe_config = FailsafeConfig()
        self.last_gnss_fix_type = 0
        # Interval timers use monotonic clock so an NTP step (e.g. on 4G
        # reconnect) does not break failsafe thresholds.
        self.gnss_lost_since = None        # monotonic ts when fix lost (None = OK)
        self.gnss_failsafe_active = False  # latched True after failsafe fires; clears on GNSS restore
        # last_heartbeat_time is None until the FIRST comms/link event arrives.
        # _check_failsafes skips the comm branch while this is None so a freshly
        # booted vehicle (no frontend yet) does not immediately trip the failsafe.
        self.last_heartbeat_time = None    # monotonic ts of last ws_alive=True
        self.ws_alive = False              # last-known frontend link state
        self.home_wp = None           # {'lat': ..., 'lon': ...}

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
        self.rt_sim_manual_mode = False # manual mode flag
        self.rt_sim_manual_n1 = 0.0    # manual thrust port
        self.rt_sim_manual_n2 = 0.0    # manual thrust stbd

        logger.info("GNC Process initialized (waiting for AUTO mode)")

    def loop(self):
        """Main loop — runs at 20 Hz."""
        now = time.time()
        mono = time.monotonic()

        # 1. Consume commands, system status, and frontend link liveness
        self._consume_commands()
        self._consume_status()
        self._consume_link(mono)

        # 2. If RT sim is active, run the simulation drifting/physics step
        #    Notice we do not return! The physics runs, sensors are spoofed,
        #    and normal navigation consumes them naturally below.
        if self.rt_sim_active:
            self._rt_sim_step(now)

        # 3. Consume navigation state (normal mode relies on sensor spoof/real)
        self._consume_nav()

        # 4. Fail-safe checks (only in REAL mode when armed in auto modes).
        # Uses monotonic clock for interval thresholds.
        if self.is_armed and not self.rt_sim_active and (self.wp_route_active or self.station_active):
            self._check_failsafes(mono)

        # Execution gate: REAL mode requires ARM; SIM mode uses rt_sim_active instead.
        # This ensures real motors NEVER move unless the user explicitly ARMed in REAL mode.
        can_execute = self.is_armed or self.rt_sim_active

        # 5. WP Route execution
        if self.wp_route_active and can_execute:
            self._run_wp_route(now)
            return

        # 6. Station Keeping execution
        if self.station_active and can_execute:
            self._run_station_keeping(now)
            return

        # 7. Legacy AUTO mode (upload mission + AUTO)
        if self.mode != "AUTO" or not can_execute:
            return

        if self.lat == 0.0 and self.lon == 0.0:
            return

        if not self.mission_loaded or not self.controller:
            return

        # Build eta/nu from navigation state
        heading = self.heading_rad
        lat0, lon0 = self.mission_origin
        N, E = latlon_to_ned(self.lat, self.lon, lat0, lon0)

        eta = np.array([N, E, 0.0, 0.0, 0.0, heading], float)
        nu = np.array([self.sog_ms, 0.0, 0.0, 0.0, 0.0, self.yaw_rate], float)

        h = 1.0 / settings.LOOP_RATES.get('gnc', 20)

        n1, n2, debug = self.controller.step(eta, nu, h)
        self._publish_control(n1, n2, debug, now, nu=nu)

        if self.controller.is_mission_complete():
            logger.info("GNC: Mission complete — holding position")

    # ---- Navigation consumption ----

    def _consume_nav(self):
        """Consume gnc/ekf_state from NavigationProcess."""
        for _ in range(50):
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
            # Track GNSS fix type for failsafe
            if 'fix_type' in data:
                self.last_gnss_fix_type = data['fix_type']

    def _consume_commands(self):
        for _ in range(50):
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
        for _ in range(50):
            msg = self.status_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            # NOTE: last_heartbeat_time is updated only in _consume_link based on
            # actual frontend liveness — NOT here. Manager keeps publishing
            # SYSTEM_STATUS regardless of WS link state, so using it as the
            # comm-failsafe heartbeat masked real 4G/commander drops.
            # Always sync armed/mode from manager (the authority)
            self.is_armed = data.get('is_armed', self.is_armed)
            new_mode = data.get('mode', self.mode)
            if new_mode != self.mode:
                # Mode changed via heartbeat — deactivate stale auto modes
                if new_mode != 'WP_ROUTE' and self.wp_route_active:
                    self._stop_wp_route()
                if new_mode != 'STATION' and self.station_active:
                    self._stop_station()
                self.mode = new_mode
            # Track GNSS fix type from system status
            if 'gnss_fix_type' in data:
                self.last_gnss_fix_type = data['gnss_fix_type']
            # Sync gnc_config from Manager heartbeat.
            # Manager is the persistence authority (loads from manager_settings.json on
            # startup and saves on every SET_GNC_CONFIG / START_WP_ROUTE / START_STATION).
            # Without this, GNCProcess would keep GncConfig() defaults after every restart
            # until the user manually clicks "Update GNC Settings" on the frontend.
            if 'gnc_config' in data:
                try:
                    new_config = GncConfig(**data['gnc_config'])
                    if new_config.model_dump() != self.gnc_config.model_dump():
                        self.gnc_config = new_config
                        self._apply_gnc_config()
                        logger.debug("GNC: gnc_config synced from system/status heartbeat")
                except Exception as e:
                    logger.warning(f"GNC: Failed to apply gnc_config from heartbeat: {e}")

    def _consume_link(self, mono_now: float):
        """Consume comms/link from web_server. Only ws_alive=True bumps the
        comm-failsafe heartbeat; ws_alive=False is the trigger we want to fire.
        """
        for _ in range(50):
            msg = self.link_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.ws_alive = bool(data.get('ws_alive', False))
            if self.ws_alive:
                self.last_heartbeat_time = mono_now

    def _handle_command(self, cmd: CommandMessage):
        # NOTE: GNC no longer publishes synthesized commands on COMMAND_USER for
        # Manager sync — that path went through Topics.GNC_SYNC instead. The old
        # `_source == 'gnc_internal'` self-loop filter is therefore no longer
        # needed.

        if cmd.type == CommandType.UPLOAD_MISSION:
            try:
                mission = MissionPayload(**cmd.payload)
                self.mission_waypoints = mission.waypoints
                self._load_mission()
                logger.info(f"GNC: Mission uploaded with {len(mission.waypoints)} waypoints")
            except Exception as e:
                logger.error(f"GNC: Failed to parse mission: {e}")

        elif cmd.type == CommandType.ARM:
            if self.rt_sim_active:
                logger.warning("GNC: ARM rejected — RT simulation is active; real motors cannot be armed during sim")
                return
            self.is_armed = True
            logger.info("GNC: Armed")

        elif cmd.type == CommandType.DISARM:
            self.is_armed = False
            if self.controller:
                self.controller.reset()
            # Also deactivate any auto modes
            if self.wp_route_active:
                self._stop_wp_route()
            if self.station_active:
                self._stop_station()
            logger.info("GNC: Disarmed — controller reset")

        elif cmd.type == CommandType.SET_MODE:
            new_mode = cmd.payload.get('mode', self.mode)
            old_mode = self.mode
            self.mode = new_mode
            # Deactivate auto modes when switching away from them
            if new_mode != 'WP_ROUTE' and self.wp_route_active:
                self._stop_wp_route()
                logger.info("GNC: WP Route auto-stopped on mode change")
            if new_mode != 'STATION' and self.station_active:
                self._stop_station()
                logger.info("GNC: Station keeping auto-stopped on mode change")
            if new_mode == 'AUTO' and self.mission_loaded:
                heading = self.heading_rad
                if self.controller:
                    self.controller.reset(psi_init=heading)
                logger.info("GNC: AUTO mode — controller activated")

        elif cmd.type == CommandType.START_RT_SIM:
            self._start_rt_sim(cmd.payload)

        elif cmd.type == CommandType.STOP_RT_SIM:
            self._stop_rt_sim()

        elif cmd.type == CommandType.START_WP_ROUTE:
            self._start_wp_route(cmd.payload)

        elif cmd.type == CommandType.STOP_WP_ROUTE:
            self._stop_wp_route()

        elif cmd.type == CommandType.START_STATION:
            self._start_station(cmd.payload)

        elif cmd.type == CommandType.STOP_STATION:
            self._stop_station()

        elif cmd.type == CommandType.SET_HOME_WP:
            self.home_wp = {
                'lat': cmd.payload.get('lat', 0.0),
                'lon': cmd.payload.get('lon', 0.0),
            }
            logger.info(f"GNC: Home WP set: {self.home_wp}")

        elif cmd.type == CommandType.MANUAL_INPUT:
            # REAL mode: ARM is required to drive real motors.
            # SIM mode: vehicle is always DISARMED; physics input works via rt_sim_active.
            if (self.is_armed or self.rt_sim_active) and self.mode == 'MANUAL':
                throttle = cmd.payload.get("throttle", 0.0)
                steering = cmd.payload.get("steering", 0.0)
                port_pct = max(-100, min(100, (throttle + steering) * 100))
                stbd_pct = max(-100, min(100, (throttle - steering) * 100))

                self.current_n1 = (port_pct / 100.0) * SALPA1_N_MAX
                self.current_n2 = (stbd_pct / 100.0) * SALPA1_N_MAX

                # Publish so frontend indicators and charts update in real-time.
                # source='sim' ensures hardware drivers skip this command in SIM mode.
                self.control_cmd_pub.publish({
                    'timestamp': time.time(),
                    'port_pct': port_pct,
                    'starboard_pct': stbd_pct,
                    'n1_rads': self.current_n1,
                    'n2_rads': self.current_n2,
                    'source': 'sim' if self.rt_sim_active else 'manual',
                })

        elif cmd.type == CommandType.SET_FAILSAFE_CONFIG:
            try:
                self.failsafe_config = FailsafeConfig(**cmd.payload)
                logger.info(f"GNC: Failsafe config updated: {self.failsafe_config}")
            except Exception as e:
                logger.error(f"GNC: Invalid failsafe config: {e}")

        elif cmd.type == CommandType.SET_GNC_CONFIG:
            try:
                # Merge into existing config so partial payloads (e.g. only
                # cruise_speed_kn) don't reset unrelated fields to defaults.
                merged = {**self.gnc_config.model_dump(), **cmd.payload}
                self.gnc_config = GncConfig(**merged)
                self._apply_gnc_config()
                logger.info(f"GNC: Parameters updated: {self.gnc_config}")
            except Exception as e:
                logger.error(f"GNC: Failed to apply GNC config: {e}")

    def _apply_gnc_config(self):
        """Update active controllers with the new GNC Config parameters."""
        cfg = self.gnc_config
        tuning = dict(wn=cfg.wn, zeta=cfg.zeta, wn_d=cfg.wn_ref, zeta_d=cfg.zeta_ref,
                      k_delta=cfg.k_delta, delta_min=cfg.delta_min, gamma=cfg.gamma,
                      tau_X=_speed_kn_to_tau_x(cfg.cruise_speed_kn),
                      vel_profiler_enabled=cfg.vel_profiler_enabled,
                      accel_ms2=cfg.accel_ms2)

        # Update main path-following controller
        if self.controller:
            self.controller.update_tuning(**tuning)

        # Update station keeper if active
        if self.station_keeper and self.station_keeper.controller:
            self.station_keeper.controller.update_tuning(**tuning)

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

    def _publish_control(self, n1, n2, debug, now, nu=None):
        """Publish motor commands and debug data."""
        self.current_n1 = float(n1)
        self.current_n2 = float(n2)
        port_pct = (self.current_n1 / SALPA1_N_MAX) * 100.0 if SALPA1_N_MAX != 0 else 0.0
        stbd_pct = (self.current_n2 / SALPA1_N_MAX) * 100.0 if SALPA1_N_MAX != 0 else 0.0

        self.control_cmd_pub.publish({
            'timestamp': now,
            'port_pct': max(-100, min(100, port_pct)),
            'starboard_pct': max(-100, min(100, stbd_pct)),
            'n1_rads': float(n1),
            'n2_rads': float(n2),
            'source': 'sim' if self.rt_sim_active else 'sensor',
        })

        # Velocity and acceleration from nu vector
        h = 1.0 / settings.LOOP_RATES.get('gnc', 20)
        if nu is not None:
            u = float(nu[0]);  v_sway = float(nu[1])
            if self.prev_nu_valid and h > 0:
                du_dt = (u         - self.prev_nu[0]) / h
                dv_dt = (v_sway    - self.prev_nu[1]) / h
            else:
                du_dt = dv_dt = 0.0
            self.prev_nu[:] = nu
            self.prev_nu_valid = True
        else:
            u = v_sway = du_dt = dv_dt = 0.0

        tau_x_eff_val = debug.get('tau_X', 0.0)
        if tau_x_eff_val > 0:
            _disc = XU_LIN * XU_LIN + 4.0 * XU_QUAD * tau_x_eff_val
            ref_speed_kn = ((-XU_LIN + math.sqrt(_disc)) / (2.0 * XU_QUAD)) / 0.5144
        else:
            ref_speed_kn = 0.0

        self.control_debug_pub.publish(
            ControlDebugMessage(
                timestamp=now,
                target_heading=debug['psi_d'],
                heading_error=debug['heading_error'],
                cross_track_error=debug['cross_track_error'],
                surge_vel=u,
                sway_vel=v_sway,
                surge_acc=du_dt,
                sway_acc=dv_dt,
                tau_x_eff=tau_x_eff_val,
                tau_x_cruise=debug.get('tau_X_cruise', 0.0),
                v_cruise=debug.get('v_cruise', 0.0),
                wp_index=debug.get('wp_index', 0),
                dist_to_wp=debug.get('dist_to_next', 0.0),
                ref_speed_kn=ref_speed_kn,
            ).model_dump()
        )

    # ================================================================
    #  WP ROUTE EXECUTION
    # ================================================================

    def _start_wp_route(self, payload: dict):
        """Start WP Route following."""
        if not self.is_armed and not self.rt_sim_active:
            logger.warning("GNC: Cannot start WP Route — vehicle not armed (ARM first in REAL mode)")
            return
        waypoints_raw = payload.get('waypoints', [])
        if len(waypoints_raw) < 2:
            logger.error("GNC: WP Route needs at least 2 waypoints")
            return

        # Override cruise speed if provided
        cruise_speed_kn_override = payload.get('cruise_speed_kn')
        if cruise_speed_kn_override is not None:
            self.gnc_config.cruise_speed_kn = float(cruise_speed_kn_override)
            self._apply_gnc_config()

        direction = payload.get('direction', 'forward')
        completion = payload.get('completion', 'stop')

        waypoints = [Waypoint(**wp) if isinstance(wp, dict) else wp for wp in waypoints_raw]

        if direction == 'reverse':
            waypoints = list(reversed(waypoints))
            self.wp_route_forward = False
        else:
            self.wp_route_forward = True

        self.wp_route_waypoints = waypoints
        self.wp_route_direction = direction
        self.wp_route_completion = completion
        self.wp_route_loops = 0

        # Set origin from first WP
        lat0, lon0 = waypoints[0].lat, waypoints[0].lon
        self.wp_route_origin = (lat0, lon0)

        # Convert to NED
        wp_ned = []
        for wp in waypoints:
            N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
            wp_ned.append({'N': N, 'E': E, 'radius': wp.radius, 'speed': wp.speed})

        # Create controller and load waypoints
        self.controller = _make_default_controller(self.gnc_config)

        # Bridge from current position to WP[0] so vehicle navigates to WP0 first
        N_cur, E_cur = latlon_to_ned(self.lat, self.lon, lat0, lon0)
        current_wp = {'N': N_cur, 'E': E_cur,
                      'radius': wp_ned[0]['radius'], 'speed': wp_ned[0]['speed']}
        bridge = [current_wp] + list(wp_ned)
        self.controller.set_waypoints(bridge)

        psi0 = math.atan2(wp_ned[0]['E'] - E_cur, wp_ned[0]['N'] - N_cur)
        self.controller.reset(psi_init=psi0)

        self.wp_route_active = True
        # Reset failsafe timers (monotonic). Only refresh comm heartbeat if the
        # WS is currently alive — otherwise leave it stale so an already-lost
        # link is detected on the next _check_failsafes tick.
        self.gnss_lost_since = None
        self.gnss_failsafe_active = False
        if self.ws_alive:
            self.last_heartbeat_time = time.monotonic()

        logger.info(f"GNC: WP Route started — {len(waypoints)} WPs, "
                     f"dir={direction}, completion={completion}")

    def _stop_wp_route(self):
        """Stop WP Route and zero motors."""
        if not self.wp_route_active:
            return
        self.wp_route_active = False
        self.current_n1 = 0.0
        self.current_n2 = 0.0
        # Publish zero motor commands
        self.control_cmd_pub.publish({
            'timestamp': time.time(),
            'port_pct': 0.0,
            'starboard_pct': 0.0,
            'n1_rads': 0.0,
            'n2_rads': 0.0,
            'source': 'gnc',
        })
        logger.info("GNC: WP Route stopped")

    def _run_wp_route(self, now):
        """Execute one WP route control step."""
        if self.lat == 0.0 and self.lon == 0.0:
            return
        if not self.wp_route_origin or not self.controller:
            return

        lat0, lon0 = self.wp_route_origin
        N, E = latlon_to_ned(self.lat, self.lon, lat0, lon0)

        eta = np.array([N, E, 0.0, 0.0, 0.0, self.heading_rad], float)
        nu = np.array([self.sog_ms, 0.0, 0.0, 0.0, 0.0, self.yaw_rate], float)
        h = 1.0 / settings.LOOP_RATES.get('gnc', 20)

        n1, n2, debug = self.controller.step(eta, nu, h)
        self._publish_control(n1, n2, debug, now, nu=nu)

        # Check mission completion
        if self.controller.is_mission_complete():
            self._handle_wp_route_completion()

    def _handle_wp_route_completion(self):
        """Handle WP route completion based on completion mode."""
        mode = self.wp_route_completion

        if mode == 'stop':
            logger.info("GNC: WP Route completed — stopping")
            self._stop_wp_route()

        elif mode == 'loop':
            self.wp_route_loops += 1
            logger.info(f"GNC: WP Route loop #{self.wp_route_loops}, restarting")

            lat0, lon0 = self.wp_route_origin
            wp_ned = []
            for wp in self.wp_route_waypoints:
                N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
                wp_ned.append({'N': N, 'E': E, 'radius': wp.radius, 'speed': wp.speed})

            # Bridge from current position to WP[0]
            N_cur, E_cur = latlon_to_ned(self.lat, self.lon, lat0, lon0)
            current_wp = {'N': N_cur, 'E': E_cur,
                          'radius': wp_ned[0]['radius'], 'speed': wp_ned[0]['speed']}
            bridge = [current_wp] + list(wp_ned)
            self.controller.set_waypoints(bridge)
            psi0 = math.atan2(wp_ned[0]['E'] - E_cur, wp_ned[0]['N'] - N_cur)
            self.controller.reset(psi0)

        elif mode == 'loop_reverse':
            self.wp_route_loops += 1
            self.wp_route_forward = not self.wp_route_forward
            logger.info(f"GNC: WP Route loop #{self.wp_route_loops}, reversing "
                         f"({'fwd' if self.wp_route_forward else 'rev'})")

            self.wp_route_waypoints = list(reversed(self.wp_route_waypoints))
            lat0, lon0 = self.wp_route_origin
            wp_ned = []
            for wp in self.wp_route_waypoints:
                N, E = latlon_to_ned(wp.lat, wp.lon, lat0, lon0)
                wp_ned.append({'N': N, 'E': E, 'radius': wp.radius, 'speed': wp.speed})

            N_cur, E_cur = latlon_to_ned(self.lat, self.lon, lat0, lon0)
            current_wp = {'N': N_cur, 'E': E_cur,
                          'radius': wp_ned[0]['radius'], 'speed': wp_ned[0]['speed']}
            bridge = [current_wp] + list(wp_ned)
            self.controller.set_waypoints(bridge)
            psi0 = math.atan2(wp_ned[0]['E'] - E_cur, wp_ned[0]['N'] - N_cur)
            self.controller.reset(psi0)

    # ================================================================
    #  STATION KEEPING EXECUTION
    # ================================================================

    def _start_station(self, payload: dict):
        """Start station keeping."""
        if not self.is_armed and not self.rt_sim_active:
            logger.warning("GNC: Cannot start Station Keeping — vehicle not armed (ARM first in REAL mode)")
            return
        lat_s = payload.get('lat', self.lat)
        lon_s = payload.get('lon', self.lon)
        reaching_radius = payload.get('reaching_radius', 3.0)
        station_radius = payload.get('station_radius', 10.0)

        # Override cruise speed if provided
        tau_x_override = payload.get('cruise_speed_kn')
        if tau_x_override is not None:
            self.gnc_config.cruise_speed_kn = float(tau_x_override)
            self._apply_gnc_config()

        if lat_s == 0.0 and lon_s == 0.0:
            logger.error("GNC: Station keeping needs a valid position")
            return

        # Use station WP as origin
        N_station, E_station = 0.0, 0.0  # station is at origin
        station_ned = {'N': N_station, 'E': E_station}
        self._station_origin = (lat_s, lon_s)

        B = SALPA1_K_POS * np.array([[1, 1], [-SALPA1_L1, -SALPA1_L2]])
        B_inv = np.linalg.inv(B)

        self.station_keeper = StationKeeper(
            station_ned=station_ned,
            reaching_radius=reaching_radius,
            station_radius=station_radius,
            m_yaw=SALPA1_IZZ,
            B_inv=B_inv,
            n_max=SALPA1_N_MAX,
            n_min=SALPA1_N_MIN,
            wn=self.gnc_config.wn,
            zeta=self.gnc_config.zeta,
            wn_d=self.gnc_config.wn_ref,
            zeta_d=self.gnc_config.zeta_ref,
            k_delta=self.gnc_config.k_delta,
            delta_min=self.gnc_config.delta_min,
            gamma=self.gnc_config.gamma,
            tau_X=_speed_kn_to_tau_x(self.gnc_config.cruise_speed_kn),
            vel_profiler_enabled=self.gnc_config.vel_profiler_enabled,
            accel_ms2=self.gnc_config.accel_ms2,
        )

        # Initialize approach path from current position
        N_cur, E_cur = latlon_to_ned(self.lat, self.lon, lat_s, lon_s)
        eta_init = np.array([N_cur, E_cur, 0.0, 0.0, 0.0, self.heading_rad])
        self.station_keeper._load_approach(eta_init)

        self.station_active = True
        self.gnss_lost_since = None
        self.gnss_failsafe_active = False
        if self.ws_alive:
            self.last_heartbeat_time = time.monotonic()

        logger.info(f"GNC: Station keeping started at ({lat_s:.6f}, {lon_s:.6f}), "
                     f"reaching={reaching_radius}m, station={station_radius}m")

    def _stop_station(self):
        """Stop station keeping and zero motors."""
        if not self.station_active:
            return
        self.station_active = False
        self.station_keeper = None
        self.current_n1 = 0.0
        self.current_n2 = 0.0
        self.control_cmd_pub.publish({
            'timestamp': time.time(),
            'port_pct': 0.0,
            'starboard_pct': 0.0,
            'n1_rads': 0.0,
            'n2_rads': 0.0,
            'source': 'gnc',
        })
        logger.info("GNC: Station keeping stopped")

    def _run_station_keeping(self, now):
        """Execute one station-keeping step."""
        if self.station_keeper is None:
            return
        if self.lat == 0.0 and self.lon == 0.0:
            return

        if self._station_origin is None:
            logger.warning("GNC: _run_station_keeping() called before _start_station(); aborting.")
            return
        lat0, lon0 = self._station_origin
        N, E = latlon_to_ned(self.lat, self.lon, lat0, lon0)

        eta = np.array([N, E, 0.0, 0.0, 0.0, self.heading_rad], float)
        nu = np.array([self.sog_ms, 0.0, 0.0, 0.0, 0.0, self.yaw_rate], float)
        h = 1.0 / settings.LOOP_RATES.get('gnc', 20)

        n1, n2, debug = self.station_keeper.step(eta, nu, h)
        self._publish_control(n1, n2, debug, now, nu=nu)

    # ================================================================
    #  FAIL-SAFE MONITORING
    # ================================================================

    def _check_failsafes(self, now):
        """Check GNSS loss and comm loss failsafes. `now` is monotonic time."""
        fs = self.failsafe_config

        # --- GNSS loss check ---
        if self.last_gnss_fix_type < fs.min_gnss_fix:
            if self.gnss_lost_since is None:
                self.gnss_lost_since = now
            elif not self.gnss_failsafe_active and now - self.gnss_lost_since > fs.ins_timeout:
                logger.warning(f"GNC FAILSAFE: GNSS lost for {fs.ins_timeout}s — {fs.ins_action}")
                if fs.ins_action == 'emergency_stop':
                    self._emergency_stop()
                else:
                    self._failsafe_station_keeping()
                self.gnss_failsafe_active = True  # latch: prevent re-trigger until GNSS restored
        else:
            self.gnss_lost_since = None
            self.gnss_failsafe_active = False

        # --- Comm loss check ---
        # Skip until the FIRST link-alive event arrives (cold-start guard:
        # frontend may not have connected yet).
        if self.last_heartbeat_time is None:
            return
        if now - self.last_heartbeat_time > fs.comm_timeout:
            logger.warning(f"GNC FAILSAFE: Comm lost for {fs.comm_timeout}s — {fs.comm_action}")
            if fs.comm_action == 'return_home' and self.home_wp:
                self._failsafe_return_home()
            else:
                self._failsafe_station_keeping()
            self.last_heartbeat_time = now  # reset to avoid repeated triggers

    def _emergency_stop(self):
        """Emergency stop: zero motors, deactivate all modes."""
        logger.warning("GNC: EMERGENCY STOP — motors off")
        self.wp_route_active = False
        self.station_active = False
        self.station_keeper = None
        self.is_armed = False
        self.current_n1 = 0.0
        self.current_n2 = 0.0
        self.control_cmd_pub.publish({
            'timestamp': time.time(),
            'port_pct': 0.0,
            'starboard_pct': 0.0,
            'n1_rads': 0.0,
            'n2_rads': 0.0,
            'source': 'gnc',
        })
        # Sync Manager state via the dedicated GNC_SYNC topic (no self-loop).
        self.sync_pub.publish({
            'timestamp': time.time(),
            'op': 'emergency_stop',
        })

    def _failsafe_station_keeping(self):
        """Switch to station keeping at current position."""
        logger.warning("GNC FAILSAFE: Switching to station keeping at current position")
        self.wp_route_active = False
        station_payload = {
            'lat': self.lat,
            'lon': self.lon,
            'reaching_radius': 3.0,
            'station_radius': 10.0,
        }
        self._start_station(station_payload)
        # Sync Manager via dedicated topic.
        self.sync_pub.publish({
            'timestamp': time.time(),
            'op': 'failsafe_station',
            'station_wp': {'lat': self.lat, 'lon': self.lon},
            'reaching_radius': station_payload['reaching_radius'],
            'station_radius': station_payload['station_radius'],
        })

    def _failsafe_return_home(self):
        """Navigate back to the Home waypoint."""
        if not self.home_wp:
            logger.warning("GNC FAILSAFE: No home WP set, falling back to station keeping")
            self._failsafe_station_keeping()
            return
        logger.warning(f"GNC FAILSAFE: Returning home to ({self.home_wp['lat']:.6f}, {self.home_wp['lon']:.6f})")
        self.wp_route_active = False
        self.station_active = False
        self.station_keeper = None
        home_route_payload = {
            'waypoints': [
                {'lat': self.lat, 'lon': self.lon, 'radius': 5.0, 'speed': 1.0},
                {'lat': self.home_wp['lat'], 'lon': self.home_wp['lon'], 'radius': 5.0, 'speed': 1.0},
            ],
            'direction': 'forward',
            'completion': 'stop',
        }
        self._start_wp_route(home_route_payload)
        # Sync Manager via dedicated topic.
        self.sync_pub.publish({
            'timestamp': time.time(),
            'op': 'failsafe_return_home',
            'home_wp': dict(self.home_wp),
            'current_wp': {'lat': self.lat, 'lon': self.lon},
        })

    # ================================================================
    #  REAL-TIME SIMULATION
    # ================================================================

    def _start_rt_sim(self, payload: dict):
        """Initialize and start the real-time simulation physics engine."""
        try:
            cfg = RTSimConfig(**payload)
        except Exception as e:
            logger.error(f"GNC: Invalid RT sim config: {e}")
            return

        self.rt_sim_config = cfg
        logger.info("GNC: Starting RT simulation (Physics Engine Only)")

        # Safety: force DISARM before sim so real motors cannot be activated.
        if self.is_armed:
            self.is_armed = False
            self.cmd_pub.publish(CommandMessage(
                timestamp=time.time(),
                type=CommandType.DISARM,
                payload={'_source': 'gnc_internal'},
            ).model_dump())
            logger.warning("GNC: Auto-DISARMED — real motors cannot run during simulation")

        lat0 = cfg.current_lat
        lon0 = cfg.current_lon
        self.rt_sim_origin = (lat0, lon0)
        self.rt_sim_waypoints = []
        self.rt_sim_wp_ned = []

        self.rt_sim_eta = np.zeros(6)
        self.rt_sim_eta[5] = math.radians(cfg.current_heading)
        self.rt_sim_nu = np.zeros(6)
        self.rt_sim_u_actual = np.array([0.0, 0.0])

        self.rt_sim_model = Salpa1Model(
            payload_mass=cfg.payload_kg,
            V_current=cfg.current_speed,
            beta_current=cfg.current_dir,
            tau_X=cfg.surge_force,
        )
        self.rt_sim_controller = None

        self.rt_sim_t = 0.0
        self.rt_sim_start_time = time.time()
        self.rt_sim_loops = 0

        # Mute real sensors
        self.cmd_pub.publish(CommandMessage(
            timestamp=time.time(),
            type=CommandType.MUTE_SENSORS,
            payload={},
        ).model_dump())

        # Reset motor commands to zeroes
        self.current_n1 = 0.0
        self.current_n2 = 0.0

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

        # Publish final status
        self.sim_status_pub.publish(RTSimStatus(
            timestamp=time.time(),
            running=False,
            elapsed_time=self.rt_sim_t,
        ).model_dump())

        # Clean up
        self.rt_sim_model = None
        self.rt_sim_eta = None
        self.rt_sim_nu = None
        
        logger.info(f"GNC: RT simulation stopped after {self.rt_sim_t:.1f}s")

    def _rt_sim_step(self, now):
        """Execute one RT simulation step: dynamics + publish."""
        cfg = self.rt_sim_config
        dt = cfg.time_step
        model = self.rt_sim_model

        # --- Compute thrust ---
        # The motor positions are driven by standard routines pushing values to self.current_n1 / n2
        u_control = np.array([self.current_n1, self.current_n2], dtype=float)

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

        # --- Publish sim status ---
        # Minimal sim status now that pathing is decoupled
        self.sim_status_pub.publish(RTSimStatus(
            timestamp=now,
            running=True,
            elapsed_time=self.rt_sim_t,
            total_time=cfg.total_time,
            gnss_mode=cfg.gnss_mode,
        ).model_dump())
