"""Multiplicative error-state INS for body-frame IMU and NED aiding data."""

from dataclasses import dataclass
import math

import numpy as np


def skew(vector):
    x_value, y_value, z_value = vector
    return np.array([
        [0.0, -z_value, y_value],
        [z_value, 0.0, -x_value],
        [-y_value, x_value, 0.0],
    ])


def normal_gravity(latitude_rad):
    sin_latitude = math.sin(latitude_rad)
    return (
        9.7803253359 * (1.0 + 0.00193185265241 * sin_latitude**2)
        / math.sqrt(1.0 - 0.00669437999013 * sin_latitude**2)
    )


def quaternion_product(left, right):
    left_scalar, left_vector = left[0], left[1:]
    right_scalar, right_vector = right[0], right[1:]
    return np.concatenate((
        [left_scalar * right_scalar - left_vector @ right_vector],
        left_scalar * right_vector
        + right_scalar * left_vector
        + np.cross(left_vector, right_vector),
    ))


def quaternion_from_rotation_vector(rotation_vector):
    angle = float(np.linalg.norm(rotation_vector))
    if angle < 1e-12:
        return np.concatenate(([1.0], 0.5 * rotation_vector))
    half_angle = 0.5 * angle
    return np.concatenate((
        [math.cos(half_angle)],
        math.sin(half_angle) * rotation_vector / angle,
    ))


def quaternion_from_euler(roll_rad, pitch_rad, yaw_rad):
    half_roll, half_pitch, half_yaw = 0.5 * np.array(
        [roll_rad, pitch_rad, yaw_rad]
    )
    cr, sr = math.cos(half_roll), math.sin(half_roll)
    cp, sp = math.cos(half_pitch), math.sin(half_pitch)
    cy, sy = math.cos(half_yaw), math.sin(half_yaw)
    return np.array([
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ])


def rotation_from_quaternion(quaternion):
    scalar, x_value, y_value, z_value = quaternion
    return np.array([
        [1 - 2 * (y_value**2 + z_value**2),
         2 * (x_value * y_value - scalar * z_value),
         2 * (x_value * z_value + scalar * y_value)],
        [2 * (x_value * y_value + scalar * z_value),
         1 - 2 * (x_value**2 + z_value**2),
         2 * (y_value * z_value - scalar * x_value)],
        [2 * (x_value * z_value - scalar * y_value),
         2 * (y_value * z_value + scalar * x_value),
         1 - 2 * (x_value**2 + y_value**2)],
    ])


def euler_from_quaternion(quaternion):
    rotation = rotation_from_quaternion(quaternion)
    pitch = -math.asin(float(np.clip(rotation[2, 0], -1.0, 1.0)))
    roll = math.atan2(rotation[2, 1], rotation[2, 2])
    yaw = math.atan2(rotation[1, 0], rotation[0, 0])
    return np.array([roll, pitch, yaw])


