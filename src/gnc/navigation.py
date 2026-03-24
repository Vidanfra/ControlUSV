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
from src.core.models import USVState


class NavigationProcess(ServiceProcess):
    """
    Navigation module — currently a raw passthrough.

    Subscribes to:
        - sensor/gnss : position, heading, speed
        - sensor/imu  : attitude (roll, pitch, yaw)

    Publishes to:
        - gnc/ekf_state : USVState (combined navigation solution)
    """

    def setup(self):
        # Subscribers
        self.gnss_sub = Subscriber([Topics.SENSOR_GNSS])
        self.imu_sub = Subscriber([Topics.SENSOR_IMU])

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

        # Validity
        self.has_gnss = False
        self.has_imu = False

        logger.info("Navigation Process initialized (passthrough mode)")

    def loop(self):
        """Main loop — runs at 20 Hz. Consume sensors and publish unified state."""

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

        try:
            state = USVState(
                timestamp=time.time(),
                lat=self.lat,
                lon=self.lon,
                altitude=self.altitude,
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
