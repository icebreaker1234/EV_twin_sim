"""Longitudinal vehicle dynamics (1-D): motor torque in, speed and acceleration out.

    m_eff * a = F_traction - F_drag - F_rolling - F_grade - F_brake

Rotating inertia is folded into m_eff (see VehicleParams.effective_mass_kg).
Pitch, tyre slip and load transfer are out of scope for this base model.
"""
from __future__ import annotations

import math

from sim.config import VehicleParams

MAX_BRAKE_DECEL = 4.0   # m/s^2, mechanical braking at full brake (about 0.4 g)


class Vehicle:
    def __init__(self, params: VehicleParams):
        self.p = params
        self.speed = 0.0          # m/s, never negative in this model
        self.distance = 0.0       # m
        self.accel = 0.0          # m/s^2 from the last step

    def reset(self) -> None:
        self.speed = self.distance = self.accel = 0.0

    def motor_omega(self, speed: float | None = None) -> float:
        """Motor shaft speed (rad/s) for a given road speed."""
        v = self.speed if speed is None else speed
        return v / self.p.wheel_radius_m * self.p.drivetrain_ratio

    def wheel_force(self, motor_torque: float) -> float:
        p = self.p
        eff = p.drivetrain_efficiency if motor_torque >= 0 else 1.0 / p.drivetrain_efficiency
        return motor_torque * p.drivetrain_ratio * eff / p.wheel_radius_m

    def resistive_force(self, speed: float, grade: float = 0.0) -> float:
        """Drag + rolling + grade (N), opposing forward motion. grade = rise/run."""
        p = self.p
        drag = 0.5 * p.air_density * p.drag_coeff * p.frontal_area_m2 * speed * speed
        theta = math.atan(grade)
        rolling = p.rolling_resistance * p.total_mass_kg * p.gravity * math.cos(theta) if speed > 0.01 else 0.0
        grade_f = p.total_mass_kg * p.gravity * math.sin(theta)
        return drag + rolling + grade_f

    def step(self, motor_torque: float, brake: float, dt_s: float, grade: float = 0.0) -> float:
        """Advance one step; returns acceleration (m/s^2). brake in [0, 1]."""
        f_trac = self.wheel_force(motor_torque)
        f_res = self.resistive_force(self.speed, grade)
        f_brake = min(1.0, max(0.0, brake)) * MAX_BRAKE_DECEL * self.p.effective_mass_kg

        if self.speed <= 0.0:
            # At rest: resistance and braking cannot push the vehicle backwards.
            a = max(0.0, f_trac - f_res) / self.p.effective_mass_kg
        else:
            a = (f_trac - f_res - f_brake) / self.p.effective_mass_kg

        new_speed = self.speed + a * dt_s
        if new_speed < 0.0:                 # braking or drag stopped the vehicle
            a = -self.speed / dt_s
            new_speed = 0.0
        self.accel = a
        self.distance += 0.5 * (self.speed + new_speed) * dt_s
        self.speed = new_speed
        return a
