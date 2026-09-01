# INS MEKF

## Purpose

`NavigationProcess` uses a multiplicative error-state Kalman filter to combine
the body-frame IMU stream with GNSS position, velocity, and heading. The filter
publishes at the navigation loop rate, interpolating between GNSS samples and
continuing to propagate when GNSS degrades or disappears.

The filter can be disabled in **Settings > Sensors > Inertial Navigation
System**. In `GNSS Only` mode, the previous lever-arm-corrected GNSS path is
used without MEKF smoothing.

## Frames and units

- Navigation frame: local NED, in meters and meters per second.
- Body frame: X forward, Y starboard, Z down.
- Quaternion: scalar-first `[q0, q1, q2, q3]`, rotating body vectors into NED.
- Accelerometer input: specific force at the vessel CRP, in `m/s^2`.
- Gyroscope input: body angular rate converted from `deg/s` to `rad/s`.
- Heading and filter attitude: radians internally.

The raw WT901 measurements are first rotated using the configured IMU mounting
angles. Acceleration is then translated from the IMU location to the CRP using
the angular-rate and angular-acceleration lever-arm terms. The MEKF never
consumes untransformed sensor axes.

## State

The nominal INS state has 16 values:

```text
x = [position_NED(3), velocity_NED(3), accel_bias(3), quaternion(4), gyro_bias(3)]
```

Its covariance describes the 15-state local error:

```text
dx = [position_error(3), velocity_error(3), accel_bias_error(3),
      attitude_error(3), gyro_bias_error(3)]
```

Nominal propagation is:

$$
a^n = R_b^n(f_m-b_a) + g^n
$$

$$
p_{k+1} = p_k + v_k\Delta t + \frac{1}{2}a^n\Delta t^2,
\qquad
v_{k+1} = v_k + a^n\Delta t
$$

Attitude uses an exact quaternion rotation-vector increment. The error-state
transition uses a second-order approximation at 20 Hz, while continuous white
process noise is discretized to first order. Covariance correction uses the
Joseph form and a multiplicative quaternion reset.

## Initialization

Initialization requires all of the following:

- INS enabled.
- A transformed IMU sample.
- A nonzero, valid, recent GNSS fix.
- A usable global latitude and longitude.

The first CRP-corrected GNSS fix becomes the local NED origin. Horizontal
velocity is initialized from GNSS SOG and COG. Yaw starts from fresh
dual-antenna heading, then magnetic heading if enabled, then IMU yaw as a weak
last resort.

Changing IMU/GNSS offsets, changing INS tuning, or switching between simulated
and real IMU sources resets the filter and requires fresh initialization.

## Aiding policy

### Position

Each new GNSS fix is translated from the stern antenna to the CRP using the
current filtered attitude. Measurement noise depends on fix quality:

| Fix | Horizontal 1-sigma | Vertical 1-sigma |
|---|---:|---:|
| RTK Fixed | NMEA GST estimate, with configured floors | NMEA GST estimate, with configured floor |
| RTK Float | `0.5 m` default | `1.0 m` default |
| DGNSS | `1.5 m` default | `2.5 m` default |
| GPS | `3.0 m` default | `5.0 m` default |

RTK Fixed therefore strongly anchors the nominal state, while lower-quality
fixes are blended more softly to suppress position jitter.

RTK Fixed position updates use a clipped innovation. Normal measurement noise
is Kalman-filtered, while a large discrepancy is corrected by a bounded amount
on every sample instead of being rejected indefinitely or accepted as one jump.
Lower-quality position outliers remain innovation-gated.

### Velocity

GNSS SOG and COG form North/East velocity measurements. They describe the stern
antenna, so the rigid-body term `w x r` is removed before the update to refer
them to the CRP. Their configured base noise is multiplied by `1`, `2`, `4`, or
`6` for RTK Fixed, RTK Float, DGNSS, or GPS respectively.

### Heading

