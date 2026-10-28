"""Throttle-to-torque controller: the part the research hypothesis sweeps.

Signal chain (all discrete, fixed step dt):

    pedal -> throttle map (pow) -> first-order filter -> pure delay
          -> scale by available torque -> rate limit -> torque command

* throttle_map_exponent: >1 softens response at small throttle openings.
* filter_tau_s:          first-order low-pass on the mapped throttle.
* latency_s:             pure transport delay, quantised to whole time steps.
* torque_ramp_nm_per_s:  rate limit on the torque command (both directions).

The throttle fraction maps onto the torque *available at the current motor
speed*, so full throttle always means "everything the motor can give now".
"""
from __future__ import annotations

from collections import deque

from sim.config import ControllerParams
from sim.motor import Motor


class ThrottleController:
    def __init__(self, params: ControllerParams, motor: Motor, dt_s: float):
        self.p = params
        self.motor = motor
        self.dt = dt_s
        self._alpha = 1.0 if params.filter_tau_s <= 0 else dt_s / (params.filter_tau_s + dt_s)
        self._delay_steps = int(round(params.latency_s / dt_s))
        self.reset()

    def reset(self) -> None:
        self._filtered = 0.0
        self._delay = deque([0.0] * self._delay_steps, maxlen=self._delay_steps or None)
        self.torque_cmd = 0.0

    def step(self, pedal: float, omega: float) -> float:
        """Advance one step. pedal in [0, 1]; omega is motor speed (rad/s)."""
        pedal = min(1.0, max(0.0, pedal))
        mapped = pedal ** self.p.throttle_map_exponent
        self._filtered += self._alpha * (mapped - self._filtered)

        if self._delay_steps:
            delayed = self._delay[0]
            self._delay.append(self._filtered)
        else:
            delayed = self._filtered

        target = delayed * float(self.motor.torque_limit(omega))
        max_delta = self.p.torque_ramp_nm_per_s * self.dt
        delta = min(max_delta, max(-max_delta, target - self.torque_cmd))
        self.torque_cmd += delta
        return self.torque_cmd
