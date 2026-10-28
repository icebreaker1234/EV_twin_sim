"""Summary metrics from a telemetry DataFrame (one row per simulation step)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_metrics(df: pd.DataFrame, dt_s: float) -> dict:
    """Run-level numbers: distance, energy, jerk (comfort) and launch performance.

    Jerk statistics ignore the instant of stopping (see _jerk_mask), where a 1-D
    model produces an unphysical spike, but keep the launch from standstill.
    """
    speed = df["speed_ms"].to_numpy()
    power = df["batt_power_w"].to_numpy()
    jerk = df["jerk_ms3"].to_numpy()
    moving = _jerk_mask(df)

    distance_m = float(df["distance_m"].iloc[-1])
    energy_wh = float(power.sum() * dt_s / 3600.0)
    j = np.abs(jerk[moving]) if moving.any() else np.zeros(1)
    hj = np.abs(df["head_jerk_ms3"].to_numpy()[moving]) if moving.any() else np.zeros(1)
    rms, head_rms = float(np.sqrt(np.mean(j ** 2))), float(np.sqrt(np.mean(hj ** 2)))

    metrics = {
        "duration_s": float(len(df) * dt_s),
        "distance_m": distance_m,
        "top_speed_kmph": float(speed.max() * 3.6),
        "energy_wh": energy_wh,
        "wh_per_km": energy_wh / (distance_m / 1000.0) if distance_m > 50 else None,
        "soc_start": float(df["soc"].iloc[0]),
        "soc_end": float(df["soc"].iloc[-1]),
        "peak_accel_ms2": float(df["accel_ms2"].max()),
        "peak_jerk_ms3": float(j.max()),
        "p95_jerk_ms3": float(np.percentile(j, 95)),
        "rms_jerk_ms3": rms,
        "peak_lean_deg": float(df["torso_lean_deg"].abs().max()),
        "head_p95_jerk_ms3": float(np.percentile(hj, 95)),
        "head_rms_jerk_ms3": head_rms,
        # >1: the body amplifies the scooter's jerk; <1: it filters it.
        "jerk_gain": head_rms / rms if rms > 1e-9 else None,
        "peak_batt_power_w": float(power.max()),
        "limited_fraction": float(df["batt_limited"].mean()),
        "t_0_40_s": _time_to_speed(df, 40.0 / 3.6),
    }
    return metrics


def _jerk_mask(df: pd.DataFrame) -> np.ndarray:
    """Samples used for every jerk statistic (scooter and head share one mask).

    Drops near-standstill samples only when the rider is not asking for power
    (braking or pedal released): that is the stop, where speed is clamped at zero.
    A launch (pedal pressed at zero speed) is kept; it is the most interesting part.
    """
    stopped = df["speed_ms"].to_numpy() <= 0.3
    no_power = (df["brake"].to_numpy() > 0.0) | (df["pedal"].to_numpy() <= 0.01)
    return ~(stopped & no_power)


def _time_to_speed(df: pd.DataFrame, target_ms: float) -> float | None:
    """Seconds from first pedal input until speed reaches target_ms."""
    pressed = df.index[df["pedal"] > 0.01]
    reached = df.index[df["speed_ms"] >= target_ms]
    if len(pressed) == 0 or len(reached) == 0 or reached[0] < pressed[0]:
        return None
    return float(df["t_s"].iloc[reached[0]] - df["t_s"].iloc[pressed[0]])
