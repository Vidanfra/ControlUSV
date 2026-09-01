#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GNSS-aided multiplicative error-state inertial navigation process.

Raw sensor data is transformed to the vessel body frame and CRP before a
15-state MEKF propagates position, velocity, attitude, and IMU biases. GNSS
position, velocity, and dual-antenna heading provide quality-adaptive aiding.
"""

import math
import time
import numpy as np
from loguru import logger

from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import ImuState, InsConfig, USVState, OffsetsConfig
from src.gnc.gnc_utils import latlon_to_ned, ned_to_latlon
from src.gnc.ins_mekf import InsMekf, MekfTuning

# Rx(180 deg): converts the attitude reference frame of a z-up IMU such as the
# WT901C (x north, y west, z up) into NED. It is a property of the sensor
# family, not of how the sensor is bolted to the hull.
_SENSOR_REF_TO_NED = np.diag([1.0, -1.0, -1.0])

# A GNSS heading older than this is considered lost and the magnetometer takes
# over; an IMU older than this stops feeding rates to the autopilot.
_GNSS_HEADING_TIMEOUT_S = 2.0
_IMU_TIMEOUT_S = 0.5

# Cut-off of the low-pass applied to the differentiated gyro rate.
_WDOT_LPF_HZ = 1.0


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _rot_zyx(roll_deg, pitch_deg, yaw_deg):
    """Rotation matrix for the ZYX sequence R = Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    cr, sr = math.cos(math.radians(roll_deg)), math.sin(math.radians(roll_deg))
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp,     cp * sr,                cp * cr],
    ])


def _euler_zyx(R):
    """Extract (roll, pitch, yaw) in degrees from a ZYX rotation matrix."""
    pitch = math.degrees(-math.asin(max(-1.0, min(1.0, R[2, 0]))))
    yaw = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    roll = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    return roll, pitch, yaw


