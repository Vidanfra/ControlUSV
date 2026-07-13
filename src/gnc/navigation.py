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
from loguru import logger

from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import USVState, OffsetsConfig

# Mean Earth radius [m] (WGS-84 mean) used for the local flat-earth
# metre <-> degree conversion of the lever-arm correction.
_EARTH_RADIUS_M = 6_371_000.0


class NavigationProcess(ServiceProcess):
    """
    Navigation module — currently a raw passthrough.

    Subscribes to:
        - sensor/gnss : position, heading, speed
        - sensor/imu  : attitude (roll, pitch, yaw)
        - system/status : sensor lever-arm offsets (OffsetsConfig)

    Publishes to:
        - gnc/ekf_state : USVState (combined navigation solution, referenced
                          to the vessel CRP after lever-arm compensation)
    """

    def setup(self):
        # Subscribers
        self.gnss_sub = Subscriber([Topics.SENSOR_GNSS])
        self.imu_sub = Subscriber([Topics.SENSOR_IMU])
        self.status_sub = Subscriber([Topics.SYSTEM_STATUS])

        # Publisher
        self.nav_pub = Publisher(Topics.STATE_ESTIMATION)

        # Latest sensor data
        self.lat = 0.0
        self.lon = 0.0
        self.altitude = 0.0
        self.heading_rad = 0.0
        self.heading_status = ""
        self.speed = 0.0
        self.course = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.source = "sensor"

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
            if hs == 'A':
                self.heading_rad = math.radians(data.get('heading', 0.0))
                self.heading_status = 'A'
            elif hs == 'S':
                # Simulated heading from RT sim
                self.heading_rad = math.radians(data.get('heading', 0.0))
                self.heading_status = 'S'

            self.source = data.get('source', 'sensor')
            self.has_gnss = True

        # --- Consume IMU ---
        while True:
            msg = self.imu_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.roll = data.get('roll', self.roll)
            self.pitch = data.get('pitch', self.pitch)
            self.yaw = data.get('yaw', self.yaw)

            # If GNSS heading is not available, use IMU magnetic heading
            if self.heading_status not in ('A', 'S'):
                mag_heading = data.get('mag_heading', 0.0)
                self.heading_rad = math.radians(mag_heading)
                self.heading_status = 'M'

            imu_source = data.get('source', 'sensor')
            if imu_source == 'sim':
                self.source = 'sim'
            self.has_imu = True

        # --- Publish unified state ---
        if not self.has_gnss:
            return  # No position data yet

        # Translate the GNSS antenna fix to the vessel CRP (lever-arm
        # compensation, rotated by the current attitude). By default the fix
        # comes from the stern antenna; the bow antenna is only used for
        # heading, so the stern lever arm is applied.
        # In simulation the vessel model already reports the CRP, so the
        # correction is skipped for sim-sourced data.
        if self.source == 'sim':
            crp_lat, crp_lon, crp_alt = self.lat, self.lon, self.altitude
        else:
            crp_lat, crp_lon, crp_alt = self._antenna_to_crp(
                self.lat, self.lon, self.altitude
            )

        try:
            state = USVState(
                timestamp=time.time(),
                lat=crp_lat,
                lon=crp_lon,
                altitude=crp_alt,
                speed=self.speed,
                course=self.course,
                heading=self.heading_rad,
                roll=self.roll,
                pitch=self.pitch,
                yaw=self.yaw,
                heading_status=self.heading_status,
                source=self.source,
            )
            self.nav_pub.publish(state.model_dump())
        except Exception as e:
            logger.error(f"Navigation: failed to publish state: {e}")

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
        phi = math.radians(self.roll)
        theta = math.radians(self.pitch)
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
        active GNSS antenna.

        The lever arm from the antenna to the CRP in the body frame is
        ``-offset`` (the CRP is the origin, and ``offset`` is the antenna
        position relative to it). That vector is rotated into NED and applied
        as a local flat-earth metre → degree correction.
        """
        src = getattr(self.offsets_config, 'position_source', 'stern')
        ant = self.offsets_config.gnss_bow if src == 'bow' else self.offsets_config.gnss_stern

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
