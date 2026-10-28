"""Rider upper-body model: an inverted pendulum on a torsional spring-damper.

Frame: the scooter, which accelerates forward at ``a``. In that frame the torso
feels a backward inertial force m*a at its centre of mass, which tips it back.
theta is the backward lean from vertical (positive = leaning back).

    I*theta'' = m*L*a*cos(theta) + m*g*L*sin(theta) - k*theta - c*theta'

with I = m*L^2 (point mass at height L above the hips). The m*g*L*sin term is
gravity trying to tip the torso over; k is chosen so that the *net* small-angle
stiffness is I*omega_n^2, which makes omega_n the real natural frequency:

    k = I*omega_n^2 + m*g*L,      c = 2*zeta*I*omega_n

The head sits higher up the same rigid torso, at height H, so its backward
displacement is H*sin(theta) and its absolute forward acceleration is

    a_head = a - H*(cos(theta)*theta'' - sin(theta)*theta'^2)

One-way coupling: the torso is driven by the scooter, but its reaction on the
scooter is ignored (the rider's mass is already in the vehicle's total mass).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from sim.config import RiderBodyParams


@dataclass
class RiderStep:
    lean_rad: float
    lean_rate_rads: float
    head_accel_ms2: float


class Rider:
    def __init__(self, params: RiderBodyParams, rider_mass_kg: float, gravity: float):
        self.p = params
        self.g = gravity
        self.mass = params.torso_mass_fraction * rider_mass_kg
        self.L = params.torso_com_height_m
        self.H = params.head_height_m
        self.inertia = self.mass * self.L ** 2
        omega_n = 2.0 * math.pi * params.natural_freq_hz
        self.omega_n = omega_n
        self.k = self.inertia * omega_n ** 2 + self.mass * gravity * self.L
        self.c = 2.0 * params.damping_ratio * self.inertia * omega_n
        self.theta = 0.0
        self.omega = 0.0

    def reset(self, theta: float = 0.0, omega: float = 0.0) -> None:
        self.theta, self.omega = theta, omega

    def step(self, accel_ms2: float, dt_s: float) -> RiderStep:
        """Advance one step given the scooter's forward acceleration."""
        th, w = self.theta, self.omega
        torque = (self.mass * self.L * accel_ms2 * math.cos(th)
                  + self.mass * self.g * self.L * math.sin(th)
                  - self.k * th - self.c * w)
        alpha = torque / self.inertia
        w += alpha * dt_s                    # semi-implicit Euler: velocity first,
        th += w * dt_s                       # then position with the new velocity
        self.theta, self.omega = th, w
        head_back_accel = self.H * (math.cos(th) * alpha - math.sin(th) * w * w)
        return RiderStep(th, w, accel_ms2 - head_back_accel)
