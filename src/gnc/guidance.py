#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guidance module for USV path following.

Contains:
- refModel3: 3rd-order reference model for smooth trajectory generation
- ALOSpathFollowing: Adaptive Line-of-Sight path following algorithm

Adapted from simulator code for production use.

Reference: T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
Motion Control. 2nd Edition, Wiley.
"""

import math
from src.gnc.gnc_utils import ssa, wrapTo2Pi


def refModel3(x_d, v_d, a_d, r, wn_d, zeta_d, v_max, sampleTime):
    """
    3rd-order reference model for smooth trajectory generation.

    Generates smooth desired position, velocity and acceleration that track
    a reference setpoint r. Acts as a critically damped low-pass filter.

    Transfer function: H(s) = wn^3 / [(s + wn)^2 * (s + 2*zeta*wn)]

    Args:
        x_d: Current desired position state [rad or m]
        v_d: Current desired velocity state [rad/s or m/s]
        a_d: Current desired acceleration state [rad/s^2 or m/s^2]
        r: Reference setpoint to track [rad or m]
        wn_d: Natural frequency of the reference model [rad/s]
        zeta_d: Relative damping ratio [-]
        v_max: Maximum allowed velocity magnitude [rad/s or m/s]
        sampleTime: Discrete sampling time step [s]

    Returns:
        (x_d, v_d, a_d): Updated desired states after one time step
    """
    # Jerk from 3rd-order dynamics
    j_d = (wn_d ** 3 * (r - x_d)
           - (2 * zeta_d + 1) * wn_d ** 2 * v_d
           - (2 * zeta_d + 1) * wn_d * a_d)

    # Forward Euler integration
    x_d += sampleTime * v_d
    v_d += sampleTime * a_d
    a_d += sampleTime * j_d

    # Velocity saturation
    v_d = max(-v_max, min(v_d, v_max))

    return x_d, v_d, a_d


def ALOSpathFollowing(eta, wk, wk_1, Delta, gamma=0.0, beta_c=0.0,
                      h=0.02, prev_progress=0.0):
    """
    Adaptive Line-of-Sight (ALOS) path following algorithm.

    Computes the desired heading to follow a straight-line path between
    two waypoints, using a virtual target point on the path segment.

    Args:
        eta: numpy array [N, E, ...] — current vehicle state (at least 2 elements)
        wk: numpy array [N_k, E_k] — current (previous) waypoint
        wk_1: numpy array [N_k+1, E_k+1] — next waypoint
        Delta: Look-ahead distance [m]
        gamma: Adaptive sideslip gain (0 = no adaptation)
        beta_c: Current sideslip estimate [rad]
        h: Sampling time [s]
        prev_progress: Previous along-track progress [m] (monotonicity)

    Returns:
        psi_d: Desired heading [rad], wrapped to [0, 2*pi]
        beta_c_new: Updated sideslip estimate [rad]
        ye: Cross-track error [m]
        target_s: Current along-track progress [m]
        N_t: Virtual target North position [m]
        E_t: Virtual target East position [m]
    """
    # Current position
    N = eta[0]
    E = eta[1]

    # Path vector
    d_N = wk_1[0] - wk[0]
    d_E = wk_1[1] - wk[1]
    L = math.sqrt(d_N ** 2 + d_E ** 2)

    # Path angle
    pi_h = math.atan2(d_E, d_N)

    # Cross-track error
    ye = -(N - wk[0]) * math.sin(pi_h) + (E - wk[1]) * math.cos(pi_h)

    # Along-track projection
    if L > 0:
        s = ((N - wk[0]) * d_N + (E - wk[1]) * d_E) / L
    else:
        s = 0

    # Virtual target progress
    target_s = s + Delta

    # Monotonicity constraint
    target_s = max(target_s, prev_progress)

    # Box constraint: stay within segment [0, L]
    clamped_s = max(0.0, min(target_s, L))

    # Virtual target point
    if L > 0:
        N_t = wk[0] + clamped_s * (d_N / L)
        E_t = wk[1] + clamped_s * (d_E / L)
    else:
        N_t = wk[0]
        E_t = wk[1]

    # LOS heading: angle from vehicle to virtual target
    psi_los = math.atan2(E_t - E, N_t - N)

    # Sideslip adaptation
    beta_dot = gamma * (Delta / math.sqrt(Delta ** 2 + ye ** 2)) * ye
    beta_c_new = beta_c + h * beta_dot

    # Desired heading
    psi_d_raw = psi_los - beta_c_new
    psi_d = wrapTo2Pi(psi_d_raw)

    return psi_d, beta_c_new, ye, target_s, N_t, E_t
