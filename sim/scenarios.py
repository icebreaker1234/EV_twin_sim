"""Test scenarios: what the rider asks of the vehicle.

Two kinds:
  * "speed"    - follow a target speed profile (a PI driver produces the pedals)
  * "throttle" - open-loop pedal profile (used for launch and tip-in studies)

The drive cycles here are SYNTHETIC. They are shaped like urban / mixed riding
but are not WMTC or the Indian Driving Cycle; swap in the official speed
traces when you have the data (see `from_speed_trace`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

KMPH = 1.0 / 3.6


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: str                      # "speed" or "throttle"
    dt_s: float
    time_s: np.ndarray
    target_speed: np.ndarray = field(default_factory=lambda: np.zeros(0))  # m/s
    pedal: np.ndarray = field(default_factory=lambda: np.zeros(0))         # 0..1
    brake: np.ndarray = field(default_factory=lambda: np.zeros(0))         # 0..1
    grade: np.ndarray = field(default_factory=lambda: np.zeros(0))         # rise/run
    params: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.time_s)


def _time(duration_s: float, dt_s: float) -> np.ndarray:
    return np.arange(int(round(duration_s / dt_s))) * dt_s


def wot_launch(dt_s: float, duration_s: float = 40.0, t_on_s: float = 0.5) -> Scenario:
    """Full throttle from rest: for 0-40 km/h time, top speed and peak power."""
    t = _time(duration_s, dt_s)
    pedal = np.where(t >= t_on_s, 1.0, 0.0)
    return Scenario("wot_launch", "throttle", dt_s, t, pedal=pedal,
                    brake=np.zeros_like(t), grade=np.zeros_like(t),
                    params={"duration_s": duration_s, "t_on_s": t_on_s})


def throttle_step(dt_s: float, level: float = 0.5, from_level: float = 0.0,
                  t_step_s: float = 2.0, duration_s: float = 10.0) -> Scenario:
    """Pedal moves from `from_level` to `level` at t_step_s: tip-in jerk study."""
    t = _time(duration_s, dt_s)
    pedal = np.where(t >= t_step_s, level, from_level)
    return Scenario("throttle_step", "throttle", dt_s, t, pedal=pedal,
                    brake=np.zeros_like(t), grade=np.zeros_like(t),
                    params={"level": level, "from_level": from_level,
                            "t_step_s": t_step_s, "duration_s": duration_s})


def from_speed_trace(name: str, dt_s: float, knots_s: list[float], knots_kmph: list[float],
                     grade: float = 0.0, params: dict | None = None) -> Scenario:
    """Piecewise-linear speed target from (time, km/h) knots. Use for real cycles."""
    t = _time(knots_s[-1], dt_s)
    target = np.interp(t, knots_s, knots_kmph) * KMPH
    return Scenario(name, "speed", dt_s, t, target_speed=target,
                    grade=np.full_like(t, grade), params=params or {})


# (time s, km/h) knots
_URBAN = [(0, 0), (4, 0), (14, 30), (30, 30), (38, 0), (46, 0), (56, 25), (70, 40),
          (82, 40), (92, 15), (98, 15), (108, 35), (122, 35), (132, 0), (140, 0),
          (152, 30), (166, 30), (176, 0), (184, 0)]

_MIXED = [(0, 0), (5, 0), (20, 40), (50, 40), (62, 20), (75, 55), (110, 55), (125, 70),
          (170, 70), (185, 40), (210, 40), (222, 0), (232, 0), (250, 45), (290, 45),
          (305, 60), (350, 60), (365, 30), (380, 30), (392, 0), (400, 0)]


def urban_stopgo(dt_s: float) -> Scenario:
    k = list(zip(*_URBAN))
    return from_speed_trace("urban_stopgo", dt_s, list(k[0]), list(k[1]),
                            params={"synthetic": True})


def mixed_cycle(dt_s: float) -> Scenario:
    k = list(zip(*_MIXED))
    return from_speed_trace("mixed_cycle", dt_s, list(k[0]), list(k[1]),
                            params={"synthetic": True})


REGISTRY = {
    "wot_launch": wot_launch,
    "throttle_step": throttle_step,
    "urban_stopgo": urban_stopgo,
    "mixed_cycle": mixed_cycle,
}


def build(name: str, dt_s: float, **kwargs) -> Scenario:
    if name not in REGISTRY:
        raise KeyError(f"Unknown scenario '{name}'. Available: {sorted(REGISTRY)}")
    return REGISTRY[name](dt_s, **kwargs)