class NavigationProcess(ServiceProcess):
    """
    Navigation module with selectable GNSS-only and GNSS-aided INS modes.

    Subscribes to:
        - sensor/gnss : position, heading, speed
        - sensor/imu  : attitude (roll, pitch, yaw)
        - system/status : sensor lever-arm offsets (OffsetsConfig)

    Publishes to:
        - gnc/imu_state : transformed IMU sample in the body frame / at CRP
        - gnc/ekf_state : USVState (combined navigation solution, referenced
                          to the vessel CRP after lever-arm compensation)
    """

    def setup(self):
        # Subscribers
        self.gnss_sub = Subscriber([Topics.SENSOR_GNSS])
        self.imu_sub = Subscriber([Topics.SENSOR_IMU])
        self.status_sub = Subscriber([Topics.SYSTEM_STATUS])

        # Publisher
        self.imu_pub = Publisher(Topics.IMU_STATE)
        self.nav_pub = Publisher(Topics.STATE_ESTIMATION)

        # Latest sensor data
        self.lat = 0.0
        self.lon = 0.0
        self.altitude = 0.0
        self.heading_rad = 0.0
        self.heading_status = ""
        self.speed = 0.0
        self.course = 0.0
        self.source = "sensor"
        self.fix_type = 0
        self.gnss_horizontal_accuracy_m = None
        self.gnss_vertical_accuracy_m = None
        self.gnss_timestamp = 0.0
        self.gnss_lat_crp = None
        self.gnss_lon_crp = None
        self.gnss_altitude_crp = None
        self.last_gnss_time = 0.0
        self.last_valid_gnss_time = 0.0

        # Heading from the GNSS dual antenna, kept apart from the published
        # heading so that it can expire and let the magnetometer take over.
        self._gnss_heading_rad = 0.0
        self._gnss_heading_status = ""
        self._gnss_heading_t = 0.0

        # IMU solution referenced to the body frame and the CRP
        self.roll_crp = 0.0
        self.pitch_crp = 0.0
        self.yaw_crp = 0.0
        self.w_crp = np.zeros(3)     # [deg/s]
        self.acc_crp = np.zeros(3)   # [m/s^2]
        self.mag_heading_crp = 0.0
        self.last_imu_time = 0.0
        self.imu_timestamp = 0.0
        self.imu_source = "sensor"

        # Previous body angular rate [rad/s] for the lever-arm angular
        # acceleration term, plus its low-pass state.
        self._prev_w = None
        self._prev_w_t = 0.0
        self._w_dot = np.zeros(3)

        # Gyro-sign cross-check against the GNSS heading derivative
        self._prev_heading = None
        self._prev_heading_t = 0.0
        self._wz_sign_mismatch = 0
        self._wz_sign_warned = False

        # Sensor lever-arm offsets (CRP compensation). Synced from the Manager
        # heartbeat (system/status), which is the persistence authority.
        self.offsets_config = OffsetsConfig()

        # Multiplicative error-state INS. It initializes only after both a valid
        # global GNSS fix and a transformed IMU attitude are available.
        self.ins_config = InsConfig()
        self.ins_filter = self._new_ins_filter()
        self.ins_origin = None
        self._last_ins_imu_t = 0.0
        self._last_attitude_aid_t = 0.0
        self._ins_source = None

        # Validity
        self.has_gnss = False
        self.has_imu = False

        logger.info("Navigation Process initialized (15-state INS MEKF + GNSS-only fallback)")

    def _new_ins_filter(self):
        cfg = self.ins_config
        return InsMekf(MekfTuning(
            accel_noise_mps2_sqrt_hz=cfg.accel_noise_mps2_sqrt_hz,
            gyro_noise_rad_s_sqrt_hz=math.radians(cfg.gyro_noise_deg_s_sqrt_hz),
            accel_bias_noise_mps2_sqrt_hz=cfg.accel_bias_noise_mps2_sqrt_hz,
            gyro_bias_noise_rad_s_sqrt_hz=math.radians(
                cfg.gyro_bias_noise_deg_s_sqrt_hz
            ),
            accel_bias_tau_s=cfg.accel_bias_tau_s,
            gyro_bias_tau_s=cfg.gyro_bias_tau_s,
            gravity_aiding_noise=cfg.gravity_aiding_noise,
            gravity_gate_mps2=cfg.gravity_gate_mps2,
            innovation_gate_sigma=cfg.innovation_gate_sigma,
        ))

    def _gnss_heading_is_fresh(self, now=None):
        """True while the dual-antenna heading is both valid and recent.

        The UM982 keeps emitting THS with status 'V' once the heading solution
        is lost, so the last good value must expire on its own.
        """
        now = time.time() if now is None else now
        return (
            self._gnss_heading_status in ('A', 'S')
            and now - self._gnss_heading_t < _GNSS_HEADING_TIMEOUT_S
        )

    def _reset_ins(self, reason):
        was_initialized = getattr(self, 'ins_filter', None) is not None and self.ins_filter.initialized
        self.ins_filter = self._new_ins_filter()
        self.ins_origin = None
        self._last_ins_imu_t = 0.0
        self._last_attitude_aid_t = 0.0
        self._ins_source = None
        if was_initialized:
            logger.info(f"Navigation: INS reset ({reason})")

    def _initialize_ins_if_ready(self):
        now = time.time()
        if (
            not self.ins_config.enabled
            or self.ins_filter.initialized
            or not self.has_imu
            or not self.has_gnss
            or self.fix_type <= 0
            or now - self.last_valid_gnss_time > self.ins_config.gnss_loss_timeout_s
            or (self.lat == 0.0 and self.lon == 0.0)
        ):
            return False

        if self._gnss_heading_is_fresh(now):
            initial_yaw = self._gnss_heading_rad
            yaw_sigma = math.radians(self.ins_config.gnss_heading_sigma_deg)
        elif self.ins_config.use_magnetometer:
            initial_yaw = math.radians(self.mag_heading_crp)
            yaw_sigma = math.radians(self.ins_config.mag_heading_sigma_deg)
        else:
            initial_yaw = math.radians(self.yaw_crp)
            yaw_sigma = math.radians(30.0)

        attitude = np.array([
            math.radians(self.roll_crp),
            math.radians(self.pitch_crp),
            initial_yaw,
        ])
        if self.source == 'sim':
            crp_lat, crp_lon, crp_alt = self.lat, self.lon, self.altitude
        else:
            crp_lat, crp_lon, crp_alt = self._antenna_to_crp(
                self.lat, self.lon, self.altitude, attitude
            )
        self.ins_origin = (crp_lat, crp_lon, crp_alt)
        self.gnss_lat_crp = crp_lat
        self.gnss_lon_crp = crp_lon
        self.gnss_altitude_crp = crp_alt
        velocity_ned = self._antenna_velocity_to_crp(
            np.array([
                self.speed * math.cos(self.course),
                self.speed * math.sin(self.course),
                0.0,
            ]),
            attitude,
        )
        position_sigma = self._gnss_position_sigmas()
        self.ins_filter.initialize(
            position_ned=np.zeros(3),
            velocity_ned=velocity_ned,
            euler_rpy_rad=attitude,
            position_sigma=position_sigma,
            velocity_sigma=(
                self.ins_config.gnss_velocity_sigma_mps,
                self.ins_config.gnss_velocity_sigma_mps,
                1.0,
            ),
            attitude_sigma_rad=(math.radians(5.0), math.radians(5.0), yaw_sigma),
        )
        self._last_ins_imu_t = self.imu_timestamp
        self._ins_source = self.imu_source
        logger.info(
            f"Navigation: INS initialized at {crp_lat:.8f}, {crp_lon:.8f} "
            f"with fix type {self.fix_type}"
        )
        return True

    def _process_ins_imu_sample(self):
        if not self.ins_filter.initialized:
            self._initialize_ins_if_ready()
        if not self.ins_filter.initialized:
            return

        sample_time = self.imu_timestamp
        dt = sample_time - self._last_ins_imu_t
        self._last_ins_imu_t = sample_time
        if dt <= 0.0:
            return
        if dt > 0.5:
            logger.warning(f"Navigation: skipped {dt:.2f}s IMU sample gap")
            return

        latitude_rad = math.radians(self.ins_origin[0])
        self.ins_filter.predict(
            self.acc_crp,
            np.radians(self.w_crp),
            dt,
            latitude_rad,
        )

        # Wave-induced tilt and magnetic disturbance are strongly correlated, so
        # applying these at the full IMU rate would make the filter track the
        # disturbance instead of averaging it out.
        aiding_period = 1.0 / self.ins_config.attitude_aiding_rate_hz
        if sample_time - self._last_attitude_aid_t < aiding_period:
            return
        self._last_attitude_aid_t = sample_time

        horizontal_speed = float(np.linalg.norm(self.ins_filter.velocity[0:2]))
        if horizontal_speed <= self.ins_config.gravity_max_speed_mps:
            self.ins_filter.update_gravity(self.acc_crp, latitude_rad)

        if self.ins_config.use_magnetometer and not self._gnss_heading_is_fresh():
            self.ins_filter.update_heading(
                math.radians(self.mag_heading_crp),
                math.radians(self.ins_config.mag_heading_sigma_deg),
            )

    def _update_ins_from_gnss(self):
        if self._gnss_heading_is_fresh():
            heading_sigma = (
                math.radians(0.2) if self._gnss_heading_status == 'S'
                else math.radians(self.ins_config.gnss_heading_sigma_deg)
            )
            self.ins_filter.update_heading(self._gnss_heading_rad, heading_sigma)

        position_sigma = self._gnss_position_sigmas()
        if self.fix_type <= 0 or position_sigma is None:
            return

        attitude = self.ins_filter.euler_rpy_rad
        if self.source == 'sim':
            crp_lat, crp_lon, crp_alt = self.lat, self.lon, self.altitude
        else:
            crp_lat, crp_lon, crp_alt = self._antenna_to_crp(
                self.lat, self.lon, self.altitude, attitude
            )
        self.gnss_lat_crp = crp_lat
        self.gnss_lon_crp = crp_lon
        self.gnss_altitude_crp = crp_alt
        north, east = latlon_to_ned(
            crp_lat, crp_lon, self.ins_origin[0], self.ins_origin[1]
        )
        down = self.ins_origin[2] - crp_alt
        self.ins_filter.update_position(
            np.array([north, east, down]),
            position_sigma,
            clip_innovation=self.fix_type == 4,
        )

        velocity_scale = {4: 1.0, 5: 2.0, 2: 4.0, 1: 6.0}.get(
            self.fix_type, 6.0
        )
        velocity_ne = self._antenna_velocity_to_crp(
            np.array([
                self.speed * math.cos(self.course),
                self.speed * math.sin(self.course),
                0.0,
            ]),
            attitude,
        )[0:2]
        velocity_sigma = np.full(
            2, self.ins_config.gnss_velocity_sigma_mps * velocity_scale
        )
        self.ins_filter.update_velocity(velocity_ne, velocity_sigma)

    def _gnss_position_sigmas(self):
        cfg = self.ins_config
        if self.fix_type == 4:
            horizontal = self.gnss_horizontal_accuracy_m
            vertical = self.gnss_vertical_accuracy_m
            horizontal_axis = (
                horizontal / math.sqrt(2.0)
                if isinstance(horizontal, (int, float)) and horizontal > 0.0
                else cfg.rtk_fixed_horizontal_floor_m
            )
            return np.array([
                max(cfg.rtk_fixed_horizontal_floor_m, horizontal_axis),
                max(cfg.rtk_fixed_horizontal_floor_m, horizontal_axis),
                max(
                    cfg.rtk_fixed_vertical_floor_m,
                    vertical if isinstance(vertical, (int, float)) and vertical > 0.0
                    else cfg.rtk_fixed_vertical_floor_m,
                ),
            ])
        if self.fix_type == 5:
            return np.array([
                cfg.rtk_float_horizontal_sigma_m,
                cfg.rtk_float_horizontal_sigma_m,
                cfg.rtk_float_vertical_sigma_m,
            ])
        if self.fix_type == 2:
            return np.array([
                cfg.dgps_horizontal_sigma_m,
                cfg.dgps_horizontal_sigma_m,
                cfg.dgps_vertical_sigma_m,
            ])
        if self.fix_type == 1:
            return np.array([
                cfg.gps_horizontal_sigma_m,
                cfg.gps_horizontal_sigma_m,
                cfg.gps_vertical_sigma_m,
            ])
        return None

    def _effective_fix_type(self, now):
        if now - self.last_valid_gnss_time > self.ins_config.gnss_loss_timeout_s:
            return 0
        return self.fix_type

    def _position_source(self, now):
        if self.source == 'sim':
            return 'SIM'
        fix_type = self._effective_fix_type(now)
        if fix_type <= 0:
            if self.ins_config.enabled and self.ins_filter.initialized:
                return 'INS'
            return 'GNSS_LOST'
        return {
            4: 'RTK_FIXED',
            5: 'RTK_FLOAT',
            2: 'DGNSS',
            1: 'GPS',
        }.get(fix_type, 'GNSS')

    def _publish_ins_navigation(self, now, imu_fresh):
        north, east, down = self.ins_filter.position
        lat, lon = ned_to_latlon(
            north, east, self.ins_origin[0], self.ins_origin[1]
        )
        altitude = self.ins_origin[2] - down
        roll, pitch, yaw = self.ins_filter.euler_rpy_rad
        velocity_north, velocity_east = self.ins_filter.velocity[0:2]
        speed = math.hypot(velocity_north, velocity_east)
        course = (
            math.atan2(velocity_east, velocity_north) if speed > 1e-6 else self.course
        )

        gnss_heading_fresh = self._gnss_heading_is_fresh(now)
        if self.source == 'sim' and gnss_heading_fresh:
            heading_status = 'S'
        elif gnss_heading_fresh:
            heading_status = 'A'
        elif self.ins_config.use_magnetometer and imu_fresh:
            heading_status = 'M'
        else:
            heading_status = 'I'

        corrected_rate = (
            self.w_crp - np.degrees(self.ins_filter.gyro_bias)
            if imu_fresh else np.zeros(3)
        )
        corrected_force = self.acc_crp - self.ins_filter.accel_bias
        self.heading_rad = yaw
        self.heading_status = heading_status
        self.speed = speed
        self.course = course
        self._check_yaw_rate_sign(math.radians(corrected_rate[2]), now)
        state = USVState(
            timestamp=now,
            lat=lat,
            lon=lon,
            altitude=altitude,
            gnss_timestamp=self.gnss_timestamp,
            gnss_lat_crp=self.gnss_lat_crp,
            gnss_lon_crp=self.gnss_lon_crp,
            gnss_altitude_crp=self.gnss_altitude_crp,
            speed=speed,
            course=course,
            heading=yaw,
            roll_crp=math.degrees(roll),
            pitch_crp=math.degrees(pitch),
            yaw_crp=math.degrees(yaw),
            wx_crp=float(corrected_rate[0]),
            wy_crp=float(corrected_rate[1]),
            wz_crp=float(corrected_rate[2]),
            accx_crp=float(corrected_force[0]),
            accy_crp=float(corrected_force[1]),
            accz_crp=float(corrected_force[2]),
            mag_heading_crp=self.mag_heading_crp,
            heading_status=heading_status,
            fix_type=self._effective_fix_type(now),
            ins_active=True,
            position_source=self._position_source(now),
            horizontal_accuracy_m=self.ins_filter.horizontal_position_sigma_m,
            vertical_accuracy_m=self.ins_filter.vertical_position_sigma_m,
            source=self.source,
        )
        self.nav_pub.publish(state.model_dump())

    def loop(self):
        """Main loop — runs at 20 Hz. Consume sensors and publish unified state."""

        # --- Consume offsets config from Manager heartbeat ---
        while True:
            msg = self.status_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            if 'offsets_config' in data:
                try:
                    new_cfg = OffsetsConfig(**data['offsets_config'])
                    if new_cfg.model_dump() != self.offsets_config.model_dump():
                        self.offsets_config = new_cfg
                        self._reset_ins("sensor offsets changed")
                        logger.debug("Navigation: offsets_config synced from heartbeat")
                except Exception as e:
                    logger.warning(f"Navigation: invalid offsets_config in heartbeat: {e}")
            if 'ins_config' in data:
                try:
                    new_cfg = InsConfig(**data['ins_config'])
                    if new_cfg.model_dump() != self.ins_config.model_dump():
                        self.ins_config = new_cfg
                        self._reset_ins("INS configuration changed")
                        logger.info(
                            f"Navigation: INS {'enabled' if new_cfg.enabled else 'disabled'}"
                        )
                except Exception as e:
                    logger.warning(f"Navigation: invalid ins_config in heartbeat: {e}")

        ins_filter_before_sensor_updates = self.ins_filter
        ins_was_initialized = self.ins_filter.initialized

        # --- Consume GNSS ---
        gnss_updated = False
        while True:
            msg = self.gnss_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.lat = data.get('lat', self.lat)
            self.lon = data.get('lon', self.lon)
            self.altitude = data.get('alt', self.altitude)
            self.speed = data.get('sog_knots', 0.0) * 0.514444  # knots → m/s
            self.course = math.radians(data.get('cog', 0.0))
            self.fix_type = int(data.get('fix_type', 0))
            self.gnss_horizontal_accuracy_m = data.get('horizontal_accuracy_m')
            self.gnss_vertical_accuracy_m = data.get('vertical_accuracy_m')
            self.gnss_timestamp = float(data.get('timestamp') or time.time())
            self.last_gnss_time = time.time()
            if self.fix_type > 0:
                self.last_valid_gnss_time = self.last_gnss_time

            hs = data.get('heading_status', '')
            if hs in ('A', 'S'):
                # 'S' is a simulated heading from the RT sim.
                self._gnss_heading_rad = math.radians(data.get('heading', 0.0))
                self._gnss_heading_status = hs
                self._gnss_heading_t = time.time()

            self.source = data.get('source', 'sensor')
            self.has_gnss = True
            gnss_updated = True

        # --- Consume IMU ---
        imu_updated = False
        while True:
            msg = self.imu_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            imu_source = data.get('source', 'sensor')
            if self.ins_filter.initialized and self._ins_source != imu_source:
                self._reset_ins("IMU source changed")
            if imu_source == 'sim':
                # The simulated IMU already reports in the body frame at the CRP.
                self.source = 'sim'
                self.roll_crp = float(data.get('roll_raw', 0.0))
                self.pitch_crp = float(data.get('pitch_raw', 0.0))
                self.yaw_crp = float(data.get('yaw_raw', 0.0))
                self.w_crp = np.array([float(data.get('wx_raw', 0.0)),
                                       float(data.get('wy_raw', 0.0)),
                                       float(data.get('wz_raw', 0.0))])
                self.acc_crp = np.array([float(data.get('ax_raw', 0.0)),
                                         float(data.get('ay_raw', 0.0)),
                                         float(data.get('az_raw', 0.0))])
                self.mag_heading_crp = self.yaw_crp % 360.0
            else:
                self._imu_to_crp(data)

            self.imu_timestamp = float(data.get('timestamp') or time.time())
            self.imu_source = imu_source
            self.last_imu_time = time.time()
            self.has_imu = True
            imu_updated = True

            if self.ins_config.enabled:
                self._process_ins_imu_sample()

        if imu_updated:
            self._publish_imu_state()

        if self.ins_config.enabled:
            self._initialize_ins_if_ready()
            if (
                gnss_updated
                and ins_was_initialized
                and self.ins_filter is ins_filter_before_sensor_updates
                and self.ins_filter.initialized
            ):
                self._update_ins_from_gnss()

        # --- Publish unified state ---
        now = time.time()
        imu_fresh = (now - self.last_imu_time) < _IMU_TIMEOUT_S
        if self.ins_config.enabled and self.ins_filter.initialized:
            try:
                self._publish_ins_navigation(now, imu_fresh)
            except Exception as e:
                logger.error(f"Navigation: failed to publish INS state: {e}")
            return

        if not self.has_gnss:
            return  # A global solution cannot initialize without GNSS

        # Heading source arbitration: the dual antenna wins while it is fresh,
        # otherwise the magnetometer takes over and the status degrades.
        if self._gnss_heading_is_fresh(now):
            self.heading_rad = self._gnss_heading_rad
            self.heading_status = self._gnss_heading_status
        elif imu_fresh:
            self.heading_rad = math.radians(self.mag_heading_crp)
            self.heading_status = 'M'
        else:
            self.heading_status = ''

        # Translate the GNSS antenna fix to the vessel CRP (lever-arm
        # compensation, rotated by the current attitude). The fix comes from
        # the stern antenna; the bow antenna is only used for heading, so the
        # stern lever arm is applied.
        # In simulation the vessel model already reports the CRP, so the
        # correction is skipped for sim-sourced data.
        if self.source == 'sim':
            crp_lat, crp_lon, crp_alt = self.lat, self.lon, self.altitude
        else:
            crp_lat, crp_lon, crp_alt = self._antenna_to_crp(
                self.lat, self.lon, self.altitude
            )
        self.gnss_lat_crp = crp_lat
        self.gnss_lon_crp = crp_lon
        self.gnss_altitude_crp = crp_alt

        # A stale rate would keep feeding the autopilot derivative term after an
        # IMU dropout; publish zero instead.
        w = self.w_crp if imu_fresh else np.zeros(3)
        acc = self.acc_crp if imu_fresh else np.zeros(3)
        self._check_yaw_rate_sign(math.radians(w[2]), now)

        try:
            effective_fix_type = self._effective_fix_type(now)
            state = USVState(
                timestamp=now,
                lat=crp_lat,
                lon=crp_lon,
                altitude=crp_alt,
                gnss_timestamp=self.gnss_timestamp,
                gnss_lat_crp=crp_lat,
                gnss_lon_crp=crp_lon,
                gnss_altitude_crp=crp_alt,
                speed=self.speed,
                course=self.course,
                heading=self.heading_rad,
                roll_crp=self.roll_crp,
                pitch_crp=self.pitch_crp,
                yaw_crp=self.yaw_crp,
                wx_crp=float(w[0]),
                wy_crp=float(w[1]),
                wz_crp=float(w[2]),
                accx_crp=float(acc[0]),
                accy_crp=float(acc[1]),
                accz_crp=float(acc[2]),
                mag_heading_crp=self.mag_heading_crp,
                heading_status=self.heading_status,
                fix_type=effective_fix_type,
                ins_active=False,
                position_source=self._position_source(now),
                horizontal_accuracy_m=(
                    self.gnss_horizontal_accuracy_m if effective_fix_type > 0 else None
                ),
                vertical_accuracy_m=(
                    self.gnss_vertical_accuracy_m if effective_fix_type > 0 else None
                ),
                source=self.source,
            )
            self.nav_pub.publish(state.model_dump())
        except Exception as e:
            logger.error(f"Navigation: failed to publish state: {e}")

    def _publish_imu_state(self):
        try:
            state = ImuState(
                timestamp=self.imu_timestamp,
                roll_crp=self.roll_crp,
                pitch_crp=self.pitch_crp,
                yaw_crp=self.yaw_crp,
                wx_crp=float(self.w_crp[0]),
                wy_crp=float(self.w_crp[1]),
                wz_crp=float(self.w_crp[2]),
                accx_crp=float(self.acc_crp[0]),
                accy_crp=float(self.acc_crp[1]),
                accz_crp=float(self.acc_crp[2]),
                mag_heading_crp=self.mag_heading_crp,
                source=self.imu_source,
            )
            self.imu_pub.publish(state.model_dump())
        except Exception as e:
            logger.error(f"Navigation: failed to publish transformed IMU: {e}")

    def _imu_to_crp(self, data):
        """Convert a raw IMU sample to the body frame at the CRP and store it.

        The mounting rotation is the ZYX sequence Rz(yaw)Ry(pitch)Rx(roll)
        configured in Settings > Offsets; it maps a sensor-frame vector into
        the body frame (x bow, y starboard, z down). The attitude is rebuilt as
        a matrix so that the rotation is exact for any mounting angle, and the
        accelerations are moved from the IMU to the CRP through the lever arm.
        """
        m = self.offsets_config.imu
        R = _rot_zyx(m.roll_deg, m.pitch_deg, m.yaw_deg)

        # Attitude: sensor DCM -> NED reference -> body frame
        A = _rot_zyx(float(data.get('roll_raw', 0.0)),
                     float(data.get('pitch_raw', 0.0)),
                     float(data.get('yaw_raw', 0.0)))
        roll, pitch, yaw = _euler_zyx(_SENSOR_REF_TO_NED @ A @ R.T)
        self.roll_crp = roll
        self.pitch_crp = pitch
        self.yaw_crp = _wrap180(yaw)

        # Rates and specific force are plain vectors in the sensor frame
        w_body = R @ np.array([float(data.get('wx_raw', 0.0)),
                               float(data.get('wy_raw', 0.0)),
                               float(data.get('wz_raw', 0.0))])
        a_body = R @ np.array([float(data.get('ax_raw', 0.0)),
                               float(data.get('ay_raw', 0.0)),
                               float(data.get('az_raw', 0.0))])
        mag_body = R @ np.array([float(data.get('mx_raw', 0.0)),
                                 float(data.get('my_raw', 0.0)),
                                 float(data.get('mz_raw', 0.0))])

        ts = float(data.get('timestamp') or time.time())
        self.w_crp = w_body  # a rigid body rotates at the same rate everywhere
        self.acc_crp = self._accel_to_crp(a_body, w_body, ts)
        self.mag_heading_crp = self._mag_heading(mag_body, roll, pitch)

    def _accel_to_crp(self, a_body, w_body_deg, ts):
        """Remove the rigid-body lever-arm terms so the specific force refers to
        the CRP: a_crp = a_imu - w_dot x r - w x (w x r)."""
        off = self.offsets_config.imu
        r = np.array([off.x, off.y, off.z])
        w = np.radians(w_body_deg)

        dt = ts - self._prev_w_t
        if self._prev_w is not None and 0.0 < dt < 0.5:
            # Differentiating a noisy 20 Hz gyro amplifies its noise by 1/dt, and
            # the lever arm turns that straight into fake specific force.
            alpha = dt / (dt + 1.0 / (2.0 * math.pi * _WDOT_LPF_HZ))
            self._w_dot += alpha * ((w - self._prev_w) / dt - self._w_dot)
        else:
            self._w_dot = np.zeros(3)
        self._prev_w, self._prev_w_t = w, ts

        return a_body - np.cross(self._w_dot, r) - np.cross(w, np.cross(w, r))

    def _mag_heading(self, mag_body, roll_deg, pitch_deg):
        """Tilt-compensated magnetic heading [0,360) from the body-frame
        magnetometer vector, including declination and the user trim."""
        m = self.offsets_config.imu
        phi, theta = math.radians(roll_deg), math.radians(pitch_deg)
        mx, my, mz = float(mag_body[0]), float(mag_body[1]), float(mag_body[2])

        xh = mx * math.cos(theta) + math.sin(theta) * (my * math.sin(phi) + mz * math.cos(phi))
        yh = my * math.cos(phi) - mz * math.sin(phi)
        hdg = math.degrees(math.atan2(-yh, xh))
        return (hdg + m.mag_declination_deg + m.mag_user_offset_deg) % 360.0

    def _check_yaw_rate_sign(self, yaw_rate, now):
        """Warn if the gyro rate opposes the GNSS heading derivative — a wrong
        IMU axis flip turns the autopilot rate feedback into positive feedback."""
        if self._wz_sign_warned or now - self._prev_heading_t < 0.5:
            return

        prev, prev_t = self._prev_heading, self._prev_heading_t
        self._prev_heading, self._prev_heading_t = self.heading_rad, now
        if prev is None or self.heading_status != 'A':
            return

        d_psi = (self.heading_rad - prev + math.pi) % (2 * math.pi) - math.pi
        hdg_rate = d_psi / (now - prev_t)
        if abs(hdg_rate) < 0.15 or abs(yaw_rate) < 0.15:
            return

        if hdg_rate * yaw_rate < 0:
            self._wz_sign_mismatch += 1
            if self._wz_sign_mismatch >= 5:
                self._wz_sign_warned = True
                logger.warning(
                    "Navigation: IMU yaw rate consistently opposes the GNSS heading "
                    "derivative — check the IMU mounting angles in Settings > Offsets."
                )
        else:
            self._wz_sign_mismatch = 0

    # ------------------------------------------------------------------
    #  CRP lever-arm compensation
    # ------------------------------------------------------------------


    def _body_to_ned(self, r_body, attitude_rpy_rad=None):
        """Rotate a body-frame vector (x fwd, y stbd, z down) into the local
        NED frame (North, East, Down) using the current attitude.

        Uses the ZYX (yaw-pitch-roll) rotation R = Rz(psi)·Ry(theta)·Rx(phi).
        Heading (yaw) dominates the horizontal correction; roll/pitch refine
        the vertical/horizontal cross terms. Roll/pitch arrive from the IMU in
        degrees, heading is already in radians.
        """
        rx, ry, rz = r_body
        if attitude_rpy_rad is None:
            phi = math.radians(self.roll_crp)
            theta = math.radians(self.pitch_crp)
            psi = self.heading_rad
        else:
            phi, theta, psi = attitude_rpy_rad

        cphi, sphi = math.cos(phi), math.sin(phi)
        cth, sth = math.cos(theta), math.sin(theta)
        cpsi, spsi = math.cos(psi), math.sin(psi)

        # R = Rz(psi) @ Ry(theta) @ Rx(phi)
        n = (
            cpsi * cth * rx
            + (cpsi * sth * sphi - spsi * cphi) * ry
            + (cpsi * sth * cphi + spsi * sphi) * rz
        )
        e = (
            spsi * cth * rx
            + (spsi * sth * sphi + cpsi * cphi) * ry
            + (spsi * sth * cphi - cpsi * sphi) * rz
        )
        d = (
            -sth * rx
            + cth * sphi * ry
            + cth * cphi * rz
        )
        return n, e, d

    def _antenna_to_crp(self, lat_deg, lon_deg, alt_m, attitude_rpy_rad=None):
        """Return the (lat, lon, altitude) of the CRP given the position of the
        stern GNSS antenna, which is the one providing the fix.

        The lever arm from the antenna to the CRP in the body frame is
        ``-offset`` (the CRP is the origin, and ``offset`` is the antenna
        position relative to it). That vector is rotated into NED and converted
        back to degrees with the same local tangent plane the filter uses.
        """
        ant = self.offsets_config.gnss_stern

        # Body-frame vector pointing from the antenna to the CRP.
        r_body = (-ant.x, -ant.y, -ant.z)
        d_north, d_east, d_down = self._body_to_ned(
            r_body, attitude_rpy_rad
        )

        crp_lat, crp_lon = ned_to_latlon(d_north, d_east, lat_deg, lon_deg)
        crp_alt = alt_m - d_down   # altitude is up-positive, NED down is down-positive
        return crp_lat, crp_lon, crp_alt

    def _antenna_velocity_to_crp(self, velocity_ned, attitude_rpy_rad=None):
        """Return the NED velocity of the CRP given the ground velocity reported
        by the stern GNSS antenna.

        A rotating rigid body gives ``v_antenna = v_crp + w x r_antenna``, so the
        lever-arm term is subtracted. Skipped when the IMU rate is stale, since
        an old angular rate would inject a spurious velocity.
        """
        velocity_ned = np.asarray(velocity_ned, dtype=float)
        if self.source == 'sim' or (time.time() - self.last_imu_time) > _IMU_TIMEOUT_S:
            return velocity_ned
        ant = self.offsets_config.gnss_stern
        lever_arm_body = np.cross(
            np.radians(self.w_crp), np.array([ant.x, ant.y, ant.z])
        )
        return velocity_ned - np.array(
            self._body_to_ned(lever_arm_body, attitude_rpy_rad)
        )