def wrap_pi(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class MekfTuning:
    accel_noise_mps2_sqrt_hz: float = 0.12
    gyro_noise_rad_s_sqrt_hz: float = math.radians(0.30)
    accel_bias_noise_mps2_sqrt_hz: float = 0.01
    gyro_bias_noise_rad_s_sqrt_hz: float = math.radians(0.02)
    accel_bias_tau_s: float = 500.0
    gyro_bias_tau_s: float = 500.0
    gravity_aiding_noise: float = 0.05
    gravity_gate_mps2: float = 0.75
    innovation_gate_sigma: float = 5.0
    max_step_s: float = 0.05


class InsMekf:
    """Nominal INS state plus a 15-state right-multiplicative error filter."""

    def __init__(self, tuning=None):
        self.tuning = tuning or MekfTuning()
        self.position = np.zeros(3)
        self.velocity = np.zeros(3)
        self.accel_bias = np.zeros(3)
        self.quaternion = np.array([1.0, 0.0, 0.0, 0.0])
        self.gyro_bias = np.zeros(3)
        self.covariance = np.eye(15)
        self.initialized = False

    def initialize(
        self,
        position_ned,
        velocity_ned,
        euler_rpy_rad,
        position_sigma=(1.0, 1.0, 2.0),
        velocity_sigma=(0.5, 0.5, 1.0),
        attitude_sigma_rad=None,
    ):
        attitude_sigma_rad = attitude_sigma_rad or (
            math.radians(5.0), math.radians(5.0), math.radians(10.0)
        )
        self.position = np.asarray(position_ned, dtype=float).copy()
        self.velocity = np.asarray(velocity_ned, dtype=float).copy()
        self.accel_bias = np.zeros(3)
        self.quaternion = quaternion_from_euler(*euler_rpy_rad)
        self.gyro_bias = np.zeros(3)
        standard_deviations = np.concatenate((
            np.asarray(position_sigma),
            np.asarray(velocity_sigma),
            np.full(3, 0.25),
            np.asarray(attitude_sigma_rad),
            np.full(3, math.radians(2.0)),
        ))
        self.covariance = np.diag(standard_deviations**2)
        self.initialized = True

    def predict(self, specific_force_body, angular_rate_body, dt, latitude_rad):
        if not self.initialized or not math.isfinite(dt) or dt <= 0.0:
            return
        force = np.asarray(specific_force_body, dtype=float)
        angular_rate = np.asarray(angular_rate_body, dtype=float)
        steps = max(1, math.ceil(dt / self.tuning.max_step_s))
        step_dt = dt / steps
        for _ in range(steps):
            self._predict_step(force, angular_rate, step_dt, latitude_rad)

    def _predict_step(self, measured_force, measured_rate, dt, latitude_rad):
        force = measured_force - self.accel_bias
        angular_rate = measured_rate - self.gyro_bias

        midpoint_delta = quaternion_from_rotation_vector(0.5 * angular_rate * dt)
        midpoint_quaternion = quaternion_product(self.quaternion, midpoint_delta)
        midpoint_quaternion /= np.linalg.norm(midpoint_quaternion)
        rotation = rotation_from_quaternion(midpoint_quaternion)
        gravity_ned = np.array([0.0, 0.0, normal_gravity(latitude_rad)])
        acceleration_ned = rotation @ force + gravity_ned

        self.position += self.velocity * dt + 0.5 * acceleration_ned * dt**2
        self.velocity += acceleration_ned * dt
        full_delta = quaternion_from_rotation_vector(angular_rate * dt)
        self.quaternion = quaternion_product(self.quaternion, full_delta)
        self.quaternion /= np.linalg.norm(self.quaternion)
        self.accel_bias *= math.exp(-dt / self.tuning.accel_bias_tau_s)
        self.gyro_bias *= math.exp(-dt / self.tuning.gyro_bias_tau_s)

        zeros = np.zeros((3, 3))
        identity = np.eye(3)
        dynamics = np.block([
            [zeros, identity, zeros, zeros, zeros],
            [zeros, zeros, -rotation, -rotation @ skew(force), zeros],
            [zeros, zeros, -identity / self.tuning.accel_bias_tau_s, zeros, zeros],
            [zeros, zeros, zeros, -skew(angular_rate), -identity],
            [zeros, zeros, zeros, zeros, -identity / self.tuning.gyro_bias_tau_s],
        ])
        noise_spread = np.block([
            [zeros, zeros, zeros, zeros],
            [-rotation, zeros, zeros, zeros],
            [zeros, identity, zeros, zeros],
            [zeros, zeros, -identity, zeros],
            [zeros, zeros, zeros, identity],
        ])
        noise_variances = np.concatenate((
            np.full(3, self.tuning.accel_noise_mps2_sqrt_hz**2),
            np.full(3, self.tuning.accel_bias_noise_mps2_sqrt_hz**2),
            np.full(3, self.tuning.gyro_noise_rad_s_sqrt_hz**2),
            np.full(3, self.tuning.gyro_bias_noise_rad_s_sqrt_hz**2),
        ))
        dynamics_dt = dynamics * dt
        transition = np.eye(15) + dynamics_dt + 0.5 * dynamics_dt @ dynamics_dt
        process_noise = noise_spread @ np.diag(noise_variances) @ noise_spread.T * dt
        self.covariance = (
            transition @ self.covariance @ transition.T + process_noise
        )
        self._stabilize_covariance()

    def update_position(
        self,
        position_ned,
        sigma_ned,
        apply_gate=True,
        clip_innovation=False,
    ):
        measurement = np.asarray(position_ned, dtype=float)
        observation = np.zeros((3, 15))
        observation[:, 0:3] = np.eye(3)
        return self._correct(
            measurement - self.position,
            observation,
            np.diag(np.asarray(sigma_ned, dtype=float) ** 2),
            apply_gate=apply_gate,
            clip_innovation=clip_innovation,
        )

    def update_velocity(self, velocity_ne, sigma_ne):
        measurement = np.asarray(velocity_ne, dtype=float)
        observation = np.zeros((2, 15))
        observation[:, 3:5] = np.eye(2)
        return self._correct(
            measurement - self.velocity[0:2],
            observation,
            np.diag(np.asarray(sigma_ne, dtype=float) ** 2),
        )

    def update_heading(self, heading_rad, sigma_rad):
        roll, pitch, yaw = euler_from_quaternion(self.quaternion)
        cos_pitch = max(abs(math.cos(pitch)), 1e-3)
        observation = np.zeros((1, 15))
        observation[0, 10:12] = [
            math.sin(roll) / cos_pitch,
            math.cos(roll) / cos_pitch,
        ]
        return self._correct(
            np.array([wrap_pi(heading_rad - yaw)]),
            observation,
            np.array([[sigma_rad**2]]),
        )

    def update_gravity(self, specific_force_body, latitude_rad):
        measured_force = np.asarray(specific_force_body, dtype=float) - self.accel_bias
        force_norm = float(np.linalg.norm(measured_force))
        expected_gravity = normal_gravity(latitude_rad)
        if force_norm < 1e-6 or abs(force_norm - expected_gravity) > self.tuning.gravity_gate_mps2:
            return False
        measured_direction = measured_force / force_norm
        predicted_direction = rotation_from_quaternion(self.quaternion).T @ np.array(
            [0.0, 0.0, -1.0]
        )
        observation = np.zeros((3, 15))
        observation[:, 9:12] = skew(predicted_direction)
        variance = self.tuning.gravity_aiding_noise**2
        return self._correct(
            measured_direction - predicted_direction,
            observation,
            np.eye(3) * variance,
        )

    def _correct(
        self,
        residual,
        observation,
        measurement_covariance,
        apply_gate=True,
        clip_innovation=False,
    ):
        if not self.initialized:
            return False
        innovation_covariance = (
            observation @ self.covariance @ observation.T + measurement_covariance
        )
        innovation_was_clipped = False
        try:
            normalized_innovation = float(
                residual.T @ np.linalg.solve(innovation_covariance, residual)
            )
            gate = self.tuning.innovation_gate_sigma**2 * residual.size
            if not math.isfinite(normalized_innovation):
                return False
            if apply_gate and normalized_innovation > gate:
                if not clip_innovation:
                    return False
                residual = residual * math.sqrt(gate / normalized_innovation)
                innovation_was_clipped = True
            gain = np.linalg.solve(
                innovation_covariance,
                observation @ self.covariance,
            ).T
        except np.linalg.LinAlgError:
            return False

        error_state = gain @ residual
        self.position += error_state[0:3]
        self.velocity += error_state[3:6]
        self.accel_bias += error_state[6:9]
        attitude_error = error_state[9:12]
        correction = quaternion_from_rotation_vector(attitude_error)
        self.quaternion = quaternion_product(self.quaternion, correction)
        self.quaternion /= np.linalg.norm(self.quaternion)
        self.gyro_bias += error_state[12:15]

        if not innovation_was_clipped:
            identity_minus_gain = np.eye(15) - gain @ observation
            self.covariance = (
                identity_minus_gain @ self.covariance @ identity_minus_gain.T
                + gain @ measurement_covariance @ gain.T
            )
        reset = np.eye(15)
        reset[9:12, 9:12] -= 0.5 * skew(attitude_error)
        self.covariance = reset @ self.covariance @ reset.T
        self._stabilize_covariance()
        return True

    def _stabilize_covariance(self):
        self.covariance = 0.5 * (self.covariance + self.covariance.T)
        diagonal = np.maximum(np.diag(self.covariance), 1e-12)
        np.fill_diagonal(self.covariance, diagonal)

    @property
    def euler_rpy_rad(self):
        return euler_from_quaternion(self.quaternion)

    @property
    def horizontal_position_sigma_m(self):
        return math.sqrt(max(0.0, self.covariance[0, 0] + self.covariance[1, 1]))

    @property
    def vertical_position_sigma_m(self):
        return math.sqrt(max(0.0, self.covariance[2, 2]))