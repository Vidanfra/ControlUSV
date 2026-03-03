#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
High-level autopilot classes combining guidance and control.

Classes:
- HeadingAutopilot: PID heading controller with reference model
- PathFollower: ALOS waypoint path following manager
- GNCController: Unified controller (PathFollower + HeadingAutopilot + allocation)

These classes are used by both the real-time GNC process and the simulator.
"""

import math
import numpy as np
from loguru import logger

from src.gnc.gnc_utils import ssa, wrapTo2Pi
from src.gnc.guidance import ALOSpathFollowing
from src.gnc.control import PIDpolePlacement, controlAllocation


class HeadingAutopilot:
    """
    PID heading controller with 3rd-order reference model.

    Wraps the PIDpolePlacement function with persistent state (integral error,
    reference model states). Can be used standalone for heading-hold mode
    or driven by the PathFollower for waypoint following.
    """

    def __init__(self, m_yaw, wn=4.0, zeta=0.5, wn_d=1.0, zeta_d=1.0,
                 r_max_deg=1000.0):
        """
        Args:
            m_yaw: Yaw moment of inertia including added mass [kg·m²]
            wn: PID natural frequency [rad/s]
            zeta: PID damping ratio [-]
            wn_d: Reference model natural frequency [rad/s]
            zeta_d: Reference model damping ratio [-]
            r_max_deg: Maximum yaw rate [deg/s]
        """
        self.m_yaw = m_yaw
        self.wn = wn
        self.zeta = zeta
        self.wn_d = wn_d
        self.zeta_d = zeta_d
        self.r_max = math.radians(r_max_deg)

        # Nomoto model parameters
        T = 1.0
        K = T / m_yaw
        self.d = 1.0 / K
        self.k = 0.0

        # Persistent states
        self.e_int = 0.0
        self.psi_d = 0.0  # desired heading (reference model state)
        self.r_d = 0.0    # desired yaw rate
        self.a_d = 0.0    # desired yaw acceleration

        # Stored gains (for telemetry/debugging)
        self.Kp = 0.0
        self.Kd = 0.0
        self.Ki = 0.0

    def reset(self, psi_init=0.0):
        """Reset the controller state for a new mission."""
        self.e_int = 0.0
        self.psi_d = psi_init
        self.r_d = 0.0
        self.a_d = 0.0

    def compute(self, psi, r, psi_ref, sampleTime):
        """
        Compute yaw torque command.

        Args:
            psi: Current heading [rad]
            r: Current yaw rate [rad/s]
            psi_ref: Desired heading reference [rad]
            sampleTime: Time step [s]

        Returns:
            tau_N: Yaw torque command [N·m]
        """
        # Prevent reference model unwinding (360° spins)
        psi_ref = self.psi_d + ssa(psi_ref - self.psi_d)

        # Tracking errors (normalized to ±180°)
        e_psi = ssa(psi - self.psi_d)
        e_r = r - self.r_d

        tau_N, self.e_int, self.psi_d, self.r_d, self.a_d, self.Kp, self.Kd, self.Ki = \
            PIDpolePlacement(
                self.e_int, e_psi, e_r,
                self.psi_d, self.r_d, self.a_d,
                self.m_yaw, self.d, self.k,
                self.wn_d, self.zeta_d,
                self.wn, self.zeta,
                psi_ref, self.r_max, sampleTime
            )

        return tau_N

    def update_tuning(self, wn=None, zeta=None, wn_d=None, zeta_d=None):
        """Update tuning parameters (can be changed mid-mission)."""
        if wn is not None:
            self.wn = wn
        if zeta is not None:
            self.zeta = zeta
        if wn_d is not None:
            self.wn_d = wn_d
        if zeta_d is not None:
            self.zeta_d = zeta_d


class PathFollower:
    """
    ALOS waypoint path following manager.

    Manages waypoint list, current segment index, and ALOS algorithm state.
    Returns desired heading for the HeadingAutopilot to track.
    """

    def __init__(self, delta=5.0, gamma=0.0):
        """
        Args:
            delta: Look-ahead distance [m]
            gamma: ALOS adaptive sideslip gain (0 = no adaptation)
        """
        self.delta = delta
        self.gamma = gamma

        # Waypoints: list of dicts with keys 'N', 'E', 'radius', 'speed'
        self.waypoints = []
        self.wp_index = 0
        self.beta_c = 0.0
        self.prev_progress = 0.0
        self._mission_complete = False

    def set_waypoints(self, waypoints_ned):
        """
        Set waypoints in local NED coordinates.

        Args:
            waypoints_ned: list of dicts, each with:
                'N': North position [m]
                'E': East position [m]
                'radius': Acceptance radius [m]
                'speed': Desired speed [m/s]
        """
        self.waypoints = waypoints_ned
        self.wp_index = 0
        self.beta_c = 0.0
        self.prev_progress = 0.0
        self._mission_complete = False
        logger.info(f"PathFollower: loaded {len(waypoints_ned)} waypoints")

    def update(self, eta, sampleTime):
        """
        Update path following for one time step.

        Args:
            eta: numpy array [N, E, D, phi, theta, psi] — current state
            sampleTime: Time step [s]

        Returns:
            psi_d: Desired heading [rad]
            ye: Cross-track error [m]
            current_speed: Desired speed for current segment [m/s]
            wp_index: Current waypoint index
        """
        if self._mission_complete or len(self.waypoints) < 2:
            return eta[5], 0.0, 0.0, self.wp_index  # hold current heading

        # Current and next waypoints
        wp_current = self.waypoints[self.wp_index]
        wp_next = self.waypoints[min(self.wp_index + 1, len(self.waypoints) - 1)]

        wk = np.array([wp_current['N'], wp_current['E']])
        wk_1 = np.array([wp_next['N'], wp_next['E']])

        # Check waypoint switching
        dist_to_next = math.sqrt(
            (eta[0] - wp_next['N']) ** 2 + (eta[1] - wp_next['E']) ** 2
        )

        if dist_to_next < wp_next['radius'] and self.wp_index < len(self.waypoints) - 2:
            self.wp_index += 1
            self.prev_progress = 0.0
            logger.info(
                f"PathFollower: switched to WP {self.wp_index + 1}/"
                f"{len(self.waypoints)}"
            )
            # Recurse with updated index
            return self.update(eta, sampleTime)

        # Check mission completion (reached last waypoint)
        if self.wp_index >= len(self.waypoints) - 2 and dist_to_next < wp_next['radius']:
            self._mission_complete = True
            logger.info("PathFollower: mission complete!")

        # ALOS guidance
        psi_d, self.beta_c, ye, self.prev_progress, N_t, E_t = \
            ALOSpathFollowing(
                eta, wk, wk_1,
                self.delta, self.gamma, self.beta_c,
                sampleTime, self.prev_progress
            )

        current_speed = wp_current.get('speed', 1.0)

        return psi_d, ye, current_speed, self.wp_index

    def is_mission_complete(self):
        """Check if all waypoints have been reached."""
        return self._mission_complete

    def reset(self):
        """Reset path following state for mission restart."""
        self.wp_index = 0
        self.beta_c = 0.0
        self.prev_progress = 0.0
        self._mission_complete = False


class GNCController:
    """
    Unified GNC controller combining PathFollower + HeadingAutopilot + control allocation.

    This is the main class used by both:
    - Real-time GNCProcess (with sensor-derived eta/nu)
    - Simulator (with vehicle-model-derived eta/nu)
    """

    def __init__(self, m_yaw, B_inv, n_max, n_min,
                 wn=4.0, zeta=0.5, wn_d=1.0, zeta_d=1.0,
                 delta=5.0, gamma=0.0, tau_X=150.0):
        """
        Args:
            m_yaw: Yaw moment of inertia [kg·m²]
            B_inv: Inverse thrust configuration matrix (2x2)
            n_max: Maximum propeller speed [rad/s]
            n_min: Minimum propeller speed [rad/s] (negative)
            wn, zeta: PID controller tuning
            wn_d, zeta_d: Reference model tuning
            delta: ALOS look-ahead distance [m]
            gamma: ALOS adaptive gain
            tau_X: Default surge force [N]
        """
        self.autopilot = HeadingAutopilot(m_yaw, wn, zeta, wn_d, zeta_d)
        self.path_follower = PathFollower(delta, gamma)
        self.B_inv = B_inv
        self.n_max = n_max
        self.n_min = n_min
        self.tau_X = tau_X

        # Debug output
        self.last_psi_d = 0.0
        self.last_ye = 0.0
        self.last_wp_index = 0

    def set_waypoints(self, waypoints_ned):
        """Load waypoints. See PathFollower.set_waypoints()."""
        self.path_follower.set_waypoints(waypoints_ned)

    def set_surge_force(self, tau_X):
        """Set surge force [N]."""
        self.tau_X = tau_X

    def step(self, eta, nu, sampleTime):
        """
        Compute one GNC control step.

        Args:
            eta: [N, E, D, phi, theta, psi] — position/attitude
            nu: [u, v, w, p, q, r] — body velocities
            sampleTime: Time step [s]

        Returns:
            n1, n2: Propeller speed commands [rad/s]
            debug: dict with psi_d, heading_error, cross_track_error, wp_index
        """
        # 1. Guidance — get desired heading from path follower
        psi_d, ye, speed, wp_idx = self.path_follower.update(eta, sampleTime)

        # 2. Control — PID heading control
        psi = eta[5]
        r = nu[5]
        tau_N = self.autopilot.compute(psi, r, psi_d, sampleTime)

        # 3. Allocation — convert to propeller speeds
        n1, n2 = controlAllocation(self.tau_X, tau_N, self.B_inv)

        # Saturate propeller speeds
        from src.gnc.gnc_utils import sat
        n1 = sat(n1, self.n_min, self.n_max)
        n2 = sat(n2, self.n_min, self.n_max)

        # Store debug info
        self.last_psi_d = psi_d
        self.last_ye = ye
        self.last_wp_index = wp_idx

        heading_error = ssa(psi - psi_d)

        debug = {
            'psi_d': psi_d,
            'heading_error': heading_error,
            'cross_track_error': ye,
            'wp_index': wp_idx,
            'n1': n1,
            'n2': n2,
            'tau_N': tau_N,
            'tau_X': self.tau_X,
            'speed': speed,
        }

        return n1, n2, debug

    def reset(self, psi_init=0.0):
        """Reset all controller state for a new mission."""
        self.autopilot.reset(psi_init)
        self.path_follower.reset()

    def is_mission_complete(self):
        """Check if the path following mission is complete."""
        return self.path_follower.is_mission_complete()

    def update_tuning(self, **kwargs):
        """
        Update tuning parameters.

        Supported kwargs: wn, zeta, wn_d, zeta_d, delta, gamma, tau_X
        """
        if 'wn' in kwargs or 'zeta' in kwargs or 'wn_d' in kwargs or 'zeta_d' in kwargs:
            self.autopilot.update_tuning(
                wn=kwargs.get('wn'), zeta=kwargs.get('zeta'),
                wn_d=kwargs.get('wn_d'), zeta_d=kwargs.get('zeta_d')
            )
        if 'delta' in kwargs:
            self.path_follower.delta = kwargs['delta']
        if 'gamma' in kwargs:
            self.path_follower.gamma = kwargs['gamma']
        if 'tau_X' in kwargs:
            self.tau_X = kwargs['tau_X']
