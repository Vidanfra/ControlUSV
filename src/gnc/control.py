#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Control module for USV heading control and motor allocation.

Contains:
- PIDpolePlacement: SISO PID heading controller with pole-placement gains
- controlAllocation: Convert surge force + yaw torque to propeller speeds

Adapted from simulator code for production use.

Reference: T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
Motion Control. 2nd Edition, Wiley.
"""

import math
import numpy as np
from src.gnc.guidance import refModel3
from src.gnc.gnc_utils import ssa


def PIDpolePlacement(e_int, e_x, e_v, x_d, v_d, a_d,
                     m, d, k, wn_d, zeta_d, wn, zeta,
                     r, v_max, sampleTime):
    """
    PID controller with pole placement and 3rd-order reference model.

    Gains are computed automatically from desired closed-loop response
    (wn, zeta) and the simplified system model (m, d, k):

        Kp = m * wn^2 - k
        Kd = 2 * m * zeta * wn - d
        Ki = (wn / 10) * Kp

    Control law: u = -Kp * e_x - Kd * e_v - Ki * e_int

    Args:
        e_int: Accumulated integral error
        e_x: Position/heading error (x - x_d)
        e_v: Velocity/rate error (v - v_d)
        x_d, v_d, a_d: Current reference model states
        m, d, k: System model parameters (inertia, damping, stiffness)
        wn_d, zeta_d: Reference model tuning
        wn, zeta: PID controller tuning
        r: Target setpoint [rad or m]
        v_max: Maximum reference velocity [rad/s or m/s]
        sampleTime: Time step [s]

    Returns:
        u: Control output (force/torque)
        e_int: Updated integral error
        x_d, v_d, a_d: Updated reference model states
        Kp, Kd, Ki: Calculated PID gains
    """
    # PID gains from pole placement
    Kp = m * wn ** 2.0 - k
    Kd = m * 2.0 * zeta * wn - d
    Ki = (wn / 10.0) * Kp

    # PID control law
    u = -Kp * e_x - Kd * e_v - Ki * e_int

    # Integral error (Euler's method)
    e_int += sampleTime * e_x

    # 3rd-order reference model
    x_d, v_d, a_d = refModel3(x_d, v_d, a_d, r, wn_d, zeta_d, v_max, sampleTime)

    return u, e_int, x_d, v_d, a_d, Kp, Kd, Ki


def controlAllocation(tau_X, tau_N, B_inv):
    """
    Convert surge force and yaw moment to individual propeller speeds.

    tau = B @ n_squared  →  n_squared = B_inv @ [tau_X, tau_N]
    n_i = sign(u_i) * sqrt(|u_i|)

    Args:
        tau_X: Desired surge force [N]
        tau_N: Desired yaw moment [N·m]
        B_inv: Inverse of the thrust configuration matrix (2x2)

    Returns:
        n1, n2: Propeller shaft speeds [rad/s]
    """
    tau = np.array([tau_X, tau_N])
    u_alloc = np.matmul(B_inv, tau)

    n1 = math.copysign(math.sqrt(abs(u_alloc[0])), u_alloc[0])
    n2 = math.copysign(math.sqrt(abs(u_alloc[1])), u_alloc[1])

    return n1, n2
