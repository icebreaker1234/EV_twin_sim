-- EV digital twin: database schema (Postgres, with TimescaleDB when available).
-- Safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS ev;

-- TimescaleDB is optional: on plain Postgres this is skipped and everything
-- still works (telemetry is just a normal table).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'timescaledb not available (%), using plain tables', SQLERRM;
END $$;

-- One row per simulation run: identity, controller knobs, and summary metrics.
CREATE TABLE IF NOT EXISTS ev.runs (
    run_id            text PRIMARY KEY,
    created_at        timestamptz      NOT NULL DEFAULT now(),
    vehicle           text             NOT NULL,   -- e.g. 'Ather 450X'
    variant           text             NOT NULL,   -- e.g. '2.9 kWh'
    vehicle_name      text             NOT NULL,   -- 'Ather 450X 2.9 kWh'
    scenario          text             NOT NULL,
    ctrl              text             NOT NULL,   -- readable controller settings
    label             text             NOT NULL,
    config_fp         text             NOT NULL,
    config            jsonb            NOT NULL,
    scenario_params   jsonb            NOT NULL DEFAULT '{}',
    -- controller knobs (denormalised so sweeps can be plotted directly)
    latency_s         double precision,
    ramp_nm_per_s     double precision,
    filter_tau_s      double precision,
    map_exponent      double precision,
    -- summary metrics
    duration_s        double precision,
    distance_m        double precision,
    top_speed_kmph    double precision,
    energy_wh         double precision,
    wh_per_km         double precision,
    soc_start         double precision,
    soc_end           double precision,
    peak_accel_ms2    double precision,
    peak_jerk_ms3     double precision,
    p95_jerk_ms3      double precision,
    rms_jerk_ms3      double precision,
    peak_batt_power_w double precision,
    limited_fraction  double precision,
    t_0_40_s          double precision,
    peak_lean_deg     double precision,
    head_p95_jerk_ms3 double precision,
    head_rms_jerk_ms3 double precision,
    jerk_gain         double precision
);

-- Upgrade databases created before the rider model existed.
ALTER TABLE ev.runs
    ADD COLUMN IF NOT EXISTS peak_lean_deg     double precision,
    ADD COLUMN IF NOT EXISTS head_p95_jerk_ms3 double precision,
    ADD COLUMN IF NOT EXISTS head_rms_jerk_ms3 double precision,
    ADD COLUMN IF NOT EXISTS jerk_gain         double precision;

CREATE INDEX IF NOT EXISTS runs_scenario_idx ON ev.runs (scenario, vehicle_name);

-- High-rate telemetry. ts = run start + t_s (real time, for partitioning and
-- future live streaming); t_s is the time since the start of the scenario and
-- is what the dashboards use to overlay runs.
CREATE TABLE IF NOT EXISTS ev.telemetry (
    run_id          text             NOT NULL REFERENCES ev.runs (run_id) ON DELETE CASCADE,
    ts              timestamptz      NOT NULL,
    t_s             double precision NOT NULL,
    target_ms       double precision,
    speed_ms        double precision,
    accel_ms2       double precision,
    jerk_ms3        double precision,
    distance_m      double precision,
    pedal           double precision,
    brake           double precision,
    torque_cmd_nm   double precision,
    torque_nm       double precision,
    motor_rpm       double precision,
    batt_power_w    double precision,
    batt_voltage_v  double precision,
    batt_current_a  double precision,
    soc             double precision,
    batt_loss_w     double precision,
    batt_limited    double precision,
    torso_lean_deg  double precision,
    head_accel_ms2  double precision,
    head_jerk_ms3   double precision,
    PRIMARY KEY (run_id, ts)
);

ALTER TABLE ev.telemetry
    ADD COLUMN IF NOT EXISTS torso_lean_deg double precision,
    ADD COLUMN IF NOT EXISTS head_accel_ms2 double precision,
    ADD COLUMN IF NOT EXISTS head_jerk_ms3  double precision;

CREATE INDEX IF NOT EXISTS telemetry_run_t_idx ON ev.telemetry (run_id, t_s);

DO $$
BEGIN
    PERFORM create_hypertable('ev.telemetry', 'ts', if_not_exists => TRUE,
                              migrate_data => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'hypertable not created (%), telemetry stays a plain table', SQLERRM;
END $$;
