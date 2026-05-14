#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salpa 1 — centralised parameter loader.

Reads Salpa1_ModelParameters.json (same directory) and exposes all physical
and control constants as module-level names.  Every other module should import
from here rather than defining its own copies.

Primary constants    — read directly from JSON.  Edit values in the JSON only.
Derived constants    — computed from primaries below; never hardcode elsewhere.

HOW THE DRAG MODEL IS CALIBRATED
---------------------------------
The assumption is: at maximum speed UMAX the two motors together produce TAU_MAX
and the total surge drag exactly equals that thrust (steady state).

    F_drag(u) = XU_LIN * u  +  XU_QUAD * u²
    F_drag(UMAX) = TAU_MAX

The drag is split between linear and quadratic fractions (xu_lin_frac / xu_quad_frac)
so that both fractions sum to 1 and together reproduce the correct drag at UMAX.

HOW THE THRUST COEFFICIENT IS DERIVED
--------------------------------------
Propeller thrust law:  T = k * n²  (n in rad/s)
At max speed the motor spins at N_MAX such that T_max = k_pos * N_MAX².
Solving: N_MAX = sqrt(max_thrust_kgf * g / k_pos)

HOW THE SURGE INERTIA (M_SURGE) IS COMPUTED
--------------------------------------------
M_SURGE = (hull_kg + default_payload_kg) * (1 - xudot_frac)
The added-mass fraction xudot_frac is negative, so (1 - xudot_frac) > 1.
"""

import json
import math
import os

_JSON = os.path.join(os.path.dirname(__file__), 'Salpa1_ModelParameters.json')
with open(_JSON) as _f:
    _p = json.load(_f)

# ── Geometry ──────────────────────────────────────────────────────────────────
# Physical hull dimensions measured on the vessel.
LENGTH       = _p['geometry']['length_m']         # [m]  overall hull length; used for R55, R66 and waterplane area
BEAM         = _p['geometry']['beam_m']           # [m]  max beam (pontoon tip to tip); used for R44 and buoyancy area
DRAFT        = _p['geometry']['draft_m']          # [m]  design waterline draft at nominal load; scales with m_total in sim
LCF          = _p['geometry']['lcf_m']            # [m]  longitudinal centre of flotation from body-frame origin (≈ 0)
PONTOON_BEAM = _p['geometry']['pontoon_beam_m']   # [m]  width of one pontoon tube; Aw_pont = CW_PONT * PONTOON_BEAM * LENGTH
PONTOON_Y    = _p['geometry']['pontoon_y_m']      # [m]  lateral distance from centreline to pontoon centre = motor lever arm
CW_PONT      = _p['geometry']['cw_pont']          # [-]  waterplane area coefficient of one pontoon (rect ≈ 1, round ≈ 0.75)
CB_PONT      = _p['geometry']['cb_pont']          # [-]  block coefficient of one pontoon; Vol_pont = CB * B * L * T

# ── Mass & inertia ────────────────────────────────────────────────────────────
# Measured on the vessel; CG vectors in body frame [x_fwd, y_stbd, z_down].
HULL_MASS       = _p['mass']['hull_kg']              # [kg]    dry hull mass, weighed on a scale
DEFAULT_PAYLOAD = _p['mass']['default_payload_kg']   # [kg]    default sensors+batteries payload; update after hardware change
CG_HULL         = _p['mass']['cg_hull_m']            # [m×3]  CG of hull in body frame; convert to np.array at use site
CG_PAYLOAD      = _p['mass']['cg_payload_m']         # [m×3]  CG of payload in body frame; estimated
R44_COEFF       = _p['mass']['r44_coeff']            # [-]    k44/beam  (roll gyration ratio);  Ig[0,0] = m * (r44_coeff*beam)²
R55_COEFF       = _p['mass']['r55_coeff']            # [-]    k55/length (pitch gyration ratio); Ig[1,1] = m * (r55_coeff*L)²
R66_COEFF       = _p['mass']['r66_coeff']            # [-]    k66/length (yaw gyration ratio);   Ig[2,2] = m * (r66_coeff*L)²
IZZ_TOTAL       = _p['mass']['izz_total_kgm2']       # [kg·m²] total yaw MOI (hull+payload+Nrdot added mass); used in autopilot

# ── Added-mass fractions ──────────────────────────────────────────────────────
# Each coefficient is a fraction of the corresponding rigid-body inertia term.
# Translational: X_udot = AM_XUDOT * m_total  (surge, typically small: -0.05 to -0.15)
# Rotational:    K_pdot = AM_KPDOT * Ig[0,0]   (roll),  N_rdot = AM_NRDOT * Ig[2,2] (yaw)
# Estimated from strip-theory for a twin-pontoon catamaran hull.
AM_XUDOT = _p['added_mass']['xudot_frac']   # [-]  surge:  Xudot = AM_XUDOT * m_total   ≈ -19 kg
AM_YVDOT = _p['added_mass']['yvdot_frac']   # [-]  sway:   Yvdot = AM_YVDOT * m_total   (large, twin-hull effect)
AM_ZWDOT = _p['added_mass']['zwdot_frac']   # [-]  heave:  Zwdot = AM_ZWDOT * m_total
AM_KPDOT = _p['added_mass']['kpdot_frac']   # [-]  roll:   Kpdot = AM_KPDOT * Ig[0,0]
AM_MQDOT = _p['added_mass']['mqdot_frac']   # [-]  pitch:  Mqdot = AM_MQDOT * Ig[1,1]
AM_NRDOT = _p['added_mass']['nrdot_frac']   # [-]  yaw:    Nrdot = AM_NRDOT * Ig[2,2]   (large, twin-hull effect)

# ── Propulsion ────────────────────────────────────────────────────────────────
# Thrust law: T = k_pos * n²  (forward, n > 0) or  T = -k_neg * n²  (reverse, n < 0)
# k values derived from motor datasheet: k = T_max[N] / N_max[rad/s]²
# where N_max = sqrt(T_max_kgf * g / k).  Measure thrust on a stand to refine.
K_POS          = _p['propulsion']['k_pos']                            # [N/(rad/s)²]  forward thrust coeff; T_fwd = K_POS * n²
K_NEG          = _p['propulsion']['k_neg']                            # [N/(rad/s)²]  reverse thrust coeff; T_rev = K_NEG * n² (~70% of K_POS)
MAX_THRUST_KGF = _p['propulsion']['max_thrust_per_motor_kgf']         # [kgf]  max forward thrust per motor (datasheet); → TAU_MAX, N_MAX
MIN_THRUST_KGF = _p['propulsion']['max_reverse_thrust_per_motor_kgf'] # [kgf]  max reverse thrust per motor; → N_MIN
T_PROP         = _p['propulsion']['t_prop_s']                         # [s]   first-order ESC+motor+prop lag; tau_dot = (cmd - tau) / T_PROP
MAX_SPEED_KN   = _p['propulsion']['max_speed_kn']                     # [kn]  design max speed at full thrust; used to calibrate drag via UMAX

# ── Drag fractions ────────────────────────────────────────────────────────────
# Surge drag is split into linear (viscous) + quadratic (pressure) components.
# Constraint: xu_lin_frac + xu_quad_frac = 1.
# Both are derived so that F_drag(UMAX) = TAU_MAX (see module docstring).
XU_LIN_FRAC  = _p['drag']['xu_lin_frac']   # [-]  fraction of drag that is linear;     XU_LIN  = xu_lin_frac  * TAU_MAX / UMAX
XU_QUAD_FRAC = _p['drag']['xu_quad_frac']  # [-]  fraction of drag that is quadratic;  XU_QUAD = xu_quad_frac * TAU_MAX / UMAX²
YAW_QUAD_FAC = _p['drag']['yaw_quad_fac']  # [-]  multiplier on quadratic yaw drag; empirical — increase if sim rotates too freely

# ── Damping time constants ────────────────────────────────────────────────────
# First-order approximation: drag_force = -(virtual_mass) * velocity / T
# These apply to the off-surge DOFs and matter mainly in the 6-DOF simulator.
T_SWAY = _p['damping']['t_sway_s']  # [s]  sway damping time constant;  reduce for a blunter hull
T_YAW  = _p['damping']['t_yaw_s']   # [s]  yaw linear damping time constant; acts alongside YAW_QUAD_FAC

# ── Control defaults ──────────────────────────────────────────────────────────
# PD pole-placement for the heading autopilot.  The inner loop uses (wn, zeta);
# the reference pre-filter (2nd-order low-pass) uses (wn_ref, zeta_ref).
# Bandwidth of inner loop ≈ wn / (2π).  Must satisfy: wn_ref < wn.
WN_AUTOPILOT    = _p['control_defaults']['wn']             # [rad/s]  autopilot natural frequency; bandwidth ≈ wn/(2π) ≈ 0.24 Hz at 1.5
ZETA_AUTOPILOT  = _p['control_defaults']['zeta']           # [-]      autopilot damping ratio; 0.7 = Butterworth, no overshoot
WN_REF          = _p['control_defaults']['wn_ref']         # [rad/s]  reference model frequency; must be < WN_AUTOPILOT
ZETA_REF        = _p['control_defaults']['zeta_ref']       # [-]      reference model damping; 1.0 = critically damped
R_MAX_DEG       = _p['control_defaults']['r_max_deg_s']    # [deg/s]  max yaw-rate in reference model; 1000 = unlimited
K_DELTA         = _p['control_defaults']['k_delta_s']      # [s]      CTE convergence time constant; Δ = max(DELTA_MIN, K_DELTA * U); τ_ye = K_DELTA
DELTA_MIN       = _p['control_defaults']['delta_min_m']    # [m]      minimum look-ahead distance floor (low-speed protection)
E_X_THRESHOLD   = _p['control_defaults']['e_x_threshold_deg']  # [deg] integrator anti-windup threshold

# ── Derived constants (computed from primaries; never hardcoded) ──────────────
# These are recalculated every time this module is imported.  Do NOT copy their
# numeric values into other files — import the name instead.

G       = 9.81
# [m/s²] Standard gravitational acceleration. Not in JSON because it is a
# universal constant, not a vessel parameter.

TAU_MAX = 2.0 * MAX_THRUST_KGF * G
# [N] Maximum combined surge thrust from both motors.
# Formula: 2 motors × max_thrust_per_motor_kgf × g
# Example: 2 × 11.5 × 9.81 ≈ 225.63 N

UMAX = MAX_SPEED_KN * 0.5144
# [m/s] Maximum surge speed converted from knots.
# Formula: max_speed_kn × 0.5144 m/s/kn
# Example: 4.0 kn × 0.5144 ≈ 2.0576 m/s

XU_LIN = XU_LIN_FRAC * TAU_MAX / UMAX
# [N·s/m] Linear (velocity-proportional) surge drag coefficient.
# Derived so that XU_LIN * UMAX = xu_lin_frac * TAU_MAX (linear fraction of total drag at UMAX).
# Example: 0.2 × 225.63 / 2.0576 ≈ 21.94 N·s/m
# Used in: process.py (tau→speed inversion), vehicle_model.py (dynamics)

XU_QUAD = XU_QUAD_FRAC * TAU_MAX / UMAX ** 2
# [N·s²/m²] Quadratic (velocity²-proportional) surge drag coefficient.
# Derived so that XU_QUAD * UMAX² = xu_quad_frac * TAU_MAX (quadratic fraction of total drag at UMAX).
# Example: 0.8 × 225.63 / 2.0576² ≈ 42.58 N·s²/m²
# Used in: process.py (tau→speed inversion), vehicle_model.py (dynamics)

_M_NOM  = HULL_MASS + DEFAULT_PAYLOAD
# [kg] Nominal total mass (private helper, not exported).
# Example: 165 + 25 = 190 kg

M_SURGE = _M_NOM * (1.0 - AM_XUDOT)
# [kg] Effective surge inertia = rigid mass + surge added mass.
# Formula: m_total × (1 − xudot_frac)  [note: xudot_frac is negative, so factor > 1]
# Example: 190 × (1 − (−0.1)) = 190 × 1.1 = 209 kg
# Used in: VelocityProfiler (surge acceleration).

N_MAX = math.sqrt(MAX_THRUST_KGF * G / K_POS)
# [rad/s] Maximum propeller angular speed (forward).
# From thrust law at saturation: T_max = K_POS * N_MAX²  →  N_MAX = sqrt(T_max[N] / K_POS)
# Example: sqrt(11.5 × 9.81 / 0.00365) ≈ 175.9 rad/s
# Used in: ESC saturation in autopilot, vehicle_model.

N_MIN = -math.sqrt(MIN_THRUST_KGF * G / K_NEG)
# [rad/s] Minimum (maximum reverse) propeller angular speed.
# From reverse thrust law: T_rev = K_NEG * n²  →  N_MIN = -sqrt(T_rev_max[N] / K_NEG)
# Example: -sqrt(8.0 × 9.81 / 0.00255) ≈ -175.4 rad/s
# Used in: ESC saturation in autopilot, vehicle_model.

L1 = -PONTOON_Y
# [m] Port motor moment arm (negative = port side).
# Yaw moment from port motor: tau_yaw_port  =  L1 * T_port

L2 =  PONTOON_Y
# [m] Starboard motor moment arm (positive = starboard side).
# Yaw moment from stbd motor: tau_yaw_stbd  =  L2 * T_stbd
