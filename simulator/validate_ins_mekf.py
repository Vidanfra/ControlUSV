#!/usr/bin/env python3
"""Deterministic validation harness for the navigation INS MEKF.

Run from the repository root with:
    .venv/bin/python simulator/validate_ins_mekf.py
"""

import math
from pathlib import Path
import sys

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.models import InsConfig
from src.gnc.ins_mekf import InsMekf, normal_gravity
from src.gnc.navigation import NavigationProcess


LATITUDE_DEG = 39.325
LATITUDE_RAD = math.radians(LATITUDE_DEG)
GRAVITY = normal_gravity(LATITUDE_RAD)
STEP_S = 0.05


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def new_filter(velocity=(0.0, 0.0, 0.0), attitude=(0.0, 0.0, 0.0)):
    filter_ = InsMekf()
    filter_.initialize(
        position_ned=np.zeros(3),
        velocity_ned=np.asarray(velocity, dtype=float),
        euler_rpy_rad=np.asarray(attitude, dtype=float),
        position_sigma=(0.02, 0.02, 0.04),
        velocity_sigma=(0.15, 0.15, 0.5),
        attitude_sigma_rad=(
            math.radians(5.0),
            math.radians(5.0),
            math.radians(1.0),
        ),
    )
    return filter_


def require_valid_covariance(filter_):
    require(np.isfinite(filter_.covariance).all(), "covariance is not finite")
    minimum_eigenvalue = float(np.linalg.eigvalsh(filter_.covariance).min())
    require(minimum_eigenvalue > 0.0, "covariance is not positive definite")


def validate_stationary_mechanization():
    filter_ = new_filter()
    for _ in range(int(60.0 / STEP_S)):
        filter_.predict([0.0, 0.0, -GRAVITY], [0.0, 0.0, 0.0], STEP_S, LATITUDE_RAD)

    position_error = float(np.linalg.norm(filter_.position))
    velocity_error = float(np.linalg.norm(filter_.velocity))
    require(position_error < 1e-8, "stationary position drifted with an ideal IMU")
    require(velocity_error < 1e-9, "stationary velocity drifted with an ideal IMU")
    require_valid_covariance(filter_)
    return position_error


def validate_kinematics():
    accelerating = new_filter()
    acceleration = 0.4
    duration = 5.0
    for _ in range(int(duration / STEP_S)):
        accelerating.predict(
            [acceleration, 0.0, -GRAVITY],
            [0.0, 0.0, 0.0],
            STEP_S,
            LATITUDE_RAD,
        )
    require(
        np.allclose(accelerating.position[:2], [5.0, 0.0], atol=1e-8),
        "constant-acceleration position has the wrong sign or scale",
    )
    require(
        np.allclose(accelerating.velocity[:2], [2.0, 0.0], atol=1e-8),
        "constant-acceleration velocity has the wrong sign or scale",
    )

    speed = 2.0
    yaw_rate = 0.1
    duration = 20.0
    navigation = NavigationProcess.__new__(NavigationProcess)
    navigation.ins_config = InsConfig(
        use_magnetometer=False,
        gravity_max_speed_mps=0.5,
    )
    navigation.ins_filter = InsMekf(navigation._new_ins_filter().tuning)
    navigation.ins_filter.initialize(
        np.zeros(3), np.array([speed, 0.0, 0.0]), np.zeros(3)
    )
    navigation.ins_origin = (LATITUDE_DEG, -0.6, 0.0)
    navigation._last_ins_imu_t = 1000.0
    navigation._last_attitude_aid_t = 0.0
    navigation.imu_timestamp = 1000.0
    navigation._gnss_heading_t = 0.0
    navigation._gnss_heading_status = ''
    navigation.mag_heading_crp = 0.0
    for _ in range(int(duration / STEP_S)):
        navigation.imu_timestamp += STEP_S
        navigation.acc_crp = np.array([0.0, speed * yaw_rate, -GRAVITY])
        navigation.w_crp = np.degrees([0.0, 0.0, yaw_rate])
        navigation._process_ins_imu_sample()

    expected_position = np.array([
        speed / yaw_rate * math.sin(yaw_rate * duration),
        speed / yaw_rate * (1.0 - math.cos(yaw_rate * duration)),
    ])
    turn_error = float(
        np.linalg.norm(navigation.ins_filter.position[:2] - expected_position)
    )
    require(turn_error < 0.01, "navigation gravity aiding erased turn acceleration")
    return turn_error


