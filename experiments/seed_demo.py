"""Fill the database with a demo set of runs for all four scooters.

    python -m experiments.seed_demo

Per scooter: baseline launch and drive cycles, a tip-in sweep over controller
latency and torque ramp (the throttle-feel study), and the urban cycle at two
latencies. Runs are idempotent: re-running replaces the same run ids.
"""
from __future__ import annotations

import itertools
import time

from experiments.runner import VEHICLES, run_one
from pipeline import loader

LATENCIES_S = [0.02, 0.05, 0.15, 0.30]
RAMPS_NM_S = [150.0, 400.0, 1500.0]


def jobs():
    for v in VEHICLES:
        yield v, "wot_launch", {}, {}
        yield v, "urban_stopgo", {}, {}
        yield v, "mixed_cycle", {}, {}
        for lat, ramp in itertools.product(LATENCIES_S, RAMPS_NM_S):
            yield (v, "throttle_step",
                   {"controller.latency_s": lat, "controller.torque_ramp_nm_per_s": ramp},
                   {"level": 0.7})
        for lat in (0.02, 0.20):          # baseline latency is 0.05, already stored
            yield v, "urban_stopgo", {"controller.latency_s": lat}, {}


def main() -> None:
    conn = loader.connect()
    loader.init_schema(conn)
    t0, n = time.time(), 0
    for vehicle, scenario, overrides, scen_kwargs in jobs():
        result = run_one(vehicle, scenario, overrides, scen_kwargs)
        loader.save_run(conn, result)
        n += 1
    conn.close()
    print(f"Stored {n} run slots in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
