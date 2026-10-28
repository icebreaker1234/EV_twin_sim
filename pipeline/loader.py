"""Write simulation results to Postgres/TimescaleDB.

Connection comes from the EV_DB_DSN environment variable, defaulting to the
docker-compose database on localhost.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, execute_values

from sim.simulate import SimResult

DEFAULT_DSN = "postgresql://ev:ev@localhost:5442/ev"
SCHEMA_FILE = Path(__file__).with_name("schema.sql")

TELEMETRY_COLS = (
    "target_ms", "speed_ms", "accel_ms2", "jerk_ms3", "distance_m", "pedal", "brake",
    "torque_cmd_nm", "torque_nm", "motor_rpm", "batt_power_w", "batt_voltage_v",
    "batt_current_a", "soc", "batt_loss_w", "batt_limited",
    "torso_lean_deg", "head_accel_ms2", "head_jerk_ms3",
)

METRIC_COLS = (
    "duration_s", "distance_m", "top_speed_kmph", "energy_wh", "wh_per_km", "soc_start",
    "soc_end", "peak_accel_ms2", "peak_jerk_ms3", "p95_jerk_ms3", "rms_jerk_ms3",
    "peak_batt_power_w", "limited_fraction", "t_0_40_s",
    "peak_lean_deg", "head_p95_jerk_ms3", "head_rms_jerk_ms3", "jerk_gain",
)


def connect(dsn: str | None = None):
    return psycopg2.connect(dsn or os.environ.get("EV_DB_DSN", DEFAULT_DSN))


def init_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_FILE.read_text())
    conn.commit()


def ctrl_label(cfg) -> str:
    c = cfg.controller
    return (f"lat {c.latency_s * 1000:.0f}ms | ramp {c.torque_ramp_nm_per_s:.0f} Nm/s | "
            f"tau {c.filter_tau_s * 1000:.0f}ms | map^{c.throttle_map_exponent:g}")


def make_run_id(result: SimResult) -> str:
    """Deterministic id: re-running the same config + scenario replaces its data."""
    scen = result.scenario
    blob = json.dumps({"fp": result.config.fingerprint(), "scenario": scen.name,
                       "params": scen.params}, sort_keys=True, default=str)
    return f"{scen.name}-{hashlib.sha256(blob.encode()).hexdigest()[:10]}"


def _clean(x):
    """NaN/inf -> None so Postgres stores NULL; values this close to zero -> 0.0.

    Filters and the torso spring decay towards zero for ever and can reach
    denormal numbers (1e-322). Postgres stores them but raises "underflow" as
    soon as a dashboard query multiplies them, so they are flushed to zero.
    """
    if x is None:
        return None
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return 0.0 if abs(x) < 1e-30 else x


def save_run(conn, result: SimResult, log_hz: float = 20.0) -> str:
    """Insert (or replace) one run and its telemetry. Returns the run_id."""
    cfg, scen = result.config, result.scenario
    run_id = make_run_id(result)
    created = datetime.now(timezone.utc)
    m = result.metrics
    vehicle_name = f"{cfg.meta.name} {cfg.meta.variant}"
    ctrl = ctrl_label(cfg)

    step = max(1, int(round(1.0 / (log_hz * cfg.dt_s))))
    df = result.telemetry.iloc[::step]

    run_cols = ["run_id", "created_at", "vehicle", "variant", "vehicle_name", "scenario",
                "ctrl", "label", "config_fp", "config", "scenario_params", "latency_s",
                "ramp_nm_per_s", "filter_tau_s", "map_exponent", *METRIC_COLS]
    run_vals = [run_id, created, cfg.meta.name, cfg.meta.variant, vehicle_name, scen.name,
                ctrl, f"{vehicle_name} | {scen.name} | {ctrl}", cfg.fingerprint(),
                Json(cfg.model_dump()), Json(scen.params, dumps=lambda o: json.dumps(o, default=str)),
                cfg.controller.latency_s, cfg.controller.torque_ramp_nm_per_s,
                cfg.controller.filter_tau_s, cfg.controller.throttle_map_exponent,
                *[_clean(m.get(c)) for c in METRIC_COLS]]

    rows = [
        (run_id, created + timedelta(seconds=float(t)), float(t),
         *[_clean(v) for v in vals])
        for t, *vals in df[["t_s", *TELEMETRY_COLS]].itertuples(index=False, name=None)
    ]

    with conn.cursor() as cur:
        cur.execute("DELETE FROM ev.runs WHERE run_id = %s", (run_id,))
        cur.execute(
            f"INSERT INTO ev.runs ({', '.join(run_cols)}) VALUES ({', '.join(['%s'] * len(run_cols))})",
            run_vals,
        )
        execute_values(
            cur,
            f"INSERT INTO ev.telemetry (run_id, ts, t_s, {', '.join(TELEMETRY_COLS)}) VALUES %s",
            rows, page_size=5000,
        )
    conn.commit()
    return run_id
