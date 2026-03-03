#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Control methods.

Reference: T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
Motion Control. 2nd. Edition, Wiley. 
URL: www.fossen.biz/wiley

Author:     Thor I. Fossen
"""

import numpy as np
from python_vehicle_simulator.lib.guidance import refModel3
from python_vehicle_simulator.lib.gnc import ssa, Rzyx

# SISO PID pole placement
def PIDpolePlacement(
    e_int,
    e_x,
    e_v,
    x_d,
    v_d,
    a_d,
    m,
    d,
    k,
    wn_d,
    zeta_d,
    wn,
    zeta,
    r,
    v_max,
    sampleTime,
):
    """
    PID controller with Pole Placement and 3rd-order Reference Model.
    
    This function calculates the PID gains (Kp, Kd, Ki) automatically based on the 
    desired closed-loop response (wn, zeta) and the system model (m, d, k).
    
    Inputs:
        e_int: Accumulated integral error
        e_x:   Position/Heading error (x - x_d)
        e_v:   Velocity/Rate error (v - v_d)
        x_d, v_d, a_d: Current state of the reference model (pos, vel, acc)
        m, d, k: System model parameters (Inertia, Damping, Stiffness)
        wn_d, zeta_d: Tuning for the Reference Model (smoothness of setpoint)
        wn, zeta: Tuning for the PID Controller (aggressiveness of tracking)
        r:     Target setpoint (e.g., desired heading)
        v_max: Maximum allowed velocity in reference model
        sampleTime: Time step [s]
        
    Returns:
        u:     Control output (force/torque)
        e_int: Updated integral error
        x_d, v_d, a_d: Updated reference model states
        Kp, Kd, Ki: Calculated PID gains (for monitoring)
    """

    # PID gains based on pole placement
    # We want the closed loop dynamics to match: s^2 + 2*zeta*wn*s + wn^2
    # Kp: Stiffness required to achieve natural frequency wn
    Kp = m * wn ** 2.0 - k
    
    # Kd: Damping required to achieve damping ratio zeta
    Kd = m * 2.0 * zeta * wn - d
    
    # Ki: Integral gain, heuristically set to be slower than natural frequency
    Ki = (wn / 10.0) * Kp

    # PID control law
    # u = -Kp*error - Kd*rate_error - Ki*integral_error
    u = -Kp * e_x - Kd * e_v - Ki * e_int

    # Integral error, Euler's method
    e_int += sampleTime * e_x

    # 3rd-order reference model for smooth position, velocity and acceleration
    # This generates a smooth trajectory from current state to target 'r'
    [x_d, v_d, a_d] = refModel3(x_d, v_d, a_d, r, wn_d, zeta_d, v_max, sampleTime)

    return u, e_int, x_d, v_d, a_d, Kp, Kd, Ki


# MIMO nonlinear PID pole placement
def DPpolePlacement(
    e_int, M3, D3, eta3, nu3, x_d, y_d, psi_d, wn, zeta, eta_ref, sampleTime
):

    # PID gains based on pole placement
    M3_diag = np.diag(np.diag(M3))
    D3_diag = np.diag(np.diag(D3))
    
    Kp = wn @ wn @ M3_diag
    Kd = 2.0 * zeta @ wn @ M3_diag - D3_diag
    Ki = (1.0 / 10.0) * wn @ Kp

    # DP control law - setpoint regulation
    e = eta3 - np.array([x_d, y_d, psi_d])
    e[2] = ssa(e[2])
    R = Rzyx(0.0, 0.0, eta3[2])
    tau = (
        - np.matmul((R.T @ Kp), e)
        - np.matmul(Kd, nu3)
        - np.matmul((R.T @ Ki), e_int)
    )

    # Low-pass filters, Euler's method
    T = 5.0 * np.array([1 / wn[0][0], 1 / wn[1][1], 1 / wn[2][2]])
    x_d += sampleTime * (eta_ref[0] - x_d) / T[0]
    y_d += sampleTime * (eta_ref[1] - y_d) / T[1]
    psi_d += sampleTime * (eta_ref[2] - psi_d) / T[2]

    # Integral error, Euler's method
    e_int += sampleTime * e

    return tau, e_int, x_d, y_d, psi_d

# Heading autopilot - Intergral SMC (Equation 16.479 in Fossen 2021)
def integralSMC(
    e_int,
    e_x,
    e_v,
    x_d,
    v_d,
    a_d,
    T_nomoto,
    K_nomoto,
    wn_d,
    zeta_d,
    K_d,
    K_sigma,
    lam,
    phi_b,
    r,
    v_max,
    sampleTime,
):

    # Sliding surface
    v_r_dot = a_d - 2 * lam * e_v - lam ** 2 * ssa(e_x)
    v_r     = v_d - 2 * lam * ssa(e_x) - lam ** 2 * e_int
    sigma   = e_v + 2 * lam * ssa(e_x) + lam ** 2 * e_int

    #  Control law
    if abs(sigma / phi_b) > 1.0:
        delta = ( T_nomoto * v_r_dot + v_r - K_d * sigma 
                 - K_sigma * np.sign(sigma) ) / K_nomoto
    else:
        delta = ( T_nomoto * v_r_dot + v_r - K_d * sigma 
                 - K_sigma * (sigma / phi_b) ) / K_nomoto

    # Integral error, Euler's method
    e_int += sampleTime * ssa(e_x)

    # 3rd-order reference model for smooth position, velocity and acceleration
    [x_d, v_d, a_d] = refModel3(x_d, v_d, a_d, r, wn_d, zeta_d, v_max, sampleTime)

    return delta, e_int, x_d, v_d, a_d




