#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulated Sensor Generators for Real-Time Simulation.

Generates GNSS and IMU messages from the 6-DOF vehicle model state,
with configurable noise profiles to emulate different GNSS quality modes.

GNSS modes:
    - rtk_fix : Very small noise (~0.01 m), fix_type=4, 20+ sats
    - dgnss   : Moderate noise (~0.5 m) + slow sinusoidal drift, fix_type=2, 12 sats
    - gps     : Large noise (~2 m) + bigger sinusoidal drift, fix_type=1, 8 sats
"""

import math
import time
import random
import numpy as np

from src.core.models import GNSSData, ImuMessage
from src.gnc.gnc_utils import ned_to_latlon


# ============================================================================
# GNSS Noise Parameters per mode
# ============================================================================
GNSS_NOISE_PROFILES = {
    'rtk_fix': {
        'white_noise_m': 0.01,         # ~1 cm position noise
        'sinusoidal_amp_m': 0.0,       # no drift
        'sinusoidal_period_s': 1.0,    # irrelevant
        'fix_type': 4,
        'num_sats': 22,
        'hdop': 0.6,
        'vdop': 0.9,
        'heading_noise_deg': 0.05,
        'speed_noise_knots': 0.02,
    },
    'dgnss': {
        'white_noise_m': 0.5,          # ~50 cm noise
        'sinusoidal_amp_m': 1.0,       # 1 m sinusoidal drift
        'sinusoidal_period_s': 60.0,   # 60 s period
        'fix_type': 2,
        'num_sats': 12,
        'hdop': 1.8,
        'vdop': 2.5,
        'heading_noise_deg': 0.3,
        'speed_noise_knots': 0.1,
    },
    'gps': {
        'white_noise_m': 2.0,          # ~2 m noise
        'sinusoidal_amp_m': 5.0,       # 5 m sinusoidal drift
        'sinusoidal_period_s': 30.0,   # 30 s period
        'fix_type': 1,
        'num_sats': 8,
        'hdop': 3.5,
        'vdop': 5.0,
        'heading_noise_deg': 1.5,
        'speed_noise_knots': 0.3,
    },
}


def simulate_gnss(eta, nu, lat0, lon0, gnss_mode, t, dt):
    """
    Generate a GNSSData message from the vehicle model state.

    Args:
        eta: [N, E, D, phi, theta, psi] — vehicle state in NED
        nu:  [u, v, w, p, q, r] — body velocities
        lat0, lon0: NED origin (degrees)
        gnss_mode: 'rtk_fix', 'dgnss', or 'gps'
        t: current simulation time [s]
        dt: time step [s]

    Returns:
        GNSSData instance with source='sim'
    """
    profile = GNSS_NOISE_PROFILES.get(gnss_mode, GNSS_NOISE_PROFILES['rtk_fix'])

    N_true = float(eta[0])
    E_true = float(eta[1])
    psi = float(eta[5])

    # Add position noise
    wn = profile['white_noise_m']
    N_noisy = N_true + random.gauss(0, wn)
    E_noisy = E_true + random.gauss(0, wn)

    # Add sinusoidal drift (different phases for N and E)
    sa = profile['sinusoidal_amp_m']
    sp = profile['sinusoidal_period_s']
    if sa > 0 and sp > 0:
        N_noisy += sa * math.sin(2 * math.pi * t / sp)
        E_noisy += sa * math.sin(2 * math.pi * t / sp + math.pi / 3)

    # Convert to lat/lon
    lat, lon = ned_to_latlon(N_noisy, E_noisy, lat0, lon0)

    # Speed over ground
    speed_ms = math.sqrt(float(nu[0])**2 + float(nu[1])**2)
    sog_knots = speed_ms / 0.514444 + random.gauss(0, profile['speed_noise_knots'])
    sog_knots = max(0.0, sog_knots)
    sog_kmh = sog_knots * 1.852

    # Heading with noise
    heading_deg = math.degrees(psi) % 360
    heading_deg += random.gauss(0, profile['heading_noise_deg'])
    heading_deg = heading_deg % 360

    # Course over ground
    cog_deg = math.degrees(math.atan2(float(nu[1]), float(nu[0]) + 1e-10) + psi) % 360

    # UTC time from simulation time
    now = time.time()
    utc_struct = time.gmtime(now)
    utc_time = time.strftime("%H:%M:%S", utc_struct)
    utc_date = time.strftime("%d/%m/%Y", utc_struct)

    return GNSSData(
        timestamp=now,
        lat=lat,
        lon=lon,
        alt=0.0,
        fix_type=profile['fix_type'],
        num_satellites=profile['num_sats'],
        hdop=profile['hdop'],
        vdop=profile['vdop'],
        heading=heading_deg,
        heading_status='S',  # Simulated
        cog=cog_deg,
        sog_knots=sog_knots,
        sog_kmh=sog_kmh,
        utc_time=utc_time,
        utc_date=utc_date,
        source='sim',
    )


def simulate_imu(eta, nu):
    """
    Generate an ImuMessage from the vehicle model state.

    Args:
        eta: [N, E, D, phi, theta, psi] — vehicle state in NED
        nu:  [u, v, w, p, q, r] — body velocities

    Returns:
        ImuMessage instance with source='sim'
    """
    roll_deg = math.degrees(float(eta[3]))
    pitch_deg = math.degrees(float(eta[4]))
    yaw_deg = math.degrees(float(eta[5]))

    # Angular rates (rad/s → deg/s for IMU message)
    wx = math.degrees(float(nu[3]))
    wy = math.degrees(float(nu[4]))
    wz = math.degrees(float(nu[5]))

    # Simulated accelerations (simplified — gravity + body accel)
    # In a real scenario we'd need the force equation; approximate here
    ax = 0.0  # Simplified: no accelerometer simulation needed for nav
    ay = 0.0
    az = -9.80665  # Stationary specific force in the body z-down frame

    return ImuMessage(
        timestamp=time.time(),
        roll_raw=roll_deg,
        pitch_raw=pitch_deg,
        yaw_raw=yaw_deg,
        ax_raw=ax,
        ay_raw=ay,
        az_raw=az,
        wx_raw=wx,
        wy_raw=wy,
        wz_raw=wz,
        mx_raw=0.0,
        my_raw=0.0,
        mz_raw=0.0,
        temp=25.0,
        source='sim',
    )