Fresh valid dual-antenna heading is the primary yaw aid. The receiver keeps
emitting THS after it loses the heading solution, so a heading is only used
while its status is valid *and* newer than two seconds. If it expires and
magnetic aiding is enabled, the transformed, tilt-compensated magnetic heading
provides a weaker yaw observation. With neither available, yaw propagates from
the gyroscope and reports heading status `I`.

### Gravity

Normalized accelerometer direction levels roll and pitch only below the
configured vessel-speed threshold and while measured specific-force magnitude
is close to local WGS-84 gravity. The speed gate is essential: applying a
gravity observation during a turn would mistake centripetal acceleration for
attitude and corrupt dead reckoning.

Gravity and magnetic updates are applied at `attitude_aiding_rate_hz` rather
than at the IMU rate. Wave-induced tilt and magnetic disturbance are strongly
correlated, so treating every sample as independent would make the filter
over-confident and track the disturbance.

## Output source and GNSS loss

`gnc/ekf_state` contains:

- `ins_active`: whether the published solution comes from the MEKF.
- `position_source`: `RTK_FIXED`, `RTK_FLOAT`, `DGNSS`, `GPS`, `INS`, or `SIM`.
- `horizontal_accuracy_m` and `vertical_accuracy_m`: covariance-derived
  1-sigma uncertainty for MEKF output.
- `fix_type`: decays to `0` when valid GNSS messages exceed the configured
  loss timeout, even if the last received fix was RTK.

During complete GNSS loss, the nominal state continues from IMU propagation and
`position_source` changes to `INS`. The decayed fix type preserves the existing
GNC GNSS-loss failsafe; continuous INS output must not masquerade as a live fix.

Dead reckoning has no fixed accuracy guarantee. Position error from a constant
unestimated acceleration bias grows approximately as:

$$
\lVert \delta p \rVert \approx \frac{1}{2}\lVert b_a \rVert t^2
$$

For example, `0.01 m/s^2` produces about `4.5 m` error after 30 seconds. Gyro
bias also rotates gravity into the horizontal plane and can cause faster drift.
The covariance is intentionally allowed to grow during an outage so consumers
can reject a solution whose uncertainty exceeds their operating limit.

## Validation

Run the deterministic harness outside the legacy test suite:

```bash
.venv/bin/python simulator/validate_ins_mekf.py
```

It verifies:

- Zero drift for an ideal stationary IMU.
- Constant-acceleration position and velocity signs/scales.
- Circular-motion mechanization and the gravity-aiding speed gate.
- Gravity and heading correction directions.
- 20 Hz interpolation between 5 Hz RTK updates.
- Authoritative RTK re-anchoring after degraded GNSS, followed by outlier gating.
- Reduced jitter with degraded GPS measurements.
- Finite dead reckoning and increasing covariance during complete GNSS loss.
- Positive-definite covariance throughout the scenarios.

This is deterministic software validation, not sensor characterization.

## Known limits and sea-trial checks

- The local tangent-plane frame omits Earth rotation, Coriolis, and
  transport-rate terms. It is intended for short-duration, local USV missions.
- GNSS measurements are applied when they arrive, with no compensation for the
  NMEA pipeline delay. Do not lower the RTK sigma floors below that delay times
  the vessel speed or the filter will chase a lagged position.
- Vertical velocity is not constrained to the water surface. Vertical
  dead-reckoning accuracy will degrade quickly without GNSS altitude.
- The real-time simulator currently supplies static gravity rather than
  hydrodynamically consistent maneuver acceleration. The standalone validator
  supplies synthetic dynamic acceleration to cover the mechanization signs.
- Default process and measurement noise values are starting points. Estimate
  IMU noise and bias stability from stationary logs before relying on outage
  performance.

Before autonomous deployment, log raw IMU, transformed IMU, navigation source,
fix type, and covariance accuracy during stationary, straight-line, turning,
RTK-degradation, and controlled GNSS-disconnection trials. Confirm that the GNC
failsafe still activates at its configured GNSS-loss duration.