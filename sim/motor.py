"""Electric motor model: torque-speed envelope and electrical power draw.

The motor is a quasi-static map (no electrical dynamics). Available torque is
constant up to the base speed, then falls as 1/omega so mechanical power stays
at peak. Beyond max_rpm no torque is available. Efficiency is a flat number for
now; an efficiency map can replace `efficiency_at` later without touching callers.

Sign convention: positive torque drives the vehicle, negative torque is
regenerative braking. Electrical power is positive when drawn from the battery
and negative when returned to it.
"""
from __future__ import annotations

import math

import numpy as np

from sim.config import MotorParams

RPM_TO_RADS = 2.0 * math.pi / 60.0


class Motor:
    def __init__(self, params: MotorParams):
        self.p = params
        self.base_omega = params.peak_power_w / params.peak_torque_nm  # rad/s
        self.max_omega = params.max_rpm * RPM_TO_RADS

    def torque_limit(self, omega):
        """Maximum torque magnitude (N*m) available at motor speed omega (rad/s).

        Accepts scalars or numpy arrays. Speed is taken as a magnitude, so the
        same envelope applies to motoring and regeneration.
        """
        w = np.abs(np.asarray(omega, dtype=float))
        t = np.where(
            w <= self.base_omega,
            self.p.peak_torque_nm,
            self.p.peak_power_w / np.maximum(w, 1e-9),
        )
        return np.where(w > self.max_omega, 0.0, t)

    def clip_torque(self, torque_cmd, omega):
        """Clamp a torque request to the envelope at this speed."""
        lim = self.torque_limit(omega)
        return np.clip(np.asarray(torque_cmd, dtype=float), -lim, lim)

    def efficiency_at(self, torque, omega):
        """Motor+inverter efficiency. Flat for now; replace with a map later."""
        return self.p.efficiency

    def electrical_power(self, torque, omega):
        """Battery-side power (W) for an applied torque at motor speed omega.

        Motoring draws more than the mechanical output (losses add);
        regenerating returns less than the mechanical input.
        """
        torque = np.asarray(torque, dtype=float)
        p_mech = torque * np.asarray(omega, dtype=float)
        eta = self.efficiency_at(torque, omega)
        return np.where(p_mech >= 0.0, p_mech / eta, p_mech * eta)
