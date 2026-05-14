#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salpa 1 USV Vehicle Model for simulation.

6-DOF dynamics model of the Salpa 1 electric catamaran.
Used ONLY by the simulator — the real vehicle uses actual hardware.

This is a production-adapted version of simulator/salpa1.py, with imports
pointing to src.gnc instead of the external python_vehicle_simulator package.

Vehicle specifications:
    - Length: 2.4 m, Beam: 1.7 m, Draft: 0.09 m (at 165 kg)
    - Mass: 165 kg hull + payload
    - Twin pontoon catamaran with 2 electric motors
    - Max speed: 4 knots (~2.06 m/s)
    - Max thrust per motor: 11.5 kgf

Reference: T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and
Motion Control. 2nd Edition, Wiley.
"""

import numpy as np
import math
from loguru import logger

from src.gnc.gnc_utils import Smtrx, Hmtrx, Rzyx, m2c, crossFlowDrag, sat, ssa
from src.gnc.control import PIDpolePlacement, controlAllocation
from src.gnc.salpa1_params import (
    LENGTH, BEAM, DRAFT, PONTOON_BEAM, PONTOON_Y, CW_PONT, CB_PONT,
    HULL_MASS, CG_HULL, CG_PAYLOAD, R44_COEFF, R55_COEFF, R66_COEFF,
    K_POS, K_NEG, MAX_THRUST_KGF, MIN_THRUST_KGF, T_PROP,
    T_SWAY, T_YAW, WN_AUTOPILOT, ZETA_AUTOPILOT, WN_REF, ZETA_REF, R_MAX_DEG,
    AM_XUDOT, AM_YVDOT, AM_ZWDOT, AM_KPDOT, AM_MQDOT, AM_NRDOT,
    XU_LIN_FRAC, XU_QUAD_FRAC, YAW_QUAD_FAC, TAU_MAX, UMAX, N_MAX, N_MIN, G,
)
from src.gnc.salpa1_params import MAX_SPEED_KN as MAX_SPEED_KNOTS
from src.gnc.salpa1_params import LCF as LCF_SALPA1


class Salpa1Model:
    """
    Salpa 1 USV 6-DOF dynamics model for simulation.

    Provides dynamics(), headingAutopilot() and controlAllocation() methods
    matching the interface expected by the simulation loop.
    """

    def __init__(self, payload_mass=25.0, V_current=0.0, beta_current=0.0,
                 tau_X=150.0, wn=None, zeta=None, wn_d=None, zeta_d=None):
        """
        Args:
            payload_mass: Payload mass [kg]
            V_current: Ocean current speed [m/s]
            beta_current: Ocean current direction [deg]
            tau_X: Surge force (pilot input) [N]
            wn, zeta: PID tuning overrides (default: use module constants)
            wn_d, zeta_d: Reference model tuning overrides
        """
        D2R = math.pi / 180
        self.g = G
        rho = 1025

        self.V_c = V_current
        self.beta_c = beta_current * D2R
        self.tauX = tau_X

        # Dimensions
        self.T_n = T_PROP
        self.L = LENGTH
        self.B = BEAM

        # Mass
        m = HULL_MASS
        self.mp = payload_mass
        self.m_total = m + self.mp

        self.rp = np.array(CG_PAYLOAD, float)
        rg = np.array(CG_HULL, float)
        rg = (m * rg + self.mp * self.rp) / (m + self.mp)

        self.S_rg = Smtrx(rg)
        self.H_rg = Hmtrx(rg)
        self.S_rp = Smtrx(self.rp)

        # Radii of gyration
        R44 = R44_COEFF * self.B
        R55 = R55_COEFF * self.L
        R66 = R66_COEFF * self.L

        # Time constants
        T_sway = T_SWAY
        T_yaw = T_YAW

        # Pontoon
        self.B_pont = PONTOON_BEAM
        y_pont = PONTOON_Y
        Cw_pont = CW_PONT
        Cb_pont = CB_PONT

        # Volume displacement and draft
        nabla = (m + self.mp) / rho
        self.T = (self.m_total / 165.0) * 0.09
        self.drag_scale_factor = self.T / 0.09

        # Inertia
        Ig_CG = m * np.diag(np.array([R44 ** 2, R55 ** 2, R66 ** 2]))
        self.Ig = Ig_CG - m * self.S_rg @ self.S_rg - self.mp * self.S_rp @ self.S_rp

        # Propeller configuration
        self.l1 = -y_pont
        self.l2 = y_pont
        self.k_pos = K_POS
        self.k_neg = K_NEG
        self.n_max = N_MAX
        self.n_min = N_MIN

        # Mass matrices
        MRB_CG = np.zeros((6, 6))
        MRB_CG[0:3, 0:3] = (m + self.mp) * np.identity(3)
        MRB_CG[3:6, 3:6] = self.Ig
        MRB = self.H_rg.T @ MRB_CG @ self.H_rg

        # Added mass
        Xudot = AM_XUDOT * m
        Yvdot = AM_YVDOT * m
        Zwdot = AM_ZWDOT * m
        Kpdot = AM_KPDOT * self.Ig[0, 0]
        Mqdot = AM_MQDOT * self.Ig[1, 1]
        Nrdot = AM_NRDOT * self.Ig[2, 2]
        self.MA = -np.diag([Xudot, Yvdot, Zwdot, Kpdot, Mqdot, Nrdot])

        self.M = MRB + self.MA
        self.Minv = np.linalg.inv(self.M)

        # Hydrostatics
        Aw_pont = Cw_pont * self.L * self.B_pont
        I_T = (
            2 * (1 / 12) * self.L * self.B_pont ** 3
            * (6 * Cw_pont ** 3 / ((1 + Cw_pont) * (1 + 2 * Cw_pont)))
            + 2 * Aw_pont * y_pont ** 2
        )
        I_L = 0.8 * 2 * (1 / 12) * self.B_pont * self.L ** 3
        KB = (1 / 3) * (5 * self.T / 2 - 0.5 * nabla / (self.L * self.B_pont))
        BM_T = I_T / nabla
        BM_L = I_L / nabla
        KM_T = KB + BM_T
        KM_L = KB + BM_L
        KG = self.T - rg[2]
        GM_T = KM_T - KG
        GM_L = KM_L - KG

        G33 = rho * self.g * (2 * Aw_pont)
        G44 = rho * self.g * nabla * GM_T
        G55 = rho * self.g * nabla * GM_L
        G_CF = np.diag([0, 0, G33, G44, G55, 0])

        LCF = LCF_SALPA1
        H = Hmtrx(np.array([LCF, 0.0, 0.0]))
        self.G = H.T @ G_CF @ H

        # Natural frequencies
        w3 = math.sqrt(G33 / self.M[2, 2])
        w4 = math.sqrt(G44 / self.M[3, 3])
        w5 = math.sqrt(G55 / self.M[4, 4])

        # Damping
        Xu = (-XU_LIN_FRAC * TAU_MAX / UMAX) * self.drag_scale_factor
        self.Xu_quad = (-XU_QUAD_FRAC * TAU_MAX / (UMAX ** 2)) * self.drag_scale_factor

        Yv = -self.M[1, 1] / T_sway
        Zw = -2 * 0.3 * w3 * self.M[2, 2]
        Kp = -2 * 0.2 * w4 * self.M[3, 3]
        Mq = -2 * 0.4 * w5 * self.M[4, 4]
        Nr = -self.M[5, 5] / T_yaw

        self.D = -np.diag([Xu, Yv, Zw, Kp, Mq, Nr])

        # Thrust allocation matrix inverse
        B_mat = self.k_pos * np.array([[1, 1], [-self.l1, -self.l2]])
        self.Binv = np.linalg.inv(B_mat)

        # Autopilot state
        self.e_int = 0.0
        self.wn = wn if wn is not None else WN_AUTOPILOT
        self.zeta = zeta if zeta is not None else ZETA_AUTOPILOT
        self.r_max = R_MAX_DEG * math.pi / 180
        self.psi_d = 0.0
        self.r_d = 0.0
        self.a_d = 0.0
        self.wn_d = wn_d if wn_d is not None else WN_REF
        self.zeta_d = zeta_d if zeta_d is not None else ZETA_REF
        self.Izz_total = self.M[5, 5]

        # Reference heading (for standalone heading-hold mode)
        self.ref = 0.0

        logger.debug(
            f"Salpa1Model: m={self.m_total:.0f}kg, T={self.T:.3f}m, "
            f"Izz={self.Izz_total:.1f}kg·m², n_max={self.n_max:.0f}rad/s"
        )

    def dynamics(self, eta, nu, u_actual, u_control, sampleTime):
        """
        Integrate 6-DOF equations of motion (one Euler step).

        Args:
            eta: [N, E, D, phi, theta, psi]
            nu: [u, v, w, p, q, r] body velocities
            u_actual: [n1, n2] actual propeller speeds
            u_control: [n1, n2] commanded propeller speeds
            sampleTime: time step [s]

        Returns:
            nu: updated body velocities
            u_actual: updated actual propeller speeds
        """
        n = np.array([u_actual[0], u_actual[1]])

        # Current velocities
        u_c = self.V_c * math.cos(self.beta_c - eta[5])
        v_c = self.V_c * math.sin(self.beta_c - eta[5])
        nu_c = np.array([u_c, v_c, 0, 0, 0, 0], float)
        Dnu_c = np.array([nu[5] * v_c, -nu[5] * u_c, 0, 0, 0, 0], float)
        nu_r = nu - nu_c

        # Coriolis matrices
        CRB_CG = np.zeros((6, 6))
        CRB_CG[0:3, 0:3] = self.m_total * Smtrx(nu[3:6])
        CRB_CG[3:6, 3:6] = -Smtrx(np.matmul(self.Ig, nu[3:6]))
        CRB = self.H_rg.T @ CRB_CG @ self.H_rg

        CA = m2c(self.MA, nu_r)
        C = CRB + CA

        # Payload force in body frame
        R = Rzyx(eta[3], eta[4], eta[5])
        f_payload = np.matmul(R.T, np.array([0, 0, self.mp * self.g], float))
        m_payload = np.matmul(self.S_rp, f_payload)
        g_0 = np.array([
            f_payload[0], f_payload[1], f_payload[2],
            m_payload[0], m_payload[1], m_payload[2]
        ])

        # Propeller thrust with saturation
        thrust = np.zeros(2)
        for i in range(2):
            n[i] = sat(n[i], self.n_min, self.n_max)
            if n[i] > 0:
                thrust[i] = self.k_pos * n[i] * abs(n[i])
            else:
                thrust[i] = self.k_neg * n[i] * abs(n[i])

        # Control forces
        tau = np.array([
            thrust[0] + thrust[1], 0, 0, 0, 0,
            -self.l1 * thrust[0] - self.l2 * thrust[1]
        ])

        # Damping (linear + quadratic)
        tau_damp = -np.matmul(self.D, nu_r)
        tau_damp[0] += self.Xu_quad * abs(nu_r[0]) * nu_r[0]
        tau_damp[5] -= YAW_QUAD_FAC * self.D[5, 5] * abs(nu_r[5]) * nu_r[5]

        # Cross-flow drag
        tau_crossflow = crossFlowDrag(self.L, self.B_pont, self.T, nu_r)

        # Equations of motion
        sum_tau = (
            tau + tau_damp + tau_crossflow
            - np.matmul(C, nu_r)
            - np.matmul(self.G, eta)
            + g_0
        )

        nu_dot = Dnu_c + np.matmul(self.Minv, sum_tau)
        n_dot = (u_control - n) / self.T_n

        # Forward Euler
        nu = nu + sampleTime * nu_dot
        n = n + sampleTime * n_dot
        u_actual = np.array(n, float)

        return nu, u_actual

    def headingAutopilot(self, eta, nu, sampleTime):
        """
        PID heading autopilot (standalone mode, for heading-hold).

        Args:
            eta, nu: current state
            sampleTime: time step [s]

        Returns:
            u_control: [n1, n2] propeller speed commands
        """
        psi = eta[5]
        r = nu[5]

        psi_ref_raw = self.ref * math.pi / 180
        psi_ref = self.psi_d + ssa(psi_ref_raw - self.psi_d)

        e_psi = ssa(psi - self.psi_d)
        e_r = r - self.r_d

        m_yaw = self.Izz_total
        T = 1
        K = T / m_yaw
        d = 1 / K
        k = 0

        (tau_N, self.e_int, self.psi_d, self.r_d, self.a_d,
         Kp, Kd, Ki) = PIDpolePlacement(
            self.e_int, e_psi, e_r,
            self.psi_d, self.r_d, self.a_d,
            m_yaw, d, k,
            self.wn_d, self.zeta_d,
            self.wn, self.zeta,
            psi_ref, self.r_max, sampleTime
        )

        n1, n2 = controlAllocation(self.tauX, tau_N, self.Binv, n_max=self.n_max, n_min=self.n_min)
        return np.array([n1, n2], float)
