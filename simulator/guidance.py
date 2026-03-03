#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guidance algorithms.

Reference: T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
Motion Control. 2nd. Edition, Wiley. 
URL: www.fossen.biz/wiley

Author:     Thor I. Fossen
"""

import numpy as np
import math

def refModel3(x_d, v_d, a_d, r, wn_d, zeta_d, v_max, sampleTime):
    """
    3rd-order reference model for smooth trajectory generation.
    
    Generates a smooth desired position x_d, velocity v_d, and acceleration a_d
    that tracks a reference setpoint r. The model acts as a critically damped
    low-pass filter, providing smooth transitions without overshoot.
    
    The transfer function is: H(s) = wn_d^3 / (s + wn_d)^2 * (s + 2*zeta_d*wn_d)
    
    Reference:
        T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
        Motion Control. 2nd Edition, Wiley. Chapter 12.1.2.
    
    Args:
        x_d (float): Current desired position state [rad or m]
        v_d (float): Current desired velocity state [rad/s or m/s]
        a_d (float): Current desired acceleration state [rad/s^2 or m/s^2]
        r (float): Reference setpoint to track [rad or m]
        wn_d (float): Natural frequency of the reference model [rad/s]
                      Higher values = faster response (typical: 0.1 - 1.0)
        zeta_d (float): Relative damping ratio [-]
                        zeta_d = 1.0 for critical damping (no overshoot)
                        zeta_d < 1.0 for underdamped (overshoot)
                        zeta_d > 1.0 for overdamped (slower response)
        v_max (float): Maximum allowed velocity magnitude [rad/s or m/s]
        sampleTime (float): Discrete sampling time step [s]
    
    Returns:
        tuple: (x_d, v_d, a_d) - Updated desired states after one time step
            - x_d (float): New desired position
            - v_d (float): New desired velocity (saturated to [-v_max, v_max])
            - a_d (float): New desired acceleration
    
    Example:
        >>> # Initialize states
        >>> x_d, v_d, a_d = 0.0, 0.0, 0.0
        >>> r = 1.0  # Target position
        >>> wn_d, zeta_d = 0.5, 1.0  # Natural freq and damping
        >>> v_max = 0.5  # Max velocity
        >>> h = 0.02  # 50 Hz sampling
        >>> 
        >>> # Simulation loop
        >>> for _ in range(100):
        ...     x_d, v_d, a_d = refModel3(x_d, v_d, a_d, r, wn_d, zeta_d, v_max, h)
    """
    
    # Compute desired "jerk" (derivative of acceleration) from 3rd-order dynamics
    # This is derived from the characteristic polynomial: (s + wn_d)^2 * (s + 2*zeta_d*wn_d)
    j_d = wn_d**3 * (r - x_d) - (2*zeta_d + 1) * wn_d**2 * v_d - (2*zeta_d + 1) * wn_d * a_d

    # Forward Euler integration to update states
    x_d += sampleTime * v_d             # Integrate velocity to get position
    v_d += sampleTime * a_d             # Integrate acceleration to get velocity
    a_d += sampleTime * j_d             # Integrate jerk to get acceleration
    
    # Velocity saturation to enforce physical limits
    if v_d > v_max:
        v_d = v_max
    elif v_d < -v_max: 
        v_d = -v_max    
    
    return x_d, v_d, a_d

def ssa(angle):
    """
    Smallest Signed Angle. Maps angle to range [-pi, pi).
    Vital for heading control to avoid 360-degree spins.
    """
    return (angle + math.pi) % (2 * math.pi) - math.pi

def wrapTo2Pi(angle):
    """
    Wrap angle to range [0, 2*pi).
    For display purposes (0 to 360 degrees).
    """
    return angle % (2 * math.pi)

def ALOSpathFollowing(eta, wk, wk_1, Delta, gamma, beta_c, h, prev_progress=0.0):
    """
    Adaptive Line-of-Sight (ALOS) path following algorithm.
    Modified to constrain virtual target point to path segment and monotonic progress.
    
    Inputs:
        eta: numpy array [N, E, psi, ...] - current state
        wk: numpy array [Nk, Ek] - previous waypoint
        wk_1: numpy array [Nk+1, Ek+1] - next waypoint
        Delta: float - look-ahead distance
        gamma: float - adaptive gain
        beta_c: float - current sideslip estimate
        h: float - sampling time
        prev_progress: float - previous along-track progress (s)
        
    Returns:
        psi_d: float - desired heading
        beta_c_new: float - updated sideslip estimate
        ye: float - cross-track error
        target_s: float - current along-track progress
    """
    
    # Extract current position
    N = eta[0]
    E = eta[1]
    
    # Path vector
    d_N = wk_1[0] - wk[0]
    d_E = wk_1[1] - wk[1]
    L = math.sqrt(d_N**2 + d_E**2)
    
    # Path angle (pi_h)
    pi_h = math.atan2(d_E, d_N)
    
    # Cross-track error (ye)
    ye = -(N - wk[0]) * math.sin(pi_h) + (E - wk[1]) * math.cos(pi_h)
    
    # Along-track distance (s) - Projection of vehicle position onto path
    if L > 0:
        s = ((N - wk[0]) * d_N + (E - wk[1]) * d_E) / L
    else:
        s = 0
        
    # Target progress (virtual point distance from wk)
    target_s = s + Delta
    
    # Monotonicity constraint: Virtual point cannot move backwards
    target_s = max(target_s, prev_progress)
    
    # Box constraint: Virtual point must stay within segment [0, L]
    clamped_s = max(0.0, min(target_s, L))
    
    # Calculate Virtual Target Point (N_t, E_t)
    if L > 0:
        N_t = wk[0] + clamped_s * (d_N / L)
        E_t = wk[1] + clamped_s * (d_E / L)
    else:
        N_t = wk[0]
        E_t = wk[1]
        
    # LOS Heading: Angle from vehicle to virtual target
    psi_los = math.atan2(E_t - E, N_t - N)
    
    # Adaptation law (beta_dot)
    beta_dot = gamma * (Delta / math.sqrt(Delta**2 + ye**2)) * ye
    
    # Update sideslip estimate (Euler integration)
    beta_c_new = beta_c + h * beta_dot
    
    # Desired heading
    psi_d_raw = psi_los - beta_c_new

    # Normalize angle to [0, 2*pi] for display consistency
    psi_d = wrapTo2Pi(psi_d_raw)
    
    return psi_d, beta_c_new, ye, target_s, N_t, E_t