def validate_attitude_updates():
    for axis in (0, 1):
        attitude = np.zeros(3)
        attitude[axis] = math.radians(5.0)
        filter_ = new_filter(attitude=attitude)
        before = abs(filter_.euler_rpy_rad[axis])
        accepted = filter_.update_gravity([0.0, 0.0, -GRAVITY], LATITUDE_RAD)
        after = abs(filter_.euler_rpy_rad[axis])
        require(accepted and after < before, "gravity update moved attitude away from level")

    filter_ = new_filter(attitude=(0.0, 0.0, math.radians(10.0)))
    filter_.covariance[11, 11] = math.radians(10.0) ** 2
    before = abs(filter_.euler_rpy_rad[2])
    accepted = filter_.update_heading(0.0, math.radians(1.0))
    after = abs(filter_.euler_rpy_rad[2])
    require(accepted and after < before, "heading update moved yaw away from measurement")
    return math.degrees(after)


def validate_rtk_interpolation():
    random = np.random.default_rng(42)
    velocity = np.array([1.0, 0.2, 0.0])
    heading = math.atan2(velocity[1], velocity[0])
    filter_ = new_filter(velocity=velocity, attitude=(0.0, 0.0, heading))
    fused_errors = []
    raw_errors = []

    for step in range(int(20.0 / STEP_S)):
        elapsed = (step + 1) * STEP_S
        truth = velocity * elapsed
        filter_.predict([0.0, 0.0, -GRAVITY], [0.0, 0.0, 0.0], STEP_S, LATITUDE_RAD)
        filter_.update_gravity([0.0, 0.0, -GRAVITY], LATITUDE_RAD)
        if step % 4 == 3:
            measurement = truth + random.normal(0.0, [0.02, 0.02, 0.04])
            filter_.update_position(
                measurement,
                [0.02, 0.02, 0.04],
                clip_innovation=True,
            )
            filter_.update_velocity(
                velocity[:2] + random.normal(0.0, 0.03, 2),
                [0.15, 0.15],
            )
            filter_.update_heading(heading, math.radians(0.5))
            raw_errors.append(float(np.linalg.norm(measurement[:2] - truth[:2])))
            fused_errors.append(float(np.linalg.norm(filter_.position[:2] - truth[:2])))

    raw_rms = float(np.sqrt(np.mean(np.square(raw_errors))))
    fused_rms = float(np.sqrt(np.mean(np.square(fused_errors))))
    require(fused_rms < 0.03, "RTK-aided solution did not remain centimeter-level")
    require(max(fused_errors) < 0.06, "20 Hz interpolation departed too far from RTK truth")
    require_valid_covariance(filter_)
    return raw_rms, fused_rms


def validate_degraded_gnss_smoothing():
    random = np.random.default_rng(20260831)
    filter_ = new_filter()
    raw_errors = []
    fused_errors = []

    for step in range(int(60.0 / STEP_S)):
        filter_.predict([0.0, 0.0, -GRAVITY], [0.0, 0.0, 0.0], STEP_S, LATITUDE_RAD)
        filter_.update_gravity([0.0, 0.0, -GRAVITY], LATITUDE_RAD)
        if step % 4 == 0:
            measurement = random.normal(0.0, [3.0, 3.0, 5.0])
            filter_.update_position(measurement, [3.0, 3.0, 5.0])
            filter_.update_velocity(random.normal(0.0, 0.15, 2), [0.9, 0.9])
            raw_errors.append(float(np.linalg.norm(measurement[:2])))
            fused_errors.append(float(np.linalg.norm(filter_.position[:2])))

    raw_rms = float(np.sqrt(np.mean(np.square(raw_errors))))
    fused_rms = float(np.sqrt(np.mean(np.square(fused_errors))))
    require(
        fused_rms < 0.3 * raw_rms,
        "degraded-GNSS fusion did not suppress position jitter",
    )
    require_valid_covariance(filter_)
    return raw_rms, fused_rms


