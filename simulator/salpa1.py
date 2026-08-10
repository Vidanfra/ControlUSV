#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
salpa1.py: 
    Class for the Salpa 1 USV - Electric Catamaran with 2 motors and 2 pontoons.
    Based on the Otter USV model by Thor I. Fossen.
    
    Vehicle specifications:
        - Length: 2.5 m
        - Beam: 1.6 m  
        - Mass: 165 kg (total)
        - Configuration: Twin pontoon catamaran with 2 electric motors

    Constructors:
        salpa1()                                          
            Step inputs for propeller revolutions n1 and n2
            
        salpa1('headingAutopilot', psi_d, V_current, beta_current, tau_X)  
            Heading autopilot with options:
                psi_d: desired yaw angle (deg)
                V_current: current speed (m/s)
                beta_c: current direction (deg)
                tau_X: surge force, pilot input (N)
            
Methods:
    [nu, u_actual] = dynamics(eta, nu, u_actual, u_control, sampleTime) 
        Returns nu[k+1] and u_actual[k+1] using Euler's method.
        
    u = headingAutopilot(eta, nu, sampleTime) 
        PID controller for automatic heading control based on pole placement.

    u = stepInput(t) 
        Generates propeller step inputs.

    [n1, n2] = controlAllocation(tau_X, tau_N)     
        Control allocation algorithm.
    
References: 
    T. I. Fossen (2021). Handbook of Marine Craft Hydrodynamics and Motion 
        Control. 2nd Edition, Wiley. URL: www.fossen.biz/wiley            

