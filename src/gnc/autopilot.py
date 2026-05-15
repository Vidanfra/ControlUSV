#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
High-level autopilot classes combining guidance and control.

Classes:
- HeadingAutopilot: PID heading controller with reference model
- PathFollower: ALOS waypoint path following manager
- VelocityProfiler: Open-loop trapezoidal surge force profile
- GNCController: Unified controller (PathFollower + HeadingAutopilot + VelocityProfiler + allocation)

These classes are used by both the real-time GNC process and the simulator.
"""

import math
import numpy as np
from loguru import logger

from src.gnc.gnc_utils import ssa, wrapTo2Pi
from src.gnc.guidance import ALOSpathFollowing
from src.gnc.control import PIDpolePlacement, controlAllocation
from src.gnc.salpa1_params import (
    TAU_MAX as _TAU_MAX, UMAX as _UMAX,
    XU_LIN as _XU_LIN, XU_QUAD as _XU_QUAD,
    M_SURGE as _M_SURGE,
    IZZ_TOTAL, N_MAX, N_MIN, WN_AUTOPILOT, ZETA_AUTOPILOT, WN_REF, ZETA_REF,
)


class HeadingAutopilot:
    """
    PID heading controller with 3rd-order reference model.

    Wraps the PIDpolePlacement function with persistent state (integral error,
    reference model states). Can be used standalone for heading-hold mode
    or driven by the PathFollower for waypoint following.
    """

    def __init__(self, m_yaw, wn=1.5, zeta=0.7, wn_d=0.5, zeta_d=1.0,
                 r_max_deg=1000.0, e_x_threshold_deg=10.0):
        """
        Args:
            m_yaw: Yaw moment of inertia including added mass [kg·m²]
            wn: PID natural frequency [rad/s]
            zeta: PID damping ratio [-]
            wn_d: Reference model natural frequency [rad/s]
            zeta_d: Reference model damping ratio [-]
            r_max_deg: Maximum yaw rate [deg/s]
            e_x_threshold_deg: Anti-windup threshold [deg]. Integrator only active when |e_x| < this value.
        """
        self.m_yaw = m_yaw
        self.wn = wn
        self.zeta = zeta
        self.wn_d = wn_d
        self.zeta_d = zeta_d
        self.r_max = math.radians(r_max_deg)
        self.e_x_threshold = math.radians(e_x_threshold_deg)

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
                psi_ref, self.r_max, sampleTime,
                e_x_threshold=self.e_x_threshold
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

    def __init__(self, k_delta=15.0, gamma=0.0, delta_min=5.0):
        """
        Args:
            k_delta:   CTE convergence time constant [s]. Look-ahead Δ = max(delta_min, k_delta * U),
                       giving a constant τ_ye = Δ/U = k_delta at all speeds.
            gamma:     ALOS adaptive sideslip gain (0 = no adaptation)
            delta_min: Minimum look-ahead distance [m] (low-speed floor)
        """
        self.k_delta   = k_delta
        self.delta_min = delta_min
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

    def update(self, eta, sampleTime, u_surge=0.0):
        """
        Update path following for one time step.

        Args:
            eta:      numpy array [N, E, D, phi, theta, psi] — current state
            sampleTime: Time step [s]
            u_surge:  Surge speed [m/s] — used to compute speed-proportional look-ahead

        Returns:
            psi_d: Desired heading [rad]
            ye: Cross-track error [m]
            current_speed: Desired speed for current segment [m/s]
            wp_index: Current waypoint index
        """
        if self._mission_complete or len(self.waypoints) < 2:
            return eta[5], 0.0, 0.0, self.wp_index  # hold current heading

        # Speed-proportional look-ahead: Δ = max(delta_min, k_delta * |u|)
        delta = max(self.delta_min, self.k_delta * abs(u_surge))

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
            return self.update(eta, sampleTime, u_surge)

        # Check mission completion (reached last waypoint)
        if self.wp_index >= len(self.waypoints) - 2 and dist_to_next < wp_next['radius']:
            self._mission_complete = True
            logger.info("PathFollower: mission complete!")

        # ALOS guidance (delta computed from speed above)
        psi_d, self.beta_c, ye, self.prev_progress, N_t, E_t = \
            ALOSpathFollowing(
                eta, wk, wk_1,
                delta, self.gamma, self.beta_c,
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


class StationKeeper:
    """
    Dual-radius station keeping algorithm.

    Two radii define the behaviour around the station waypoint:
      - reaching_radius (inner): once inside, the USV idles (zero thrust).
      - station_radius (outer): once outside, the USV re-engages and drives
        back to the station waypoint.

    States: APPROACHING → IDLE → APPROACHING (cycle)
    """

    APPROACHING = 'APPROACHING'
    IDLE = 'IDLE'

    def __init__(self, station_ned, reaching_radius=3.0, station_radius=10.0,
                 m_yaw=IZZ_TOTAL, B_inv=None, n_max=N_MAX, n_min=N_MIN,
                 wn=WN_AUTOPILOT, zeta=ZETA_AUTOPILOT, wn_d=WN_REF, zeta_d=ZETA_REF,
                 k_delta=15.0, delta_min=5.0, gamma=0.0, tau_X=150.0,
                 vel_profiler_enabled=True, accel_ms2=0.3):
        """
        Args:
            station_ned: dict with 'N', 'E' keys — station point in NED
            reaching_radius: inner radius [m] — idle when inside
            station_radius: outer radius [m] — re-engage when outside
            vel_profiler_enabled: Enable/disable the trapezoidal velocity profiler
            accel_ms2: Acceleration rate when leaving a waypoint [m/s²]
        """
        self.station_ned = station_ned
        self.reaching_radius = reaching_radius
        self.station_radius = station_radius
        self.state = self.APPROACHING

        # Create a GNCController for approach segments
        self.controller = GNCController(
            m_yaw=m_yaw, B_inv=B_inv, n_max=n_max, n_min=n_min,
            wn=wn, zeta=zeta, wn_d=wn_d, zeta_d=zeta_d,
            k_delta=k_delta, delta_min=delta_min, gamma=gamma, tau_X=tau_X,
            vel_profiler_enabled=vel_profiler_enabled, accel_ms2=accel_ms2,
        )

    def _load_approach(self, eta):
        """Build a 2-WP path from current position to station."""
        current_wp = {'N': float(eta[0]), 'E': float(eta[1]),
                      'radius': self.reaching_radius, 'speed': None}  # full cruise from start
        target_wp = {'N': self.station_ned['N'], 'E': self.station_ned['E'],
                     'radius': self.reaching_radius, 'speed': 0.0}   # decelerate to stop
        self.controller.set_waypoints([current_wp, target_wp])
        self.controller.reset(psi_init=eta[5])
        self.state = self.APPROACHING
        logger.info(f"StationKeeper: APPROACHING (d > {self.station_radius:.1f}m)")

    def _distance_to_station(self, eta):
        dn = eta[0] - self.station_ned['N']
        de = eta[1] - self.station_ned['E']
        return math.sqrt(dn * dn + de * de)

    def step(self, eta, nu, dt):
        """
        Execute one station-keeping step.

        Returns:
            n1, n2: propeller commands (0, 0 when idle)
            debug: dict with control info (or minimal dict when idle)
        """
        dist = self._distance_to_station(eta)

        if self.state == self.APPROACHING:
            # Check if we've reached the inner zone
            if dist < self.reaching_radius:
                self.state = self.IDLE
                logger.info(f"StationKeeper: IDLE (d={dist:.1f}m < {self.reaching_radius:.1f}m)")
                return 0.0, 0.0, {'psi_d': eta[5], 'heading_error': 0.0,
                                   'cross_track_error': 0.0, 'wp_index': 0,
                                   'station_state': self.IDLE, 'station_dist': dist}

            n1, n2, debug = self.controller.step(eta, nu, dt)
            debug['station_state'] = self.APPROACHING
            debug['station_dist'] = dist
            return n1, n2, debug

        else:  # IDLE
            if dist > self.station_radius:
                logger.info(f"StationKeeper: RE-ENGAGE (d={dist:.1f}m > {self.station_radius:.1f}m)")
                self._load_approach(eta)
                n1, n2, debug = self.controller.step(eta, nu, dt)
                debug['station_state'] = self.APPROACHING
                debug['station_dist'] = dist
                return n1, n2, debug

            return 0.0, 0.0, {'psi_d': eta[5], 'heading_error': 0.0,
                               'cross_track_error': 0.0, 'wp_index': 0,
                               'station_state': self.IDLE, 'station_dist': dist}


class VelocityProfiler:
    """
    Open-loop trapezoidal surge force profile for waypoint route following.

    Modulates tau_X (surge force) throughout the route to produce a smooth
    speed profile with controlled acceleration and deceleration at each
    waypoint, improving turning performance and reducing cross-track error.

    Profile between waypoints k → k+1
    ──────────────────────────────────
                tau_cruise
          ┌─────────────────────┐
         /                       \\
        /  accel                  \\ decel
    ───/    ramp                   \\ ramp ───
      WP[k]                         WP[k+1]
    tau[k]                           tau[k+1]

    Speed mapping
    ─────────────
    Each waypoint has a 'speed' field (passing/crossing speed [m/s]).
    tau at a waypoint = tau_cruise × (v_wp / v_cruise)   [user's linear formula]

    If speed ≤ 0 or not set → no constraint, treated as cruise speed.

    Deceleration distance — physics-based numerical shooting
    ─────────────────────────────────────────────────────────
    The ramp distance is the distance over which a linearly decreasing thrust,
    from tau_cruise down to tau_eq(v_wp) = Xu_lin·v_wp + Xu_quad·v_wp², brings
    the vessel from v_cruise to v_wp.

    Solved by integrating the surge ODE numerically (RK4) and bisecting on the
    ramp distance until the vessel speed at the end of the ramp is within 5 cm/s
    of the target speed.  No empirical scaling factor.

    Coast distance (zero-thrust lower bound) is used only to seed the bisection.

    Short segment handling
    ──────────────────────
    If accel + decel zones overlap (segment shorter than accel_d + decel_d),
    both constraints are applied simultaneously and the minimum tau is used,
    naturally limiting speed throughout the short segment.
    """

    def __init__(self,
                 tau_x_cruise: float,
                 Xu_lin: float  = _XU_LIN,
                 Xu_quad: float = _XU_QUAD,
                 m_surge: float = _M_SURGE,
                 accel_ms2: float = 0.3):
        """
        Args:
            tau_x_cruise: Cruise surge force [N]
            Xu_lin:       Linear surge drag coefficient [N·s/m]   (positive)
            Xu_quad:      Quadratic surge drag coefficient [N·s²/m²] (positive)
            m_surge:      Surge virtual mass  m + |Xudot|  [kg]
            accel_ms2:    Target acceleration when leaving a waypoint [m/s²].
                          Used for the kinematic ramp-up: d_accel = (v_cruise²−v_wp²)/(2·a).
        """
        self.Xu_lin  = Xu_lin
        self.Xu_quad = Xu_quad
        self.m_surge = m_surge
        self.accel_ms2 = max(accel_ms2, 0.01)   # guard against division by zero

        self._wps        = []   # waypoint dicts passed by GNCController
        self._wp_tau     = []   # tau_X target at each waypoint [N]
        self._ramp_dist  = []   # deceleration ramp distance (physics-based, per WP) [m]
        self._accel_dist = []   # acceleration ramp distance (kinematic, per WP) [m]

        # Set cruise after drag params are initialised (v_cruise depends on them)
        self.tau_x_cruise = 0.0
        self.v_cruise     = 0.0
        self.update_cruise(tau_x_cruise)

    # ── Physics helpers ────────────────────────────────────────────────────

    def _v_eq(self, tau_x: float) -> float:
        """Equilibrium surge speed [m/s] at constant tau_x."""
        if tau_x <= 0.0:
            return 0.0
        disc = self.Xu_lin ** 2 + 4.0 * self.Xu_quad * tau_x
        return (-self.Xu_lin + math.sqrt(disc)) / (2.0 * self.Xu_quad)

    def _coast_distance(self, v_start: float, v_end: float) -> float:
        """
        Distance [m] to decelerate from v_start to v_end under pure drag.
        Analytical solution of  m·dv/ds = -(Xu_lin + Xu_quad·v).
        """
        if v_end >= v_start or v_start <= 0.0:
            return 0.0
        v_end = max(v_end, 0.01)   # avoid ln(0)
        return (self.m_surge / self.Xu_quad) * math.log(
            (self.Xu_lin + self.Xu_quad * v_start) /
            (self.Xu_lin + self.Xu_quad * v_end)
        )

    def _ramp_distance(self, v_start: float, v_end: float) -> float:
        """
        Find the minimum ramp distance [m] such that a linearly decreasing thrust
        from tau_cruise to tau_eq(v_end) brings the vessel from v_start to within
        5 cm/s of v_end.

        Physics:
            tau(x) = tau_start + (tau_end - tau_start) * x/d_ramp
            ODE:    m·v·dv/dx = tau(x) - Xu_lin·v - Xu_quad·v²

        where tau_end = Xu_lin·v_end + Xu_quad·v_end² (equilibrium at v_end).

        Solved by RK4 integration + bisection on d_ramp.
        The pure-coast distance is used as the initial lower bound so bisection
        always starts inside a valid bracket.
        """
        if v_end >= v_start or v_start <= 0.0:
            return 0.0

        tau_start = self.tau_x_cruise  # = drag(v_start) at cruise equilibrium
        tau_end   = self.Xu_lin * v_end + self.Xu_quad * v_end ** 2
        v_tol     = 0.05   # accept vessel within 5 cm/s of target at ramp end [m/s]
        v_target  = v_end + v_tol

        # ── Bounds: coast_dist (zero thrust → fastest decel) as lower bound ────
        d_lo = max(self._coast_distance(v_start, v_end), 0.1)
        d_hi = max(d_lo * 40.0, 1.0)

        def sim(d: float) -> float:
            """RK4 over d_ramp; return vessel speed at the end."""
            n  = 300
            dx = d / n
            v  = v_start
            for i in range(n):
                xi = i / n
                xm = (i + 0.5) / n
                xe = (i + 1.0) / n
                ti = tau_start + (tau_end - tau_start) * xi
                tm = tau_start + (tau_end - tau_start) * xm
                te = tau_start + (tau_end - tau_start) * xe

                def f(vi: float, tau_i: float) -> float:
                    vi = max(vi, 1e-4)
                    return (tau_i - self.Xu_lin * vi - self.Xu_quad * vi * vi) / (self.m_surge * vi)

                k1 = f(v, ti)
                k2 = f(max(v + 0.5 * dx * k1, 1e-4), tm)
                k3 = f(max(v + 0.5 * dx * k2, 1e-4), tm)
                k4 = f(max(v + dx * k3, 1e-4), te)
                v  = max(v + dx * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0, 1e-4)
                if v <= v_target:
                    return v   # early exit: decelerated enough
            return v

        # ── Expand d_hi until sim(d_hi) ≤ v_target ────────────────────────────
        for _ in range(8):
            if sim(d_hi) > v_target:
                d_hi *= 4.0
            else:
                break
        else:
            logger.warning(
                f"[VelocityProfiler] _ramp_distance: could not converge "
                f"v_start={v_start:.3f} v_end={v_end:.3f} — using d={d_hi:.1f} m"
            )
            return d_hi

        # ── 25 bisection iterations ≈ sub-mm accuracy ─────────────────────────
        for _ in range(25):
            d_mid = 0.5 * (d_lo + d_hi)
            if sim(d_mid) > v_target:
                d_lo = d_mid   # need more distance
            else:
                d_hi = d_mid   # already decelerates enough

        return d_hi

    # ── Profile management ─────────────────────────────────────────────────

    def update_cruise(self, tau_x_cruise: float) -> None:
        """Update cruise surge force and recompute the velocity profile."""
        self.tau_x_cruise = max(tau_x_cruise, 0.0)
        self.v_cruise     = self._v_eq(self.tau_x_cruise)
        if self._wps:
            self._precompute()

    def set_waypoints(self, waypoints: list) -> None:
        """
        Load waypoints and precompute the surge force profile.

        Args:
            waypoints: list of dicts with keys 'N', 'E', 'radius', 'speed'
                       ('speed' ≤ 0 or absent → treated as cruise speed)
        """
        self._wps = waypoints
        self._precompute()

    def update_accel(self, accel_ms2: float) -> None:
        """Update the acceleration rate and recompute the velocity profile."""
        self.accel_ms2 = max(accel_ms2, 0.01)
        if self._wps:
            self._precompute()

    def _precompute(self) -> None:
        """Recompute tau_X and ramp distances for all waypoints."""
        self._wp_tau    = []
        self._ramp_dist = []
        self._accel_dist = []

        for wp in self._wps:
            # speed field is in knots; None/missing → cruise, ≤ 0 → explicit stop
            v_wp_kn = wp.get('speed')
            if v_wp_kn is None:
                v_wp = self.v_cruise           # no speed constraint → full cruise
            elif v_wp_kn <= 0.0:
                v_wp = 0.0                     # explicit stop at this waypoint
            else:
                v_wp = min(v_wp_kn * 0.5144, self.v_cruise)   # kn → m/s, clamp to cruise

            # tau at WP = equilibrium thrust that maintains v_wp in steady-state
            tau_wp = self.Xu_lin * v_wp + self.Xu_quad * v_wp ** 2

            # Deceleration ramp: physics-based numerical shooting (approaching the WP)
            d_decel = self._ramp_distance(self.v_cruise, v_wp)

            # Acceleration ramp: kinematic formula (leaving the WP)
            # d = (v_cruise² - v_wp²) / (2 * a)  — constant-acceleration model
            #
            # NOTE: this is the ramp distance measured PAST the acceptance circle
            # (see get_tau_x for how dist_past_wp = max(0, dist_from_prev - radius)
            # shifts the ramp origin to the circle exit, preventing a cruise spike
            # at the WP switch instant).
            if v_wp < self.v_cruise:
                d_accel = (self.v_cruise ** 2 - v_wp ** 2) / (2.0 * self.accel_ms2)
            else:
                d_accel = 0.0

            self._wp_tau.append(tau_wp)
            self._ramp_dist.append(d_decel)
            self._accel_dist.append(d_accel)

        logger.debug(
            f"[VelocityProfiler] v_cruise={self.v_cruise:.2f} m/s  "
            f"tau_cruise={self.tau_x_cruise:.1f} N  a_accel={self.accel_ms2:.3f} m/s²  "
            f"WPs decel/accel dists: "
            f"{[(round(self._ramp_dist[i],1), round(self._accel_dist[i],1)) for i in range(len(self._wps))]}"
        )

    # ── Main query ─────────────────────────────────────────────────────────

    def get_tau_x(self, wp_idx: int,
                  dist_to_next: float,
                  dist_from_prev: float) -> float:
        """
        Compute desired surge force for the current position.

        Both the deceleration constraint (approaching next WP) and the
        acceleration constraint (leaving current WP) are evaluated.
        The minimum of the two is used so that short segments are handled
        correctly (vessel stays slow throughout).

        Args:
            wp_idx:         Current from-waypoint index (PathFollower.wp_index)
            dist_to_next:   Distance to next waypoint [m]
            dist_from_prev: Distance from current (from) waypoint [m]

        Returns:
            tau_x: Desired surge force [N]
        """
        n = len(self._wps)
        if n < 2 or wp_idx >= n - 1:
            return self.tau_x_cruise

        tau_x   = self.tau_x_cruise
        next_idx = wp_idx + 1

        # ── Deceleration zone: approaching next WP ────────────────────────
        d_decel = self._ramp_dist[next_idx]
        if d_decel > 0.0 and dist_to_next <= d_decel:
            # alpha: 1.0 at start of ramp, 0.0 right at the WP
            alpha   = dist_to_next / d_decel
            tau_dec = alpha * self.tau_x_cruise + (1.0 - alpha) * self._wp_tau[next_idx]
            tau_x   = min(tau_x, tau_dec)

        # ── Acceleration zone: leaving current WP ─────────────────────────
        # The ramp starts once the vessel exits the acceptance circle.
        # dist_past_wp = distance traveled PAST the acceptance boundary.
        #   - Inside the circle (dist_from_prev ≤ radius):  dist_past_wp = 0
        #     → alpha = 0 → tau_acc = tau_wp  (no spike at WP switch)
        #   - Outside the circle:  dist_past_wp > 0, tau ramps toward cruise
        wp_radius    = float(self._wps[wp_idx].get('radius', 5.0))
        dist_past_wp = max(0.0, dist_from_prev - wp_radius)
        d_accel = self._accel_dist[wp_idx]
        if d_accel > 0.0 and dist_past_wp <= d_accel:
            # alpha: 0.0 at circle exit, 1.0 at end of ramp
            alpha   = dist_past_wp / d_accel
            tau_acc = (1.0 - alpha) * self._wp_tau[wp_idx] + alpha * self.tau_x_cruise
            tau_x   = min(tau_x, tau_acc)

        return max(tau_x, 0.0)


class GNCController:
    """
    Unified GNC controller combining PathFollower + HeadingAutopilot + control allocation.

    This is the main class used by both:
    - Real-time GNCProcess (with sensor-derived eta/nu)
    - Simulator (with vehicle-model-derived eta/nu)
    """

    def __init__(self, m_yaw, B_inv, n_max, n_min,
                 wn=1.5, zeta=0.7, wn_d=0.5, zeta_d=1.0,
                 k_delta=15.0, delta_min=5.0, gamma=0.0,
                 tau_X=150.0, e_x_threshold_deg=10.0,
                 vel_profiler_enabled=True, accel_ms2=0.3):
        """
        Args:
            m_yaw: Yaw moment of inertia [kg·m²]
            B_inv: Inverse thrust configuration matrix (2x2)
            n_max: Maximum propeller speed [rad/s]
            n_min: Minimum propeller speed [rad/s] (negative)
            wn, zeta: PID controller tuning
            wn_d, zeta_d: Reference model tuning
            k_delta:   CTE convergence time constant [s]; look-ahead = max(delta_min, k_delta * U)
            delta_min: Minimum look-ahead distance [m] (low-speed floor)
            gamma: ALOS adaptive gain
            tau_X: Cruise surge force [N]
            e_x_threshold_deg: Anti-windup threshold [deg]
            vel_profiler_enabled: Enable/disable the trapezoidal velocity profiler
            accel_ms2: Acceleration rate when leaving a waypoint [m/s²]
        """
        self.autopilot    = HeadingAutopilot(m_yaw, wn, zeta, wn_d, zeta_d,
                                             e_x_threshold_deg=e_x_threshold_deg)
        self.path_follower = PathFollower(k_delta, gamma, delta_min)
        self.vel_profiler  = VelocityProfiler(tau_X, accel_ms2=accel_ms2)
        self.vel_profiler_enabled = vel_profiler_enabled
        self.B_inv = B_inv
        self.n_max = n_max
        self.n_min = n_min
        self.tau_X = tau_X   # cruise force (reference; profiler modulates this)

        # Debug output
        self.last_psi_d    = 0.0
        self.last_ye       = 0.0
        self.last_wp_index = 0

    def set_waypoints(self, waypoints_ned):
        """Load waypoints into path follower and velocity profiler."""
        self.path_follower.set_waypoints(waypoints_ned)
        self.vel_profiler.set_waypoints(waypoints_ned)

    def set_surge_force(self, tau_X):
        """Update cruise surge force and recalculate velocity profile."""
        self.tau_X = tau_X
        self.vel_profiler.update_cruise(tau_X)

    def step(self, eta, nu, sampleTime):
        """
        Compute one GNC control step.

        Args:
            eta: [N, E, D, phi, theta, psi] — position/attitude
            nu: [u, v, w, p, q, r] — body velocities
            sampleTime: Time step [s]

        Returns:
            n1, n2: Propeller speed commands [rad/s]
            debug: dict with psi_d, heading_error, cross_track_error, wp_index,
                   tau_X_eff (effective surge force from velocity profile)
        """
        # 1. Guidance — desired heading from path follower (speed-proportional look-ahead)
        u_surge = float(nu[0])
        psi_d, ye, speed, wp_idx = self.path_follower.update(eta, sampleTime, u_surge)

        # 2. Velocity profile — compute effective surge force for this timestep.
        #    Distances to/from waypoints drive the trapezoidal ramp.
        wps = self.path_follower.waypoints
        tau_x_eff = self.tau_X   # fallback: constant cruise
        dist_to_next = 0.0
        if self.vel_profiler_enabled and len(wps) >= 2 and wp_idx < len(wps) - 1:
            wp_from = wps[wp_idx]
            wp_to   = wps[min(wp_idx + 1, len(wps) - 1)]
            dist_to_next  = math.hypot(eta[0] - wp_to['N'],   eta[1] - wp_to['E'])
            dist_from_prev = math.hypot(eta[0] - wp_from['N'], eta[1] - wp_from['E'])
            tau_x_eff = self.vel_profiler.get_tau_x(wp_idx, dist_to_next, dist_from_prev)
        elif not self.vel_profiler_enabled and len(wps) >= 2 and wp_idx < len(wps) - 1:
            wp_to = wps[min(wp_idx + 1, len(wps) - 1)]
            dist_to_next = math.hypot(eta[0] - wp_to['N'], eta[1] - wp_to['E'])

        # 3. Heading PID control
        psi = eta[5]
        r   = nu[5]
        tau_N = self.autopilot.compute(psi, r, psi_d, sampleTime)

        # 4. Allocation — effective surge force + yaw torque → propeller speeds
        n1, n2 = controlAllocation(tau_x_eff, tau_N, self.B_inv,
                                   n_max=self.n_max, n_min=self.n_min)

        # Store debug info
        self.last_psi_d    = psi_d
        self.last_ye       = ye
        self.last_wp_index = wp_idx

        heading_error = ssa(psi - psi_d)

        debug = {
            'psi_d':            psi_d,
            'heading_error':    heading_error,
            'cross_track_error': ye,
            'wp_index':         wp_idx,
            'dist_to_next':     dist_to_next,
            'n1':               n1,
            'n2':               n2,
            'tau_N':            tau_N,
            'tau_X':            tau_x_eff,   # effective value (after profiler)
            'tau_X_cruise':     self.tau_X,  # user-set cruise value
            'speed':            speed,
            'v_cruise':         self.vel_profiler.v_cruise,
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

        Supported kwargs: wn, zeta, wn_d, zeta_d, k_delta, delta_min, gamma, tau_X
        """
        if 'wn' in kwargs or 'zeta' in kwargs or 'wn_d' in kwargs or 'zeta_d' in kwargs:
            self.autopilot.update_tuning(
                wn=kwargs.get('wn'), zeta=kwargs.get('zeta'),
                wn_d=kwargs.get('wn_d'), zeta_d=kwargs.get('zeta_d')
            )
        if 'k_delta' in kwargs:
            self.path_follower.k_delta = kwargs['k_delta']
        if 'delta_min' in kwargs:
            self.path_follower.delta_min = kwargs['delta_min']
        if 'gamma' in kwargs:
            self.path_follower.gamma = kwargs['gamma']
        if 'tau_X' in kwargs:
            self.tau_X = kwargs['tau_X']
            self.vel_profiler.update_cruise(kwargs['tau_X'])
        if 'vel_profiler_enabled' in kwargs:
            self.vel_profiler_enabled = bool(kwargs['vel_profiler_enabled'])
        if 'accel_ms2' in kwargs:
            self.vel_profiler.update_accel(kwargs['accel_ms2'])
