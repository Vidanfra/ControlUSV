#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNC utility functions for marine craft.

Standalone port of math/matrix utilities used by guidance and control modules.
No external dependencies beyond numpy/math.

Reference: T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
Motion Control. 2nd Edition, Wiley.
"""

import numpy as np
import math


def ssa(angle: float) -> float:
    """Smallest signed angle — maps angle to [-pi, pi)."""
    return (angle + math.pi) % (2 * math.pi) - math.pi


def wrapTo2Pi(angle: float) -> float:
    """Wrap angle to [0, 2*pi)."""
    return angle % (2 * math.pi)


def sat(x: float, x_min: float, x_max: float) -> float:
    """Saturate signal x to [x_min, x_max]."""
    if x > x_max:
        return x_max
    elif x < x_min:
        return x_min
    return x


def Smtrx(a):
    """
    3x3 skew-symmetric matrix S(a) such that a × b = S(a) @ b.
    """
    return np.array([
        [0, -a[2], a[1]],
        [a[2], 0, -a[0]],
        [-a[1], a[0], 0]
    ])


def Hmtrx(r):
    """
    6x6 system transformation matrix H(r).
    Property: inv(H(r)) = H(-r).

    If r = r_bg (CO → CG), then M_CO = H(r_bg).T @ M_CG @ H(r_bg).
    """
    H = np.identity(6, float)
    H[0:3, 3:6] = Smtrx(r).T
    return H


def Rzyx(phi, theta, psi):
    """
    Euler angle rotation matrix R ∈ SO(3) using the ZYX convention.
    Rotates from BODY to NED frame: p_ned = R @ p_body.
    """
    cphi = math.cos(phi)
    sphi = math.sin(phi)
    cth = math.cos(theta)
    sth = math.sin(theta)
    cpsi = math.cos(psi)
    spsi = math.sin(psi)

    return np.array([
        [cpsi * cth, -spsi * cphi + cpsi * sth * sphi, spsi * sphi + cpsi * cphi * sth],
        [spsi * cth, cpsi * cphi + sphi * sth * spsi, -cpsi * sphi + sth * spsi * cphi],
        [-sth, cth * sphi, cth * cphi]
    ])


def Tzyx(phi, theta):
    """
    Euler angle attitude transformation matrix T using ZYX convention.
    Maps body angular velocities to Euler angle rates.
    """
    cphi = math.cos(phi)
    sphi = math.sin(phi)
    cth = math.cos(theta)
    sth = math.sin(theta)

    try:
        T = np.array([
            [1, sphi * sth / cth, cphi * sth / cth],
            [0, cphi, -sphi],
            [0, sphi / cth, cphi / cth]
        ])
    except ZeroDivisionError:
        raise ValueError("Tzyx is singular for theta = ±90 degrees.")

    return T


def attitudeEuler(eta, nu, sampleTime):
    """
    Forward Euler integration of generalized position/Euler angles.
    eta[k+1] = eta[k] + h * [R @ nu_lin; T @ nu_ang]
    """
    p_dot = np.matmul(Rzyx(eta[3], eta[4], eta[5]), nu[0:3])
    v_dot = np.matmul(Tzyx(eta[3], eta[4]), nu[3:6])

    eta[0:3] = eta[0:3] + sampleTime * p_dot
    eta[3:6] = eta[3:6] + sampleTime * v_dot

    return eta


def m2c(M, nu):
    """
    Coriolis and centripetal matrix C from mass matrix M and velocity nu.
    Supports 6-DOF and 3-DOF models.
    """
    M = 0.5 * (M + M.T)  # symmetrize

    if len(nu) == 6:
        M11 = M[0:3, 0:3]
        M12 = M[0:3, 3:6]
        M21 = M12.T
        M22 = M[3:6, 3:6]

        nu1 = nu[0:3]
        nu2 = nu[3:6]
        dt_dnu1 = np.matmul(M11, nu1) + np.matmul(M12, nu2)
        dt_dnu2 = np.matmul(M21, nu1) + np.matmul(M22, nu2)

        C = np.zeros((6, 6))
        C[0:3, 3:6] = -Smtrx(dt_dnu1)
        C[3:6, 0:3] = -Smtrx(dt_dnu1)
        C[3:6, 3:6] = -Smtrx(dt_dnu2)
    else:
        C = np.zeros((3, 3))
        C[0, 2] = -M[1, 1] * nu[1] - M[1, 2] * nu[2]
        C[1, 2] = M[0, 0] * nu[0]
        C[2, 0] = -C[0, 2]
        C[2, 1] = -C[1, 2]

    return C


def Hoerner(B, T):
    """
    2D Hoerner cross-flow form coefficient as a function of beam B and draft T.
    """
    DATA1 = np.array([
        0.0109, 0.1766, 0.3530, 0.4519, 0.4728, 0.4929, 0.4933, 0.5585,
        0.6464, 0.8336, 0.9880, 1.3081, 1.6392, 1.8600, 2.3129, 2.6000,
        3.0088, 3.4508, 3.7379, 4.0031
    ])
    DATA2 = np.array([
        1.9661, 1.9657, 1.8976, 1.7872, 1.5837, 1.2786, 1.2108, 1.0836,
        0.9986, 0.8796, 0.8284, 0.7599, 0.6914, 0.6571, 0.6307, 0.5962,
        0.5868, 0.5859, 0.5599, 0.5593
    ])
    return np.interp(B / (2 * T), DATA1, DATA2)


def crossFlowDrag(L, B, T, nu_r):
    """
    Cross-flow drag integrals using strip theory.
    Returns 6x1 generalized force vector tau_crossflow.
    """
    rho = 1026
    n = 20
    dx = L / 20
    Cd_2D = Hoerner(B, T)

    Yh = 0
    Nh = 0
    xL = -L / 2

    for i in range(0, n + 1):
        v_r = nu_r[1]
        r = nu_r[5]
        Ucf = abs(v_r + xL * r) * (v_r + xL * r)
        Yh = Yh - 0.5 * rho * T * Cd_2D * Ucf * dx
        Nh = Nh - 0.5 * rho * T * Cd_2D * xL * Ucf * dx
        xL += dx

    return np.array([0, Yh, 0, 0, 0, Nh], float)


# ---- Coordinate conversion utilities ----

EARTH_RADIUS = 6378137.0  # WGS84 equatorial radius (m)


def latlon_to_ned(lat, lon, lat0, lon0):
    """
    Convert lat/lon (degrees) to local NED (North, East) in meters
    relative to a reference point (lat0, lon0).
    """
    dLat = math.radians(lat - lat0)
    dLon = math.radians(lon - lon0)
    lat0_rad = math.radians(lat0)

    N = EARTH_RADIUS * dLat
    E = EARTH_RADIUS * math.cos(lat0_rad) * dLon
    return N, E


def ned_to_latlon(N, E, lat0, lon0):
    """
    Convert local NED (North, East) in meters back to lat/lon (degrees)
    relative to a reference point (lat0, lon0).
    """
    lat0_rad = math.radians(lat0)
    lat = lat0 + math.degrees(N / EARTH_RADIUS)
    lon = lon0 + math.degrees(E / (EARTH_RADIUS * math.cos(lat0_rad)))
    return lat, lon