def validate_rtk_recovery():
    filter_ = new_filter()
    filter_.position = np.array([10.0, 0.0, 0.0])
    residuals = []
    for _ in range(100):
        accepted = filter_.update_position(
            np.zeros(3), [0.02, 0.02, 0.04], clip_innovation=True
        )
        require(accepted, "robust RTK update was rejected")
        residuals.append(abs(float(filter_.position[0])))

    require(
        all(next_value < value for value, next_value in zip(residuals, residuals[1:])),
        "repeated RTK updates did not converge monotonically",
    )
    recovered_position = float(filter_.position[0])
    require(abs(recovered_position) < 0.1, "RTK updates did not re-anchor position")
    return recovered_position


def validate_complete_outage():
    filter_ = new_filter()
    for step in range(int(10.0 / STEP_S)):
        filter_.predict([0.0, 0.0, -GRAVITY], [0.0, 0.0, 0.0], STEP_S, LATITUDE_RAD)
        filter_.update_gravity([0.0, 0.0, -GRAVITY], LATITUDE_RAD)
        if step % 4 == 0:
            filter_.update_position(np.zeros(3), [0.02, 0.02, 0.04])
            filter_.update_velocity(np.zeros(2), [0.15, 0.15])
            filter_.update_heading(0.0, math.radians(0.5))

    sigma_before = filter_.horizontal_position_sigma_m
    for _ in range(int(30.0 / STEP_S)):
        filter_.predict([0.0, 0.0, -GRAVITY], [0.0, 0.0, 0.0], STEP_S, LATITUDE_RAD)
    sigma_after = filter_.horizontal_position_sigma_m

    require(np.isfinite(filter_.position).all(), "outage position became invalid")
    require(np.isfinite(filter_.velocity).all(), "outage velocity became invalid")
    require(sigma_after > sigma_before, "outage uncertainty did not grow")
    require_valid_covariance(filter_)

    biased = new_filter()
    for _ in range(int(30.0 / STEP_S)):
        biased.predict([0.01, 0.0, -GRAVITY], [0.0, 0.0, 0.0], STEP_S, LATITUDE_RAD)
    bias_drift = float(np.linalg.norm(biased.position[:2]))
    require(abs(bias_drift - 4.5) < 1e-6, "accelerometer-bias drift scaling is wrong")
    return sigma_before, sigma_after, bias_drift


def main():
    stationary_error = validate_stationary_mechanization()
    turn_error = validate_kinematics()
    residual_yaw = validate_attitude_updates()
    rtk_raw, rtk_fused = validate_rtk_interpolation()
    gps_raw, gps_fused = validate_degraded_gnss_smoothing()
    rtk_recovery = validate_rtk_recovery()
    sigma_before, sigma_after, bias_drift = validate_complete_outage()

    print("INS MEKF validation passed")
    print(f"  ideal stationary drift: {stationary_error:.3e} m / 60 s")
    print(f"  dynamic turn error: {turn_error:.6f} m / 20 s")
    print(f"  residual yaw after 10 deg correction: {residual_yaw:.3f} deg")
    print(f"  RTK horizontal RMS: raw {rtk_raw:.3f} m, fused {rtk_fused:.3f} m")
    print(f"  GPS horizontal RMS: raw {gps_raw:.3f} m, fused {gps_fused:.3f} m")
    print(f"  10 m RTK convergence residual: {rtk_recovery:.3f} m")
    print(f"  outage horizontal sigma: {sigma_before:.3f} -> {sigma_after:.3f} m")
    print(f"  0.01 m/s^2 unestimated bias drift: {bias_drift:.3f} m / 30 s")


if __name__ == "__main__":
    main()