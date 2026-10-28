"""Simulation loop: wires rider, controller, motor, battery and vehicle together."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from sim.battery import Battery
from sim.config import SimConfig
from sim.controller import ThrottleController
from sim.driver import PIDriver
from sim.metrics import compute_metrics
from sim.motor import RPM_TO_RADS, Motor
from sim.rider import Rider
from sim.scenarios import Scenario
from sim.vehicle import Vehicle


@dataclass
class SimResult:
    config: SimConfig
    scenario: Scenario
    telemetry: pd.DataFrame
    metrics: dict


def simulate(cfg: SimConfig, scenario: Scenario) -> SimResult:
    dt = cfg.dt_s
    if abs(scenario.dt_s - dt) > 1e-12:
        raise ValueError(f"Scenario dt ({scenario.dt_s}) does not match config dt ({dt})")

    motor = Motor(cfg.motor)
    battery = Battery(cfg.battery)
    vehicle = Vehicle(cfg.vehicle)
    ctrl = ThrottleController(cfg.controller, motor, dt)
    driver = PIDriver()
    rider = Rider(cfg.rider_body, cfg.vehicle.rider_mass_kg, cfg.vehicle.gravity)

    n = scenario.n
    cols = ("target_ms", "speed_ms", "accel_ms2", "distance_m", "pedal", "brake",
            "torque_cmd_nm", "torque_nm", "motor_rpm", "batt_power_w", "batt_voltage_v",
            "batt_current_a", "soc", "batt_loss_w", "batt_limited",
            "torso_lean_deg", "head_accel_ms2")
    rec = {c: np.zeros(n) for c in cols}

    for k in range(n):
        v = vehicle.speed
        if scenario.kind == "speed":
            target = scenario.target_speed[k]
            pedal, brake = driver.step(target, v, dt)
        else:
            target = float("nan")
            pedal, brake = scenario.pedal[k], scenario.brake[k]
        grade = scenario.grade[k] if len(scenario.grade) else 0.0

        omega = vehicle.motor_omega()
        torque_cmd = float(motor.clip_torque(ctrl.step(pedal, omega), omega))

        p_req = float(motor.electrical_power(torque_cmd, omega))
        bs = battery.step(p_req, dt)
        torque = torque_cmd
        if p_req > 1e-6 and bs.power_w < p_req:       # battery could not deliver it all
            torque = torque_cmd * bs.power_w / p_req

        accel = vehicle.step(torque, brake, dt, grade)
        body = rider.step(accel, dt)

        rec["target_ms"][k], rec["speed_ms"][k] = target, vehicle.speed
        rec["accel_ms2"][k], rec["distance_m"][k] = accel, vehicle.distance
        rec["pedal"][k], rec["brake"][k] = pedal, brake
        rec["torque_cmd_nm"][k], rec["torque_nm"][k] = torque_cmd, torque
        rec["motor_rpm"][k] = omega / RPM_TO_RADS
        rec["batt_power_w"][k], rec["batt_voltage_v"][k] = bs.power_w, bs.voltage_v
        rec["batt_current_a"][k], rec["soc"][k] = bs.current_a, bs.soc
        rec["batt_loss_w"][k], rec["batt_limited"][k] = bs.loss_w, float(bs.limited)
        rec["torso_lean_deg"][k] = math.degrees(body.lean_rad)
        rec["head_accel_ms2"][k] = body.head_accel_ms2

    df = pd.DataFrame(rec)
    df.insert(0, "t_s", scenario.time_s)
    df["jerk_ms3"] = np.gradient(df["accel_ms2"].to_numpy(), dt)
    df["head_jerk_ms3"] = np.gradient(df["head_accel_ms2"].to_numpy(), dt)
    return SimResult(cfg, scenario, df, compute_metrics(df, dt))
