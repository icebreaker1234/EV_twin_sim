"""Typed, validated configuration for the EV digital twin.

Vehicles are defined in YAML (see configs/). Every model is frozen and rejects
unknown keys, so a typo in a YAML file or a sweep override fails loudly instead
of being silently ignored.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Meta(_Frozen):
    name: str
    variant: str
    notes: str = ""


class VehicleParams(_Frozen):
    vehicle_mass_kg: float = Field(gt=30, lt=400)      # kerb mass
    rider_mass_kg: float = Field(gt=30, lt=200)
    wheel_radius_m: float = Field(gt=0.1, lt=0.5)
    frontal_area_m2: float = Field(gt=0.2, lt=2.0)
    drag_coeff: float = Field(gt=0.2, lt=1.5)
    rolling_resistance: float = Field(gt=0.001, lt=0.05)
    air_density: float = Field(gt=0.8, lt=1.5)
    gravity: float = Field(gt=9.0, lt=10.0)
    drivetrain_ratio: float = Field(gt=1.0, lt=30.0)   # motor rpm / wheel rpm
    drivetrain_efficiency: float = Field(gt=0.5, le=1.0)
    rotating_inertia_kgm2: float = Field(ge=0.0, lt=1.0)  # rotor, at motor shaft

    @property
    def total_mass_kg(self) -> float:
        return self.vehicle_mass_kg + self.rider_mass_kg

    @property
    def effective_mass_kg(self) -> float:
        """Total mass plus rotating inertia as seen at the wheel."""
        j_wheel = self.rotating_inertia_kgm2 * self.drivetrain_ratio ** 2
        return self.total_mass_kg + j_wheel / self.wheel_radius_m ** 2


class MotorParams(_Frozen):
    peak_torque_nm: float = Field(gt=1, lt=500)
    peak_power_w: float = Field(gt=500, lt=100_000)
    max_rpm: float = Field(gt=500, lt=30_000)
    efficiency: float = Field(gt=0.5, le=1.0)

    @property
    def base_rpm(self) -> float:
        """Speed where constant torque meets constant power."""
        omega_base = self.peak_power_w / self.peak_torque_nm
        return omega_base * 60.0 / (2.0 * math.pi)

    @model_validator(mode="after")
    def _check_speed_range(self) -> "MotorParams":
        if self.max_rpm <= self.base_rpm:
            raise ValueError("max_rpm must exceed the base speed (power/torque)")
        return self


class BatteryParams(_Frozen):
    energy_kwh: float = Field(gt=0.2, lt=50)
    nominal_voltage_v: float = Field(gt=12, lt=500)
    internal_resistance_ohm: float = Field(gt=0, lt=1)
    min_voltage_v: float = Field(gt=5, lt=500)
    initial_soc: float = Field(gt=0, le=1)

    @property
    def capacity_ah(self) -> float:
        return self.energy_kwh * 1000.0 / self.nominal_voltage_v

    @model_validator(mode="after")
    def _check_voltages(self) -> "BatteryParams":
        if self.min_voltage_v >= self.nominal_voltage_v:
            raise ValueError("min_voltage_v must be below nominal_voltage_v")
        return self


class ControllerParams(_Frozen):
    """The knobs the throttle-feel hypothesis sweeps."""
    latency_s: float = Field(ge=0, lt=1)
    torque_ramp_nm_per_s: float = Field(gt=0)
    filter_tau_s: float = Field(ge=0, lt=1)
    throttle_map_exponent: float = Field(gt=0.2, lt=4)


class RiderBodyParams(_Frozen):
    """Rider upper body as an inverted pendulum pivoting at the hips.

    The pelvis is fixed to the seat and the feet to the floorboard; the torso,
    head and arms (one lumped mass) lean back when the scooter accelerates and
    are held up by a torsional spring-damper (trunk muscles, hands on the bars).
    The spring is specified by its natural frequency and damping ratio, which is
    easier to reason about than a stiffness in Nm/rad.
    """
    torso_mass_fraction: float = Field(gt=0.2, lt=0.8)   # share of rider mass above the hips
    torso_com_height_m: float = Field(gt=0.1, lt=0.6)    # hips to lumped centre of mass
    head_height_m: float = Field(gt=0.2, lt=0.9)         # hips to head
    natural_freq_hz: float = Field(gt=0.3, lt=8.0)       # of the torso on its spring-damper
    damping_ratio: float = Field(ge=0.0, lt=2.0)

    @model_validator(mode="after")
    def _check_geometry(self) -> "RiderBodyParams":
        if self.head_height_m <= self.torso_com_height_m:
            raise ValueError("head_height_m must be above torso_com_height_m")
        return self


class Claimed(_Frozen):
    """Manufacturer claims, used as validation targets (not as inputs)."""
    top_speed_kmph: Optional[float] = None
    accel_0_40_s: Optional[float] = None
    range_km_idc: Optional[float] = None


class SimConfig(_Frozen):
    meta: Meta
    dt_s: float = Field(gt=0, le=0.1)
    vehicle: VehicleParams
    motor: MotorParams
    battery: BatteryParams
    controller: ControllerParams
    rider_body: RiderBodyParams
    claimed: Claimed = Claimed()

    @model_validator(mode="after")
    def _check_rider_stable(self) -> "SimConfig":
        # Explicit integration of the torso needs omega_n * dt well below 1.
        if 2 * math.pi * self.rider_body.natural_freq_hz * self.dt_s > 0.5:
            raise ValueError("rider natural frequency too high for this time step")
        return self

    def fingerprint(self) -> str:
        """Short stable hash of the full config, to tag runs in the database."""
        blob = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


# ---------------------------------------------------------------- loading ---

def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _load_raw(path: Path, _seen: tuple = ()) -> dict:
    path = path.resolve()
    if path in _seen:
        raise ValueError(f"Circular 'extends' at {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    parent = raw.pop("extends", None)
    if parent:
        raw = _deep_merge(_load_raw(path.parent / parent, _seen + (path,)), raw)
    return raw


def _set_dotted(d: dict, dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    for p in parents:
        d = d.setdefault(p, {})
    d[leaf] = value


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> SimConfig:
    """Load a vehicle YAML (following 'extends'), apply dotted overrides, validate.

    Example: load_config("configs/ather_450x_2p9.yaml", {"controller.latency_s": 0.1})
    """
    raw = _load_raw(Path(path))
    for key, value in (overrides or {}).items():
        _set_dotted(raw, key, value)
    return SimConfig.model_validate(raw)