Original Author: Thor I. Fossen (Otter USV)
Modified for Salpa 1: USV Salpa 1 Navigation Development Team
Date: December 2025
"""

import numpy as np
import math
from simulation.control import PIDpolePlacement
from simulation.gnc import Smtrx, Hmtrx, Rzyx, m2c, crossFlowDrag, sat, ssa, wrapTo2Pi


# ============================================================================
# SALPA 1 USV CONFIGURATION PARAMETERS
# ============================================================================
# Fill in these values based on your measurements and motor specifications.
# Otter USV values are shown for reference.
#
# INSTRUCTIONS:
#   1. Measure/estimate each parameter for your Salpa 1 USV
#   2. Replace the placeholder values (marked with TODO)
#   3. Run simulation and validate behavior
#   4. Tune autopilot parameters if needed
# ============================================================================

# -----------------------------------------------------------------------------
# MAIN DIMENSIONS
# -----------------------------------------------------------------------------
LENGTH = 2.4             # [m] Overall length of the USV
                                # Otter: 2.0 m
                                
BEAM = 1.7               # [m] Overall beam (width) of the USV
                                # Otter: 1.08 m
DRAFT = 0.09             # [m] Draft (vertical distance submerged of design waterline)
# -----------------------------------------------------------------------------
# MASS PROPERTIES
# -----------------------------------------------------------------------------
HULL_MASS = 165.0        # [kg] Mass of hull structure (without payload)
                                # Otter: 55.0 kg (without batteries)
                                # TODO: Weigh your hull or estimate

PAYLOAD_MASS = 25.0      # [kg] Mass of payload (sensors, extra batteries, etc.)
                                # Otter: 25.0 kg
                                # TODO: Weigh your payload components

# Center of Gravity for hull only (relative to CO at midship, waterline)
# Coordinate system: x = forward, y = starboard, z = down (NED body frame)
# Negative z means ABOVE waterline
CG_HULL = [-0.063, 0.0, -0.065]    # [m] [x, y, z] CG of hull without payload
                                       # Otter: [0.2, 0, -0.2]
                                       # TODO: Estimate or measure

# Location of payload (electronics, batteries, etc.)
CG_PAYLOAD = [0.1, 0.0, -0.1]  # [m] [x, y, z] Location of payload CG
                                        # Otter: [0.05, 0, -0.35]
                                        # TODO: Where are your batteries/electronics?

# -----------------------------------------------------------------------------
# PONTOON GEOMETRY (CRITICAL FOR CATAMARAN)
# -----------------------------------------------------------------------------
PONTOON_BEAM = 0.35      # [m] Width of ONE pontoon at waterline
                                # Otter: 0.25 m
                                # TODO: Measure your pontoon width

PONTOON_Y = 0.673         # [m] Distance from centerline to pontoon center
                                # Otter: 0.395 m
                                # For Salpa1: approximately (BEAM/2 - PONTOON_BEAM/2)
                                # Used for hydrostatics only (waterline centroid)

MOTOR_Y = 0.765           # [m] Distance from centerline to each motor shaft
                                # Measured motor-to-motor separation: 1.53 m
                                # This is the thrust lever arm used in allocation

CW_PONT = 0.75           # [-] Waterline area coefficient (0.7 - 0.95)
                                # Otter: 0.75
                                # = Actual_waterline_area / (L * B_pont)
                                # 0.75 = rounded ends, 0.9+ = rectangular ends
                                # TODO: Estimate based on pontoon shape

CB_PONT = 0.871            # [-] Block coefficient (0.4 - 0.8)
                                # Otter: 0.4
                                # = Submerged_volume / (L * B_pont * Draft)
                                # 0.4 = rounded/V-shaped, 0.7+ = rectangular cross-section
                                # TODO: Estimate based on pontoon cross-section

# -----------------------------------------------------------------------------
# RADII OF GYRATION (mass distribution)
# -----------------------------------------------------------------------------
# These coefficients multiply the dimensions to get radii of gyration
# Typical values for small catamarans - adjust if mass distribution is unusual

R44_COEFF = 0.43         # Roll radius = R44_COEFF * BEAM
                                # Otter: 0.40
                                # Wider catamarans may use 0.42-0.45

R55_COEFF = 0.25         # Pitch radius = R55_COEFF * LENGTH  
                                # Otter: 0.25
                                # Standard value, rarely needs changing

R66_COEFF = 0.25         # Yaw radius = R66_COEFF * LENGTH
                                # Otter: 0.25
                                # Standard value, rarely needs changing

# -----------------------------------------------------------------------------
# SPEED AND DAMPING
# -----------------------------------------------------------------------------
MAX_SPEED_KNOTS = 4.0    # [knots] Maximum forward speed
                                # Otter: 6 knots (~3.09 m/s)
                                # TODO: What is your USV's top speed?

T_SWAY = 1.5             # [s] Time constant in sway (lateral motion decay)
                                # Otter: 1.0 s
                                # Larger = slower sway damping (heavier boat)
                                # TODO: Estimate or tune from experiments

T_YAW = 1.06             # [s] Time constant in yaw (rotation decay)
                                # Otter: 1.0 s
                                # Measured: tau = Izz/d1 = 185/175

# PROPULSION SYSTEM (CRITICAL)
# -----------------------------------------------------------------------------
# Thrust model: T = k * n * |n|  where n = propeller speed [rad/s]
# NOTE: These coefficients are PER MOTOR (not total)

K_POS = 0.00365          # [N/(rad/s)²] Positive (forward) thrust coefficient
                                # Original datasheet derivation: k = T_max / n_max²
                                # with T_max = 11.5 kgf and n_max = 175.9 rad/s.
                                # Bollard test now gives 9.5 kgf per motor, so the
                                # saturation speed drops to n_max = 159.8 rad/s.
                                # Otter: 0.02216/2 = 0.01108 (they divided because
                                #        24.4 kgf was TOTAL thrust for both motors)

K_NEG = 0.00255          # [N/(rad/s)²] Negative (reverse) thrust coefficient
                                # Estimated as ~70% of k_pos (typical for propellers)
                                # TODO: Measure reverse thrust if possible

MAX_THRUST_KGF = 9.5     # [kgf] Maximum thrust PER MOTOR
                                # Measured on the bollard test

MIN_THRUST_KGF = 5.5     # [kgf] Maximum reverse thrust PER MOTOR
                                # Measured on the bollard test

T_PROP = 0.1             # [s] Propeller/motor time constant
                                # Otter: 0.1 s
                                # Electric motors: 0.05 - 0.15 s typical
                                # TODO: Faster motors = smaller value

# -----------------------------------------------------------------------------
# HEADING AUTOPILOT TUNING
# -----------------------------------------------------------------------------
WN_AUTOPILOT = 4       # [rad/s] PID controller natural frequency
                                # Otter: 2.5 rad/s
                                # Lower for heavier/slower boats (1.0 - 2.0)
                                # TODO: Tune based on simulation response

ZETA_AUTOPILOT = 0.5     # [-] PID controller damping ratio
                                # Otter: 1.0 (critically damped)
                                # 1.0 = no overshoot, <1 = faster but overshoots

WN_REF = 1             # [rad/s] Reference model natural frequency
                                # Otter: 0.5 rad/s
                                # Slower = smoother heading transitions
                                # TODO: Tune for desired response speed

ZETA_REF = 1.0           # [-] Reference model damping ratio
                                # Otter: 1.0

R_MAX_DEG = 25          # [deg/s] Maximum yaw rate
                                # Otter: 10 deg/s
                                # Physical maximum is approx. 34 deg/s

# -----------------------------------------------------------------------------
# OTHER PARAMETERS
# -----------------------------------------------------------------------------
LCF_SALPA1 = -0.001              # [m] Longitudinal center of flotation (from midship)
                                # Otter: -0.2 m
                                # Negative = aft of midship
                                # TODO: Estimate based on hull shape


# ============================================================================
# SALPA 1 VEHICLE CLASS
# ============================================================================

class salpa1:
    """
    salpa1()                                            Propeller step inputs
    salpa1('headingAutopilot', psi_d, V_c, beta_c, tau_X)  Heading autopilot
    
    Inputs:
        psi_d: desired heading angle (deg)
        V_c: current speed (m/s)
        beta_c: current direction (deg)
        tau_X: surge force, pilot input (N)        
    """

    def __init__(
        self, 
        controlSystem="stepInput", 
        r = 0, 
        V_current = 0, 
        beta_current = 0,
        tau_X = 120,
        payload_mass = 25.0
    ):
        
        # Constants
        D2R = math.pi / 180     # deg2rad
        self.g = 9.81           # acceleration of gravity (m/s^2)
        rho = 1025              # density of water (kg/m^3)

        if controlSystem == "headingAutopilot":
            self.controlDescription = (
                "Heading autopilot, psi_d = "
                + str(r)
                + " deg"
                )
        else:
            self.controlDescription = "Step inputs for n1 and n2"
            controlSystem = "stepInput"

        self.ref = r
        self.V_c = V_current
        self.beta_c = beta_current * D2R
        self.controlMode = controlSystem
        self.tauX = tau_X  # surge force (N)

        # ====================================================================
        # VEHICLE PARAMETERS (from configuration section above)
        # ====================================================================
        
        # Main dimensions
        self.T_n = T_PROP        # propeller time constant (s)
        self.L = LENGTH          # length (m)
        self.B = BEAM            # beam (m)
        
        self.nu = np.array([0, 0, 0, 0, 0, 0], float)  # velocity vector
        self.u_actual = np.array([0, 0], float)        # propeller revolution states
        self.name = "Salpa 1 USV - Electric Catamaran (2.5m x 1.6m, 165kg)"

        self.controls = [
            "Left propeller shaft speed (rad/s)",
            "Right propeller shaft speed (rad/s)"
        ]
        self.dimU = len(self.controls)

        # Mass properties (from configuration)
        m = HULL_MASS                    # hull mass (kg)
        self.mp = payload_mass           # payload mass (kg)
        self.m_total = m + self.mp
        
        self.rp = np.array(CG_PAYLOAD, float)  # location of payload (m)
        rg = np.array(CG_HULL, float)          # CG for hull only (m)
        rg = (m * rg + self.mp * self.rp) / (m + self.mp)  # CG corrected for payload
        
        self.S_rg = Smtrx(rg)
        self.H_rg = Hmtrx(rg)
        self.S_rp = Smtrx(self.rp)

        # Radii of gyration (from configuration coefficients)
        R44 = R44_COEFF * self.B      # roll
        R55 = R55_COEFF * self.L      # pitch
        R66 = R66_COEFF * self.L      # yaw
        
        # Damping time constants (from configuration)
        T_sway = T_SWAY              # time constant in sway (s)
        T_yaw = T_YAW                # time constant in yaw (s)
        Umax = MAX_SPEED_KNOTS * 0.5144   # max forward speed (m/s)

        # Pontoon geometry (from configuration)
        self.B_pont = PONTOON_BEAM   # beam of one pontoon (m)
        y_pont = PONTOON_Y           # distance from centerline to waterline centroid (m)
        Cw_pont = CW_PONT            # waterline area coefficient (-)
        Cb_pont = CB_PONT            # block coefficient (-)

        # Inertia dyadic, volume displacement and draft
        nabla = (m + self.mp) / rho  # volume
        
        # Draft Calculation:
        # Based on user data, Salpa 1 has a linear relationship between Mass and Draft.
        # Design point: 165 kg -> 0.09 m draft.
        # T = (Mass / 165.0) * 0.09
        self.T = (self.m_total / 165.0) * 0.09  # draft (m) Parameters obstained from design point of Salpa 1 USV.
        
        # Drag Scaling Factor:
        # Scale drag proportional to draft (and thus mass).
        self.drag_scale_factor = self.T / 0.09
        
        Ig_CG = m * np.diag(np.array([R44 ** 2, R55 ** 2, R66 ** 2]))
        self.Ig = Ig_CG - m * self.S_rg @ self.S_rg - self.mp * self.S_rp @ self.S_rp

        # Propeller lever arms and thrust coefficients (from configuration)
        self.l1 = -MOTOR_Y                  # lever arm, left propeller (m)
        self.l2 = MOTOR_Y                   # lever arm, right propeller (m)
        self.k_pos = K_POS           # positive thrust coefficient
        self.k_neg = K_NEG           # negative thrust coefficient
        
        # Max/min propeller speeds from thrust limits
        self.n_max = math.sqrt((MAX_THRUST_KGF * self.g) / self.k_pos)
        self.n_min = -math.sqrt((MIN_THRUST_KGF * self.g) / self.k_neg)

        # MRB_CG = [ (m+mp) * I3  O3      (Fossen 2021, Chapter 3)
        #               O3       Ig ]
        MRB_CG = np.zeros((6, 6))
        MRB_CG[0:3, 0:3] = (m + self.mp) * np.identity(3)
        MRB_CG[3:6, 3:6] = self.Ig
        MRB = self.H_rg.T @ MRB_CG @ self.H_rg

        # Hydrodynamic added mass (best practice)
        Xudot = -0.1 * m
        Yvdot = -1.5 * m
        Zwdot = -1.0 * m
        Kpdot = -0.2 * self.Ig[0, 0]
        Mqdot = -0.8 * self.Ig[1, 1]
        Nrdot = -2.1 * self.Ig[2, 2]

        self.MA = -np.diag([Xudot, Yvdot, Zwdot, Kpdot, Mqdot, Nrdot])

        # System mass matrix
        self.M = MRB + self.MA
        self.Minv = np.linalg.inv(self.M)

        # Hydrostatic quantities (Fossen 2021, Chapter 4)
        Aw_pont = Cw_pont * self.L * self.B_pont  # waterline area, one pontoon
        I_T = (
            2
            * (1 / 12)
            * self.L
            * self.B_pont ** 3
            * (6 * Cw_pont ** 3 / ((1 + Cw_pont) * (1 + 2 * Cw_pont)))
            + 2 * Aw_pont * y_pont ** 2
        )
        I_L = 0.8 * 2 * (1 / 12) * self.B_pont * self.L ** 3
        KB = (1 / 3) * (5 * self.T / 2 - 0.5 * nabla / (self.L * self.B_pont))
        BM_T = I_T / nabla  # BM values
        BM_L = I_L / nabla
        KM_T = KB + BM_T    # KM values
        KM_L = KB + BM_L
        KG = self.T - rg[2]
        GM_T = KM_T - KG    # GM values
        GM_L = KM_L - KG

        G33 = rho * self.g * (2 * Aw_pont)  # spring stiffness (heave)
        G44 = rho * self.g * nabla * GM_T     # spring stiffness (roll)
        G55 = rho * self.g * nabla * GM_L     # spring stiffness (pitch)
        G_CF = np.diag([0, 0, G33, G44, G55, 0])  # spring stiff. matrix in CF
        
        LCF = LCF_SALPA1                      # longitudinal center of flotation
        H = Hmtrx(np.array([LCF, 0.0, 0.0]))  # transform G_CF from CF to CO
        self.G = H.T @ G_CF @ H

        # Natural frequencies
        w3 = math.sqrt(G33 / self.M[2, 2])
        w4 = math.sqrt(G44 / self.M[3, 3])
        w5 = math.sqrt(G55 / self.M[4, 4])

        # Linear damping coefficients
        # Xu: surge damping from max speed (resistance = thrust at Umax)
        # We use the Total Max Thrust (2 motors) to calculate the resistance at max speed
        # Naval Arch Note: We split drag into Linear (friction) and Quadratic (pressure/wave)
        # Otter used 100% linear. We use 20% linear, 80% quadratic for better realism.
        # We also scale the drag based on the actual draft (drag_scale_factor).
        total_thrust_max = 2 * MAX_THRUST_KGF * self.g
        
        # Linear part (20% of total drag at max speed)
        Xu = (-0.2 * total_thrust_max / Umax) * self.drag_scale_factor
        
        # Quadratic part (80% of total drag at max speed) - stored for dynamics()
        self.Xu_quad = (-0.8 * total_thrust_max / (Umax ** 2)) * self.drag_scale_factor
        
        Yv = -self.M[1, 1] / T_sway          # sway - from time constant
        Zw = -2 * 0.3 * w3 * self.M[2, 2]    # heave - from rel. damping
        Kp = -2 * 0.2 * w4 * self.M[3, 3]    # roll - from rel. damping
        Mq = -2 * 0.4 * w5 * self.M[4, 4]    # pitch - from rel. damping
        Nr = -self.M[5, 5] / T_yaw           # yaw - from time constant

        self.D = -np.diag([Xu, Yv, Zw, Kp, Mq, Nr])

        # Propeller configuration/input matrix: tau = B * n²
        B = self.k_pos * np.array([[1, 1], [-self.l1, -self.l2]])
        self.Binv = np.linalg.inv(B)

        # ====================================================================
        # HEADING AUTOPILOT PARAMETERS (from configuration)
        # ====================================================================
        
        self.e_int = 0                          # integral error state
        self.wn = WN_AUTOPILOT           # PID natural frequency
        self.zeta = ZETA_AUTOPILOT       # PID damping ratio

        # Reference model states
        self.r_max = R_MAX_DEG * math.pi / 180   # max yaw rate (rad/s)
        self.psi_d = 0                          # desired heading angle
        self.r_d = 0                            # desired yaw rate
        self.a_d = 0                            # desired yaw acceleration
        self.wn_d = WN_REF               # reference model natural freq
        self.zeta_d = ZETA_REF           # reference model damping

        # Store yaw inertia for autopilot (M[5,5] = Izz + added mass)
        self.Izz_total = self.M[5, 5]
        
        # Print configuration summary
        print(f"\n{'='*60}")
        print(f"Salpa 1 USV Configuration Summary")
        print(f"{'='*60}")
        print(f"Dimensions:     L = {self.L:.2f} m, B = {self.B:.2f} m")
        print(f"Mass:           {self.m_total:.1f} kg (hull: {m:.1f}, payload: {self.mp:.1f})")
        print(f"Draft:          {self.T:.3f} m")
        print(f"Max speed:      {Umax:.2f} m/s ({MAX_SPEED_KNOTS:.1f} knots)")
        print(f"Yaw inertia:    {self.Izz_total:.1f} kg·m² (for autopilot tuning)")
        print(f"n_max:          {self.n_max:.1f} rad/s")
        print(f"{'='*60}\n")


    def dynamics(self, eta, nu, u_actual, u_control, sampleTime):
        """
        [nu,u_actual] = dynamics(eta,nu,u_actual,u_control,sampleTime) integrates
        the Otter USV equations of motion using Euler's method.
        """

        # Input vector
        n = np.array([u_actual[0], u_actual[1]])

        # Current velocities
        u_c = self.V_c * math.cos(self.beta_c - eta[5])  # current surge vel.
        v_c = self.V_c * math.sin(self.beta_c - eta[5])  # current sway vel.

        nu_c = np.array([u_c, v_c, 0, 0, 0, 0], float)  # current velocity vector
        Dnu_c = np.array([nu[5]*v_c, -nu[5]*u_c, 0, 0, 0, 0],float) # derivative
        nu_r = nu - nu_c  # relative velocity vector

        # Rigid body and added mass Coriolis and centripetal matrices
        # CRB_CG = [ (m+mp) * Smtrx(nu2)          O3   (Fossen 2021, Chapter 6)
        #              O3                   -Smtrx(Ig*nu2)  ]
        CRB_CG = np.zeros((6, 6))
        CRB_CG[0:3, 0:3] = self.m_total * Smtrx(nu[3:6])
        CRB_CG[3:6, 3:6] = -Smtrx(np.matmul(self.Ig, nu[3:6]))
        CRB = self.H_rg.T @ CRB_CG @ self.H_rg  # transform CRB from CG to CO

        CA = m2c(self.MA, nu_r)
        # Uncomment to cancel the Munk moment in yaw, if stability problems
        # CA[5, 0] = 0  
        # CA[5, 1] = 0 
        # CA[0, 5] = 0
        # CA[1, 5] = 0

        C = CRB + CA

        # Payload force and moment expressed in BODY
        R = Rzyx(eta[3], eta[4], eta[5])
        f_payload = np.matmul(R.T, np.array([0, 0, self.mp * self.g], float))              
        m_payload = np.matmul(self.S_rp, f_payload)
        g_0 = np.array([ f_payload[0],f_payload[1],f_payload[2], 
                         m_payload[0],m_payload[1],m_payload[2] ])

        # Control forces and moments - with propeller revolution saturation
        thrust = np.zeros(2)
        for i in range(0, 2):

            n[i] = sat(n[i], self.n_min, self.n_max)  # saturation, physical limits

            if n[i] > 0:  # positive thrust
                thrust[i] = self.k_pos * n[i] * abs(n[i])
            else:  # negative thrust
                thrust[i] = self.k_neg * n[i] * abs(n[i])

        # Control forces and moments
        tau = np.array(
            [
                thrust[0] + thrust[1],
                0,
                0,
                0,
                0,
                -self.l1 * thrust[0] - self.l2 * thrust[1],
            ]
        )

        # Hydrodynamic linear damping + nonlinear yaw damping
        tau_damp = -np.matmul(self.D, nu_r)
        
        # Add nonlinear surge damping (quadratic drag)
        tau_damp[0] = tau_damp[0] + self.Xu_quad * abs(nu_r[0]) * nu_r[0]
        
        # Add nonlinear yaw damping (empirical factor 10 from Otter model)
        tau_damp[5] = tau_damp[5] - 10 * self.D[5, 5] * abs(nu_r[5]) * nu_r[5]

        # State derivatives (with dimension)
        tau_crossflow = crossFlowDrag(self.L, self.B_pont, self.T, nu_r)
        sum_tau = (
            tau
            + tau_damp
            + tau_crossflow
            - np.matmul(C, nu_r)
            - np.matmul(self.G, eta)
            + g_0
        )

        nu_dot = Dnu_c + np.matmul(self.Minv, sum_tau)  # USV dynamics
        n_dot = (u_control - n) / self.T_n  # propeller dynamics

        # Forward Euler integration [k+1]
        nu = nu + sampleTime * nu_dot
        n = n + sampleTime * n_dot

        u_actual = np.array(n, float)

        return nu, u_actual


    def controlAllocation(self, tau_X, tau_N):
        """
        [n1, n2] = controlAllocation(tau_X, tau_N)
        """
        tau = np.array([tau_X, tau_N])  # tau = B * u_alloc
        u_alloc = np.matmul(self.Binv, tau)  # u_alloc = inv(B) * tau

        # u_alloc = abs(n) * n --> n = sign(u_alloc) * sqrt(u_alloc)
        n1 = np.sign(u_alloc[0]) * math.sqrt(abs(u_alloc[0]))
        n2 = np.sign(u_alloc[1]) * math.sqrt(abs(u_alloc[1]))

        return n1, n2


    def headingAutopilot(self, eta, nu, sampleTime):
        """
        u = headingAutopilot(eta, nu, sampleTime)
        
        PID controller for automatic heading control based on pole placement.
        Uses a 3rd-order reference model for smooth heading transitions.

        tau_N = (T/K) * a_d + (1/K) * rd
               - Kp * ( ssa( psi-psi_d ) + Td * (r - r_d) + (1/Ti) * z )
        """
        psi = eta[5]                              # yaw angle
        r = nu[5]                                 # yaw rate
        
        # Calculate raw reference in radians
        psi_ref_raw = self.ref * math.pi / 180
        
        # FIX 1: Prevent reference model unwinding (360-degree spins)
        # Ensure the new reference is within +/- 180 degrees of the CURRENT reference state
        psi_ref = self.psi_d + ssa(psi_ref_raw - self.psi_d)
        
        # FIX 2: Normalize tracking error to +/- 180 degrees
        e_psi = ssa(psi - self.psi_d)             # yaw angle tracking error
        
        e_r = r - self.r_d                        # yaw rate tracking error

        wn = self.wn                              # PID natural frequency
        zeta = self.zeta                          # PID damping factor
        wn_d = self.wn_d                          # reference model natural frequency
        zeta_d = self.zeta_d                      # reference model damping

        # Use computed yaw inertia (including added mass)
        # This replaces the hardcoded 41.4 from Otter
        m_yaw = self.Izz_total
        T = 1
        K = T / m_yaw
        d = 1 / K
        k = 0

        # PID feedback controller with 3rd-order reference model
        tau_X = self.tauX

        [tau_N, self.e_int, self.psi_d, self.r_d, self.a_d, self.Kp, self.Kd, self.Ki] = PIDpolePlacement(
            self.e_int,
            e_psi,
            e_r,
            self.psi_d,
            self.r_d,
            self.a_d,
            m_yaw,
            d,
            k,
            wn_d,
            zeta_d,
            wn,
            zeta,
            psi_ref,
            self.r_max,
            sampleTime,
        )
        # Note: psi_d is kept unwrapped for smooth reference model tracking
        # Wrap to [0, 2*pi] only when displaying/storing

        [n1, n2] = self.controlAllocation(tau_X, tau_N)
        u_control = np.array([n1, n2], float)

        return u_control


    def stepInput(self, t):
        """
        u = stepInput(t) generates propeller step inputs.
        """
        n1 = 100  # rad/s
        n2 = 80

        if t > 30 and t < 100:
            n1 = 80
            n2 = 120
        else:
            n1 = 0
            n2 = 0

        u_control = np.array([n1, n2], float)

        return u_control
