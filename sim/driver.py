"""Rider model: a PI speed follower that turns a target speed into pedal inputs.

Output is (throttle, brake), each in [0, 1]. Used for drive-cycle scenarios;
open-loop scenarios (e.g. a throttle step) bypass the driver entirely.
"""
from __future__ import annotations


class PIDriver:
    def __init__(self, kp: float = 0.45, ki: float = 0.15, brake_gain: float = 0.5):
        self.kp, self.ki, self.brake_gain = kp, ki, brake_gain
        self._integral = 0.0

    def reset(self) -> None:
        self._integral = 0.0

    def step(self, target_speed: float, speed: float, dt_s: float) -> tuple[float, float]:
        err = target_speed - speed
        u = self.kp * err + self.ki * self._integral
        saturated = u > 1.0 or u < -1.0
        # Anti-windup: freeze the integrator while the pedal is saturated and
        # the error would push it further out.
        if not (saturated and (u * err) > 0):
            self._integral += err * dt_s
        if target_speed <= 0.05 and speed < 0.3:
            self._integral = 0.0
        u = self.kp * err + self.ki * self._integral
        if u >= 0:
            return min(1.0, u), 0.0
        return 0.0, min(1.0, -u * self.brake_gain * 2.0)
