# Salpa 1 — Parameter Identification & Calibration Guide

This document catalogues every empirical parameter in
[`src/gnc/Salpa1_ModelParameters.json`](src/gnc/Salpa1_ModelParameters.json),
explains its physical meaning, and provides a practical procedure for measuring
or identifying it on the real vessel.

**Priority legend**
| Tag | Meaning |
|-----|---------|
| 🔴 HIGH | Directly affects autopilot performance on real hardware. Must be calibrated before sea trials |
| 🟡 MED | Affects simulator accuracy or secondary control behaviour. Calibrate when possible |
| 🟢 LOW | Only relevant for 6-DOF roll/pitch/heave simulation, or negligible sensitivity |

---

## 1. Geometry

These are the most straightforward parameters: direct physical measurements of the hull.

| Parameter | Symbol | Units | Physical meaning | Measurement procedure | Equipment | Current value | Measured value |
|-----------|--------|-------|------------------|-----------------------|-----------|:---:|:---:|
| `length_m` | $L$ | m | Overall hull length from bow transom to stern transom | Tape measure along the centre line with vessel on land | Tape measure | 2.400 | |
| `beam_m` | $B$ | m | Maximum beam — outer edge to outer edge of pontoons | Tape measure at the widest point | Tape measure | 1.700 | |
| `draft_m` | $T$ | m | Waterline draft at nominal operating load (165 + 25 kg). Scales in the simulator with actual payload | Float the vessel at nominal load. Mark the waterline on a vertical rod held against the hull, then measure from the keel to the mark. Repeat port and starboard and average | Tape measure, calm water | 0.090 | |
| `lcf_m` | $x_{LCF}$ | m | Longitudinal Centre of Flotation — the point along the x-axis through which small trim (pitch) rotations occur when a weight is added | Add a small known weight $\delta m$ at two different longitudinal stations $x_1$, $x_2$. Measure draft change $\delta T$ at each. LCF is the station that produces no trim change. Alternatively measure from CAD waterplane geometry | Scale, waterline ruler | -0.001 | |
| `pontoon_beam_m` | $B_{pont}$ | m | Outer width (diameter) of one pontoon tube at the waterline | Caliper or tape across one pontoon at mid-ship | Tape / caliper | 0.350 | |
| `pontoon_y_m` | $y_{pont}$ | m | 🔴 Lateral distance from vessel centreline to the thrust axis of each motor. This is the **lever arm** used in thrust allocation: $\tau_N = (T_S - T_P) \times y_{pont}$ | Measure from vessel centreline to each motor shaft with vessel on land. Use a plumb line from each motor shaft to the ground and measure the ground distance to the centreline. Average port and starboard | Tape, plumb line | 0.673 | |
| `cw_pont` | $C_w$ | — | Waterplane area coefficient of one pontoon: $C_w = A_w / (L \times B_{pont})$. Accounts for the rounded cross-section of the tube | Trace the waterplane outline of one pontoon on a sheet of paper (with vessel at rest). Measure the enclosed area $A_w$ by planimeter or grid counting. $C_w = A_w / (L \times B_{pont})$ | Paper, planimeter or CAD | 0.75 | |
| `cb_pont` | $C_b$ | — | Block coefficient of one pontoon: $C_b = V_{pont} / (L \times B_{pont} \times T)$. $V_{pont}$ is the submerged volume per pontoon. From Archimedes: total displacement $\nabla = m_{total}/\rho$, so $V_{pont} = \nabla/2$ | $C_b = m_{total} / (2 \times \rho \times L \times B_{pont} \times T)$ where $\rho = 1025$ kg/m³. All other terms are directly measured | Depends on other measurements | 0.871 | |

---

## 2. Mass and Inertia

