"""Battery pack model: open-circuit voltage curve plus one series resistance.

Equivalent circuit: V_terminal = V_oc(SoC) - R * I, with I > 0 on discharge.
SoC is tracked by coulomb counting. The pack is asked for a *power*; the model
solves for the current that delivers it given the voltage sag, and limits the
request when the pack cannot deliver it (maximum power transfer, or the
minimum-voltage cutoff).

The V_oc curve is a generic NMC-style per-cell curve, scaled so that a cell
nominal of 3.6 V maps to the config's pack nominal voltage. It is an estimate,
not a measured curve for any specific pack. A first-order RC pair (transient
sag and recovery) can be added to `step` later without changing callers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from sim.config import BatteryParams

# Generic NMC per-cell open-circuit voltage vs state of charge.
_SOC_PTS = np.array([0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0])
_CELL_V_PTS = np.array([3.00, 3.30, 3.45, 3.58, 3.70, 3.90, 4.05, 4.20])
_CELL_NOMINAL_V = 3.6


@dataclass(frozen=True)
class BatteryStep:
    """Result of one battery step."""
    power_w: float        # terminal power actually delivered (+) / absorbed (-)
    current_a: float      # + discharge, - charge
    voltage_v: float      # terminal voltage under load
    soc: float
    loss_w: float         # I^2 * R heat
    limited: bool         # True if the request was cut back


class Battery:
    def __init__(self, params: BatteryParams):
        self.p = params
        self.soc = params.initial_soc

    def reset(self, soc: float | None = None) -> None:
        self.soc = self.p.initial_soc if soc is None else soc

    def open_circuit_voltage(self, soc: float | None = None) -> float:
        s = self.soc if soc is None else soc
        cell_v = float(np.interp(s, _SOC_PTS, _CELL_V_PTS))
        return cell_v / _CELL_NOMINAL_V * self.p.nominal_voltage_v

    def max_discharge_current(self, voc: float) -> float:
        """Current at which terminal voltage just reaches the cutoff."""
        return max(0.0, (voc - self.p.min_voltage_v) / self.p.internal_resistance_ohm)

    def max_discharge_power(self) -> float:
        """Largest terminal power available now (W), cutoff and physics included."""
        voc, r = self.open_circuit_voltage(), self.p.internal_resistance_ohm
        i = min(self.max_discharge_current(voc), voc / (2.0 * r))
        return (voc - r * i) * i

    def step(self, power_w: float, dt_s: float) -> BatteryStep:
        """Deliver (+) or absorb (-) terminal power for one time step."""
        voc, r = self.open_circuit_voltage(), self.p.internal_resistance_ohm
        limited = False

        if power_w >= 0.0:
            if power_w > 0.0 and self.soc <= 0.0:    # empty pack cannot discharge
                return BatteryStep(0.0, 0.0, voc, 0.0, 0.0, True)
            p_cap = self.max_discharge_power()
            if power_w > p_cap:
                power_w, limited = p_cap, True
            i = (voc - math.sqrt(max(voc * voc - 4.0 * r * power_w, 0.0))) / (2.0 * r)
        else:
            if self.soc >= 1.0:                      # full pack cannot accept regen
                return BatteryStep(0.0, 0.0, voc, self.soc, 0.0, True)
            i = (voc - math.sqrt(voc * voc - 4.0 * r * power_w)) / (2.0 * r)  # i < 0

        v = voc - r * i
        self.soc = min(1.0, max(0.0, self.soc - i * dt_s / (3600.0 * self.p.capacity_ah)))
        return BatteryStep(v * i, i, v, self.soc, r * i * i, limited)
