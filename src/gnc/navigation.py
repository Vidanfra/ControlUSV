#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Navigation Process — dummy passthrough (future EKF/sensor fusion).

Subscribes to sensor/gnss and sensor/imu, forwards a unified navigation
state on gnc/ekf_state.  When a real EKF is implemented, the body of
the loop() method is replaced with the filter update logic.
"""

import math
import time
import numpy as np
from loguru import logger

from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import ImuState, USVState, OffsetsConfig

# Mean Earth radius [m] (WGS-84 mean) used for the local flat-earth
# metre <-> degree conversion of the lever-arm correction.
_EARTH_RADIUS_M = 6_371_000.0

# Rx(180 deg): converts the attitude reference frame of a z-up IMU such as the
# WT901C (x north, y west, z up) into NED. It is a property of the sensor
# family, not of how the sensor is bolted to the hull.
_SENSOR_REF_TO_NED = np.diag([1.0, -1.0, -1.0])

# A GNSS heading older than this is considered lost and the magnetometer takes
# over; an IMU older than this stops feeding rates to the autopilot.
_GNSS_HEADING_TIMEOUT_S = 2.0
_IMU_TIMEOUT_S = 0.5


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
    Navigation module — currently a raw passthrough.

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
        # acceleration term
        self._prev_w = None
        self._prev_w_t = 0.0

        # Gyro-sign cross-check against the GNSS heading derivative
        self._prev_heading = None
        self._prev_heading_t = 0.0
        self._wz_sign_mismatch = 0
        self._wz_sign_warned = False

        # Sensor lever-arm offsets (CRP compensation). Synced from the Manager
        # heartbeat (system/status), which is the persistence authority.
        self.offsets_config = OffsetsConfig()

        # Validity
        self.has_gnss = False
        self.has_imu = False

        logger.info("Navigation Process initialized (passthrough + CRP lever-arm mode)")

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
                        logger.debug("Navigation: offsets_config synced from heartbeat")
                except Exception as e:
                    logger.warning(f"Navigation: invalid offsets_config in heartbeat: {e}")

        # --- Consume GNSS ---
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

            hs = data.get('heading_status', '')
            if hs in ('A', 'S'):
                # 'S' is a simulated heading from the RT sim.
                self._gnss_heading_rad = math.radians(data.get('heading', 0.0))
                self._gnss_heading_status = hs
                self._gnss_heading_t = time.time()

            self.source = data.get('source', 'sensor')
            self.has_gnss = True

        # --- Consume IMU ---
        imu_updated = False
        while True:
            msg = self.imu_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            imu_source = data.get('source', 'sensor')
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

        if imu_updated:
            self._publish_imu_state()

        # --- Publish unified state ---
        if not self.has_gnss:
            return  # No position data yet

        now = time.time()
        imu_fresh = (now - self.last_imu_time) < _IMU_TIMEOUT_S

        # Heading source arbitration: the dual antenna wins while it is fresh,
        # otherwise the magnetometer takes over and the status degrades.
        if (now - self._gnss_heading_t) < _GNSS_HEADING_TIMEOUT_S:
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

        # A stale rate would keep feeding the autopilot derivative term after an
        # IMU dropout; publish zero instead.
        w = self.w_crp if imu_fresh else np.zeros(3)
        self._check_yaw_rate_sign(math.radians(w[2]), now)

        try:
            state = USVState(
                timestamp=now,
                lat=crp_lat,
                lon=crp_lon,
                altitude=crp_alt,
                speed=self.speed,
                course=self.course,
                heading=self.heading_rad,
                roll_crp=self.roll_crp,
                pitch_crp=self.pitch_crp,
                yaw_crp=self.yaw_crp,
                wx_crp=float(w[0]),
                wy_crp=float(w[1]),
                wz_crp=float(w[2]),
                accx_crp=float(self.acc_crp[0]),
                accy_crp=float(self.acc_crp[1]),
                accz_crp=float(self.acc_crp[2]),
                mag_heading_crp=self.mag_heading_crp,
                heading_status=self.heading_status,
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
            w_dot = (w - self._prev_w) / dt
        else:
            w_dot = np.zeros(3)
        self._prev_w, self._prev_w_t = w, ts

        return a_body - np.cross(w_dot, r) - np.cross(w, np.cross(w, r))

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


    def _body_to_ned(self, r_body):
        """Rotate a body-frame vector (x fwd, y stbd, z down) into the local
        NED frame (North, East, Down) using the current attitude.

        Uses the ZYX (yaw-pitch-roll) rotation R = Rz(psi)·Ry(theta)·Rx(phi).
        Heading (yaw) dominates the horizontal correction; roll/pitch refine
        the vertical/horizontal cross terms. Roll/pitch arrive from the IMU in
        degrees, heading is already in radians.
        """
        rx, ry, rz = r_body
        phi = math.radians(self.roll_crp)
        theta = math.radians(self.pitch_crp)
        psi = self.heading_rad

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

    def _antenna_to_crp(self, lat_deg, lon_deg, alt_m):
        """Return the (lat, lon, altitude) of the CRP given the position of the
        stern GNSS antenna, which is the one providing the fix.

        The lever arm from the antenna to the CRP in the body frame is
        ``-offset`` (the CRP is the origin, and ``offset`` is the antenna
        position relative to it). That vector is rotated into NED and applied
        as a local flat-earth metre → degree correction.
        """
        ant = self.offsets_config.gnss_stern

        # Body-frame vector pointing from the antenna to the CRP.
        r_body = (-ant.x, -ant.y, -ant.z)
        d_north, d_east, d_down = self._body_to_ned(r_body)

        # Flat-earth conversion of the local NED offset to lat/lon/altitude.
        lat_rad = math.radians(lat_deg)
        d_lat = math.degrees(d_north / _EARTH_RADIUS_M)
        cos_lat = math.cos(lat_rad)
        if abs(cos_lat) < 1e-9:
            d_lon = 0.0
        else:
            d_lon = math.degrees(d_east / (_EARTH_RADIUS_M * cos_lat))

        crp_lat = lat_deg + d_lat
        crp_lon = lon_deg + d_lon
        crp_alt = alt_m - d_down   # altitude is up-positive, NED down is down-positive
        return crp_lat, crp_lon, crp_alt