| Parameter | Symbol | Units | Physical meaning | Measurement procedure | Equipment | Current value | Measured value |
|-----------|--------|-------|------------------|-----------------------|-----------|:---:|:---:|
| `hull_kg` | $m_{hull}$ | kg | Dry mass of the bare hull, motors, ESCs, and permanently installed hardware (no payload) | Suspend the hull from a calibrated hanging scale or load cell. Run the measurement with no batteries or removable sensors | Hanging load cell or platform scale ≥ 200 kg | 165.0 | |
| `default_payload_kg` | $m_{payload}$ | kg | Mass of the current payload configuration (batteries, sensors, housings, cabling) | Weigh each payload item individually on a precision scale and sum. Update this value every time the payload changes | Precision scale ≥ 5 kg | 25.0 | |
| `cg_hull_m` | $\mathbf{r}_g$ | m | CG of the bare hull in body frame $[x_{fwd},\ y_{stbd},\ z_{down}]$ | **Three-point weighing:** support the hull on three load cells at known positions. Solve the 3-DOF static equilibrium to find $x_g$, $y_g$. $z_g$ is estimated from hull geometry or a tilt test (measure trim angle under a known vertical shift of the CG) | 3× load cells, rigid jig | [-0.063, 0.0, -0.065] | |
| `cg_payload_m` | $\mathbf{r}_p$ | m | CG of the payload in body frame | Measure the 3D position of each payload item's individual CG in the body frame. Compute the mass-weighted centroid: $\mathbf{r}_p = \sum m_i \mathbf{r}_i / \sum m_i$ | Tape measure, CAD | [0.1, 0.0, -0.1] | |
| `r44_coeff` | $k_{44}/B$ | — | Roll radius of gyration as a fraction of beam. $I_{44} = m \times (k_{44})^2$ | **Bifilar pendulum (roll axis):** suspend the hull from two wires of equal length $\ell$, attached symmetrically at $\pm d$ from the roll axis. Release from small roll angle, measure period $T_{osc}$. $I_{44} = m g d^2 T_{osc}^2 / (4\pi^2 \ell)$. $k_{44} = \sqrt{I_{44}/m}$, $r_{44} = k_{44}/B$ | Wires, stopwatch, ruler | 0.43 | |
| `r55_coeff` | $k_{55}/L$ | — | Pitch radius of gyration as a fraction of length. $I_{55} = m \times (k_{55})^2$ | **Bifilar pendulum (pitch axis):** same as above with wires fore and aft. $k_{55} = \sqrt{I_{55}/m}$, $r_{55} = k_{55}/L$ | Wires, stopwatch, ruler | 0.25 | |
| `r66_coeff` | $k_{66}/L$ | — | 🔴 Yaw radius of gyration as a fraction of length. Together with `nrdot_frac`, determines $I_{zz,total}$ which scales PID gains: $K_p = I_{zz} \omega_n^2$ | **Trifilar pendulum (horizontal):** suspend the hull horizontally from 3 wires of equal length $\ell$ at radius $R$ from the yaw axis. Measure yaw oscillation period $T_{osc}$. $I_{66} = m g R^2 T_{osc}^2 / (4\pi^2 \ell)$. $k_{66} = \sqrt{I_{66}/m}$, $r_{66} = k_{66}/L$. **Can also be measured with IMU on the water** (see §4 `nrdot_frac`) | Wires (3×), stopwatch, level surface | 0.25 | |
| `izz_total_kgm2` | $I_{zz,total}$ | kg·m² | 🔴 Total yaw moment of inertia **in water** (rigid body + yaw added mass). Used directly by `HeadingAutopilot` to compute PID gains. Stored separately from `r66_coeff` for the autopilot (which doesn't run the full vehicle model) | Trifilar pendulum **with vessel floating** (measure $I_{zz,total}$ including added mass): oscillate yaw with a horizontal bifilar suspended from a crane over water — or derive from the free yaw decay test (see §4). Alternatively compute from $r_{66\_coeff}$ result + added mass estimate: $I_{zz,total} \approx m(k_{66})^2 (1 + |N_{rdot\_frac}|)$ | Wires, IMU, stopwatch | 60.0 | |

---

## 3. Added Mass

Added mass (or hydrodynamic virtual inertia) is the hardest group to measure accurately in the field. 
For the **autopilot** (real hardware), only `nrdot_frac` matters significantly because it changes $I_{zz,total}$.
The remaining terms matter for **simulator accuracy** only.

> **Strip-theory background:** for a twin-pontoon catamaran the sway and yaw added mass are unusually large (factors of 1.5–2.0×) compared to a monohull, because the two pontoons together push a very wide water column.

| Parameter | Symbol | Units | Physical meaning | Measurement procedure | Equipment | Current value | Measured value |
|-----------|--------|-------|------------------|-----------------------|-----------|:---:|:---:|
| `xudot_frac` | $X_{\dot{u}}/m$ | — | 🟡 Surge added mass as a fraction of total mass. $M_{surge} = m(1 - x_{\dot{u}\_frac})$. Affects the velocity profiler ramp distances | **Surge deceleration fit:** drive to cruise speed, cut throttle, record $v(t)$ from dual-GNSS. Fit $(M_{surge}) \dot{v} = -(X_u v + X_{u^2} v^2)$ to extract $M_{surge}$. Then $x_{\dot{u}\_frac} = 1 - M_{surge}/m$. This test is **combined with drag identification** (§5). | Dual GNSS, data logging | -0.10 | |
| `yvdot_frac` | $Y_{\dot{v}}/m$ | — | 🟢 Sway added mass as a fraction of total mass. Large for a catamaran (~150%). Affects sway simulation dynamics | Sway impulse: push vessel laterally from dock. Record lateral velocity from IMU integration. Fit sway decay $v_y(t)$ to $(m + Y_{\dot{v}}) \dot{v}_y = -Y_v v_y$. Hard to separate from $Y_v$ without varying the push force. Semi-empirical: $Y_{\dot{v}} \approx -\rho \pi R^2 L / m$ per pontoon × 2 for circular cross-section | IMU (lateral accel) | -1.50 | |
| `zwdot_frac` | $Z_{\dot{w}}/m$ | — | 🟢 Heave added mass fraction. Only affects heave oscillation in simulator. Not used by autopilot | Semi-empirical from waterplane area. Can use natural heave frequency: $\omega_3 = \sqrt{G_{33}/M_{heave}}$ where $G_{33} = \rho g (2 A_{w,pont})$. Drop the vessel onto water and count heave oscillation frequency | Not needed for autopilot | -1.00 | |
| `kpdot_frac` | $K_{\dot{p}}/I_{44}$ | — | 🟢 Roll added moment fraction. Only affects roll simulation | Same approach as `yvdot_frac` but in roll. Very low priority | — | -0.20 | |
| `mqdot_frac` | $M_{\dot{q}}/I_{55}$ | — | 🟢 Pitch added moment fraction. Only affects pitch simulation | Analogous to heave. Very low priority | — | -0.80 | |
| `nrdot_frac` | $N_{\dot{r}}/I_{66}$ | — | 🔴 Yaw added moment fraction. $I_{zz,total} = I_{66,rigid}(1 + \|N_{rdot\_frac}\|)$. Since $K_p = I_{zz} \omega_n^2$, an error of 30% here translates to 30% wrong PID gains | **Free yaw decay test (recommended):** with vessel floating freely, apply a brief differential thrust impulse to spin the vessel to ~20–30°/s, then cut to zero. Record $r(t)$ from IMU. The **in-water** oscillation experiment gives $I_{zz,total}$ directly: $I_{zz,total} = N_{torque\_applied} / \alpha_{measured}$ for a known torque step, OR fit the free-yaw deceleration curve $(I_{zz,total}) \dot{r} = -(N_r r + N_{r^2}\|r\|r)$. Compare $I_{zz,total}$ to the in-air bifilar result to find $N_{rdot} = I_{zz,total} - I_{66,rigid}$. $N_{rdot\_frac} = N_{rdot}/I_{66,rigid}$ | IMU (gyro), data logging, propulsion control | -1.70 | |

---

## 4. Propulsion

The thrust model is $T = k \cdot n^2$ (forward) / $T = -k_{neg} \cdot n^2$ (reverse). All parameters should be measured on a **thrust stand** to eliminate hull interaction effects. 

> **Critical note on `pontoon_y_m`:** the allocation matrix inverse is $B^{-1} = (k_{pos} \begin{bmatrix}1 & 1\\ -l_1 & -l_2\end{bmatrix})^{-1}$. An error in `pontoon_y_m` directly scales how much of the commanded yaw torque is actually applied — verify this measurement to ±5 mm.

| Parameter | Symbol | Units | Physical meaning | Measurement procedure | Equipment | Current value | Measured value |
|-----------|--------|-------|------------------|-----------------------|-----------|:---:|:---:|
| `k_pos` | $k_{+}$ | N/(rad/s)² | 🔴 Forward thrust coefficient. $T_{fwd} = k_+ n^2$ where $n$ is propeller angular speed [rad/s] | **Thrust stand:** fix motor + propeller in a water tank at operating depth. Mount to a load cell. Apply throttle commands at multiple RPM setpoints. Read ESC-reported RPM (or optical tachometer). Plot $T$ vs $n^2$ → slope = $k_+$. Minimum 10 points from $n=50$ to $n=175$ rad/s | Load cell (0–150 N), RPM sensor, water tank | 0.00365 | |
| `k_neg` | $k_{-}$ | N/(rad/s)² | 🔴 Reverse thrust coefficient. $T_{rev} = -k_- n^2$. Typically ~70% of $k_+$ due to asymmetric prop geometry | Same thrust stand, reverse direction. Compare with forward to quantify asymmetry | Load cell, RPM sensor | 0.00255 | |
| `max_thrust_per_motor_kgf` | $T_{max}$ | kgf | Maximum forward thrust per motor at full ESC command. Used to compute `TAU_MAX = 2 T_{max} g` and `N_MAX` | Thrust stand at full throttle. Read peak load cell value. Average over 10–30 s steady state to exclude transients. **Manufacturer value is 11.5 kgf** — verify on actual propeller (size/pitch may differ from datasheet) | Load cell | 11.5 | |
| `max_reverse_thrust_per_motor_kgf` | $T_{max,rev}$ | kgf | Maximum reverse thrust per motor. Used to compute `N_MIN` | Thrust stand at full reverse throttle | Load cell | 8.0 | |
| `t_prop_s` | $T_{prop}$ | s | 🟡 First-order lag of the ESC + motor + propeller system. Models the delay between a commanded RPM change and the actual thrust response. Used in the simulator dynamics | **Step response test:** command a step from 0 to 100% throttle on the stand. Record thrust vs time at 100 Hz or faster. Fit $T(t) = T_{max}(1 - e^{-t/T_{prop}})$. Repeat at several throttle levels and average. Note: the ESC may have software ramping that dominates over the motor inertia | Load cell + high-rate data logger (≥100 Hz) | 0.10 | |
| `max_speed_kn` | $U_{max}$ | kn | 🔴 Maximum speed over ground at full throttle, calm water. This is the **drag calibration anchor**: $F_{drag}(U_{max}) = \tau_{max}$ by assumption | **GPS speed trial:** run the vessel at full throttle in both directions along the same straight course in flat water on a windless day. Average the two-direction speed to cancel current. Record 10+ passes with RTK GNSS, use maximum sustained speed (10 s average). Conditions: $< 0.2$ m/s current, $< 3$ kn wind | RTK GNSS, calm water | 4.00 | |

---

## 5. Surge Drag

The surge drag model is $F_{drag}(v) = X_{u,lin} \cdot v + X_{u,quad} \cdot v^2$, where:

$$X_{u,lin} = \frac{xu\_lin\_frac \times \tau_{max}}{U_{max}}, \quad X_{u,quad} = \frac{xu\_quad\_frac \times \tau_{max}}{U_{max}^2}$$

The constraint $xu\_lin\_frac + xu\_quad\_frac = 1$ ensures $F_{drag}(U_{max}) = \tau_{max}$ (drag equals thrust at maximum speed). The **split between linear and quadratic** determines how drag scales at intermediate speeds — this directly affects the velocity profiler deceleration ramp distances.

> **Most practical field method: coasting deceleration.** Drive to cruise speed, cut both motors, and log GPS velocity. Fit the ODE $M_{surge}\,\dot{v} = -(X_{u,lin}\,v + X_{u,quad}\,v^2)$ to the $v(t)$ time series using nonlinear least-squares.

| Parameter | Symbol | Units | Physical meaning | Measurement procedure | Equipment | Current value | Measured value |
|-----------|--------|-------|------------------|-----------------------|-----------|:---:|:---:|
| `xu_lin_frac` | $f_{lin}$ | — | 🔴 Fraction of total drag that is linear in speed. Low $f_{lin}$ → more quadratic character → drag increases steeply at high speed → shorter decel ramps | **Multi-speed steady-state:** hold constant speeds $v_1$, $v_2$ (e.g. 1.0 and 1.8 m/s) using closed-loop throttle. At each speed, $T_{applied} = F_{drag}(v)$. Read $n_i$ from ESC and compute $T_i = k_+ n_i^2$. Solve: $X_{u,lin} v_i + X_{u,quad} v_i^2 = T_i$ (2 equations, 2 unknowns). Then $f_{lin} = X_{u,lin} U_{max}/\tau_{max}$. **OR use coasting deceleration fit** (see note above — single experiment identifies both fractions simultaneously) | RTK GNSS (dual antenna for accurate speed), ESC telemetry | 0.20 | |
| `xu_quad_frac` | $f_{quad}$ | — | 🔴 Fraction of total drag that is quadratic in speed. $f_{quad} = 1 - f_{lin}$. Dominant at cruise speeds on this vessel (80%). High $f_{quad}$ means drag grows rapidly with speed → shorter coast-to-stop distances at high speed | Identified simultaneously with `xu_lin_frac` | Same as above | 0.80 | |
| `yaw_quad_fac` | — | — | 🟡 Multiplier on the yaw quadratic damping term. Higher value → yaw decelerates faster after differential thrust is removed. Affects simulator yaw manoeuvre fidelity. Does **not** affect the real autopilot (only used in 6-DOF sim). | **Yaw rate decay test:** apply full differential thrust for ~3 s to spin up to $r \approx 20{-}30$°/s, then cut all motors. Record $r(t)$ from IMU. Fit $I_{zz,total}\,\dot{r} = -(N_{r,lin}\,r + N_{r,quad}\|r\|r)$ where $N_{r,quad} = k_{yaw}\,X_{u,quad}\,L_{eff}^2$. Adjust `yaw_quad_fac` until the simulated yaw decay matches the recorded trace | IMU, data logging | 10.0 | |

---

## 6. Damping Time Constants

These first-order time constants approximate linear damping for the **sway** and **yaw** degrees of freedom. They are used in the 6-DOF simulator to set off-diagonal damping matrix entries. They do **not** affect the PID autopilot directly.

| Parameter | Symbol | Units | Physical meaning | Measurement procedure | Equipment | Current value | Measured value |
|-----------|--------|-------|------------------|-----------------------|-----------|:---:|:---:|
| `t_sway_s` | $T_{sway}$ | s | 🟡 Sway (lateral) linear damping time constant. $v_y(t) = v_{y0}\,e^{-t/T_{sway}}$ in free drift after a lateral impulse. Smaller $T_{sway}$ → heavier lateral damping | **Sway impulse test:** push the vessel sideways from a dock with a known brief force. Cut all thrust. Record lateral acceleration $a_y(t)$ from IMU, integrate to obtain $v_y(t)$. Fit single exponential to extract $T_{sway}$. Alternatively, apply a brief lateral thruster burst then cut to zero (requires simultaneous firing of both motors in the same direction — check feasibility in allocation matrix) | IMU (lateral axis) | 1.5 | |
| `t_yaw_s` | $T_{yaw}$ | s | 🟡 Yaw linear damping time constant. Applies to the **linear** part of yaw drag used in the Nomoto model. Note: the Nomoto model in `HeadingAutopilot` uses $d = 1/K = I_{zz}/T_{yaw}$ implicitly through the gain formulas. Setting $d=0$ at present makes this term inactive in PID design, but it is used in the 6-DOF sim | **Yaw rate decay test** (same experiment as `yaw_quad_fac`): from the $r(t)$ curve, the initial slope at $r \approx 0$ gives the linear part: $T_{yaw} = -I_{zz,total}/N_{r,lin}$ where $N_{r,lin}$ is the linear coefficient from the two-term fit | IMU (gyro), data logging | 1.5 | |

---

## 7. Control Defaults

These are **tuning parameters**, not physical parameters. They live in `Salpa1_ModelParameters.json` only as factory defaults and can be adjusted at runtime from the **Settings** view without touching the JSON. The table below gives guidance on how to determine appropriate values from sea trials.

| Parameter | Symbol | Units | Physical meaning | How to choose / tune | Default | Tuned value |
|-----------|--------|-------|------------------|----------------------|:-------:|:-----------:|
| `wn` | $\omega_n$ | rad/s | 🔴 PID inner-loop natural frequency. Bandwidth ≈ $\omega_n/(2\pi)$ Hz. Settling time ≈ $4/(\zeta \omega_n)$ s. Gains: $K_p = I_{zz}\,\omega_n^2$, $K_d = 2 I_{zz}\,\zeta\,\omega_n$ | Start at $\omega_n = 1.0$. Perform step heading commands ($\pm 30°, \pm 90°$). Increase $\omega_n$ until heading tracks quickly without oscillation. Back off by 20% from the onset of oscillation. Typical range 0.8–2.5 rad/s. **Increasing $\omega_n$ scales $K_p$ quadratically** — be cautious | 1.5 | |
| `zeta` | $\zeta$ | — | 🔴 PID damping ratio. $\zeta = 0.7$ is Butterworth (minimal overshoot). $\zeta < 0.5$ causes oscillation. $\zeta > 1.0$ is overdamped (slow) | Observe heading step responses. Increase if oscillation present, decrease if too sluggish. Butterworth ($\zeta = 0.7$) is usually the best starting point. Range 0.5–1.2 | 0.7 | |
| `wn_ref` | $\omega_{n,ref}$ | rad/s | 🟡 Reference model (heading pre-filter) natural frequency. Determines how fast the desired heading ramps when a new heading command arrives. Settling time ≈ $4/(\zeta_{ref}\,\omega_{n,ref})$ s | Must satisfy $\omega_{n,ref} < \omega_n$. Too high → abrupt heading commands hit the motor saturation limits. Too low → very slow heading changes. At 0.5 rad/s with $\zeta_{ref}=1.0$, a 90° turn ramps over ~8 s. Increase to 1.0 if turns are too slow in practice | 0.5 | |
| `zeta_ref` | $\zeta_{ref}$ | — | 🟡 Reference model damping. $\zeta_{ref}=1.0$ (critically damped) means the commanded heading ramps smoothly with no overshoot in the reference itself | 1.0 is almost always optimal. Change only if the heading reference has visible lag (increase) or overshoot (decrease) — rarely needed | 1.0 | |
| `r_max_deg_s` | $\dot{\psi}_{max}$ | °/s | 🟢 Hard yaw-rate cap inside the reference model. At 1000 °/s it is effectively unlimited. Set to e.g. 20 °/s to add hard rate limiting during fast turns | Leave at 1000 (unlimited) unless the vessel is found to overshoot its acceptance radius on tight waypoint turns despite correct look-ahead tuning. Then reduce to cap the yaw rate | 1000 | |
| `k_delta_s` | $k_\Delta$ | s | 🔴 ALOS look-ahead time constant. $\Delta = \max(\Delta_{min},\, k_\Delta \cdot U)$. The cross-track error convergence time constant is $\tau_{ye} = \Delta/U = k_\Delta$ (constant at all speeds). Rule: $k_\Delta \gg 4/(\zeta\,\omega_n) \approx 3.8$ s at defaults | Perform straight-line runs with an initial cross-track offset. Observe how quickly the vessel converges back to the path without oscillation. Decrease $k_\Delta$ if convergence is too slow; increase if the path approach is oscillatory. Typical range 10–25 s | 15.0 | |
| `delta_min_m` | $\Delta_{min}$ | m | 🟡 Minimum look-ahead distance (low-speed floor). Prevents numerical issues when $U \approx 0$ (ALOS denominator instability). Should be $\geq 1$ body length | Set to ~1.5–2× the acceptance radius. At $\Delta_{min}=5$ m and $r_{wp}=5$ m, the vessel always has a stable target even at rest. Reduce to 3 m if waypoints are close together | 5.0 | |
| `e_x_threshold_deg` | $e_{x,th}$ | ° | 🟡 Anti-windup threshold. Integrator accumulates only when $|\psi_{error}| < e_{x,th}$. Prevents integral windup during large-angle manoeuvres | Set to ≈$2 \times$ the typical steady-state heading error in calm water. 10° is conservative. Reduce to 5° if there is residual steady-state heading error that the integrator is not correcting | 10.0 | |

---

## 8. Suggested Calibration Sequence

Run experiments in this order (each result feeds into the next):

```
1. Geometry (tape measure, on land)           → pontoon_y_m, length_m, beam_m, draft_m
2. Mass (hanging scale, on land)              → hull_kg, payload_kg
3. CG (three-point weighing, on land)         → cg_hull_m
4. In-air MOI (trifilar pendulum, on land)    → r66_coeff, r44_coeff, r55_coeff
5. Thrust stand (in water tank)               → k_pos, k_neg, t_prop_s, max_thrust_kgf
6. GPS speed trial (on water)                 → max_speed_kn  [anchors drag scale]
7. Coasting deceleration (on water)           → xu_lin_frac, xu_quad_frac, xudot_frac
8. Yaw decay (on water)                       → nrdot_frac, izz_total, yaw_quad_fac
9. Sway impulse (on water)                    → t_sway_s, yvdot_frac
10. GNC step-response sea trials              → wn, zeta, wn_ref, k_delta_s
```

**Minimum viable set for autopilot accuracy** (steps 1, 2, 5, 6, 7, 8, 10):
`pontoon_y_m`, `k_pos`, `k_neg`, `max_speed_kn`, `xu_lin_frac`, `xu_quad_frac`, `nrdot_frac` / `izz_total_kgm2`.

---

## 9. How Errors Propagate to Autopilot Performance

| Parameter error | Effect |
|----------------|--------|
| `pontoon_y_m` wrong by 5 cm | Yaw torque per differential thrust error = 5/673 ≈ 7%. PID gains unchanged but effective plant gain is wrong → slight heading offset under turning | 
| `izz_total_kgm2` wrong by 20% | $K_p$, $K_d$ wrong by 20% → proportional reduction in closed-loop bandwidth. With $I_{zz}$ 20% too low, the autopilot is under-tuned (sluggish but stable). With 20% too high, over-tuned (faster but may oscillate) |
| `xu_quad_frac` wrong (e.g. 0.5 instead of 0.8) | Velocity profiler decel ramps over/under-estimated. Vessel arrives at WP too fast or too slow. No effect on heading control |
| `k_pos` wrong by 10% | Thrust allocation gives incorrect motor RPM for commanded force/torque. If $k_+$ is over-estimated, actual thrust is lower → vessel is slow to reach commanded speed |
| `max_speed_kn` wrong | Drag coefficients $X_{u,lin}$ and $X_{u,quad}$ are both scaled proportionally. A 10% error in $U_{max}$ → 10% error in $X_{u,lin}$ and 21% error in $X_{u,quad}$ (quadratic scaling) |
