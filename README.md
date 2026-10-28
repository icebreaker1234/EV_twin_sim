# EV Digital Twin

Physics simulation of electric scooters (Ather 450X 2.9 / 3.7 kWh, Ola S1 Pro 4 kWh / Plus 5.2 kWh),
a throttle-to-torque controller study, a Postgres/TimescaleDB telemetry store, and Grafana dashboards.

```
configs/      vehicle YAMLs (published specs; ESTIMATED fields flagged)
sim/          config, motor, battery, controller, vehicle, rider, driver, scenarios, simulate, metrics
experiments/  runner, CLI (run.py), demo seeding (seed_demo.py)
pipeline/     schema.sql, loader.py
grafana/      provisioning, build_dashboard.py, dashboards/ev_overview.json
tests/        pytest suite
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
docker compose up -d
python -m experiments.seed_demo
open http://localhost:3030
```

`pytest -q` runs the simulator tests (no database needed). `docker compose up -d` starts
TimescaleDB on :5442 and Grafana on :3030. `seed_demo` stores about 70 runs across the four
scooters. Grafana login is admin / admin. (Comments are kept out of the code block on purpose:
zsh does not treat `#` as a comment when pasted into an interactive shell.)

One run from the command line:

```bash
python -m experiments.run ather_450x_2p9 throttle_step \
    --set controller.latency_s=0.15 --scen level=0.7 --db
```

Database tests (use a scratch database, they drop the `ev` schema):

```bash
EV_TEST_DSN=postgresql://ev:ev@localhost:5442/ev_test pytest tests/test_pipeline.py
```

## How it fits together

pedal -> **controller** (map, filter, latency, ramp limit) -> **motor** (torque envelope)
-> **battery** (power -> current, voltage sag, limits) -> **vehicle** (longitudinal dynamics)
-> **rider** (torso on a spring-damper: lean angle, head acceleration and jerk)
-> telemetry -> `ev.runs` / `ev.telemetry` -> Grafana.

Runs are stored with `t_s` (seconds since start) and shown on a fixed 2000-01-01 time axis so
different vehicles and settings overlay. Run ids are deterministic, so re-running replaces.

## Known limits (base version)

* Parameters marked ESTIMATED in `configs/` are not calibrated. Run `wot_launch` and compare with
  the `claimed:` values; the validation phase tunes them.
* Drive cycles are synthetic, not WMTC / Indian Driving Cycle.
* Rider body (`rider_body:` in `configs/base.yaml`) is one lumped torso pivoting at the hips, driven
  by the scooter's acceleration, with its parameters ESTIMATED from biomechanics ranges. One-way
  coupling: the torso's reaction on the scooter is ignored. Not a crash-test dummy.
* Jerk statistics (scooter and head) skip only the final stop (near zero speed with brake on or
  pedal released); the launch from standstill is included.
* An existing database picks up the new rider columns when `seed_demo` or `run.py --db` runs
  (`init_schema` adds them). Re-seed afterwards: run ids changed because the config gained fields.
* 1-D longitudinal model: no pitch, tyre slip or load transfer. Flat motor efficiency. Fixed
  battery resistance, no RC transient, no temperature. Regen is not used yet.
* Grafana dashboard JSON was generated and every query verified against Postgres, but the
  dashboard has not been opened in Grafana itself yet.
