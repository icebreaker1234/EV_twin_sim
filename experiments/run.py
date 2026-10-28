"""Command-line runner.

Examples:
    python -m experiments.run ather_450x_2p9 urban_stopgo
    python -m experiments.run ola_s1_pro_4kwh throttle_step \\
        --set controller.latency_s=0.15 --scen level=0.7 --db
"""
from __future__ import annotations

import argparse
import ast

from experiments.runner import run_one


def _kv(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        key, _, raw = item.partition("=")
        try:
            out[key] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            out[key] = raw
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("vehicle", help="config name (e.g. ather_450x_2p9) or YAML path")
    ap.add_argument("scenario", help="wot_launch | throttle_step | urban_stopgo | mixed_cycle")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="config override, e.g. controller.latency_s=0.15")
    ap.add_argument("--scen", action="append", metavar="KEY=VALUE",
                    help="scenario argument, e.g. level=0.7")
    ap.add_argument("--db", action="store_true", help="store the run in the database")
    ap.add_argument("--log-hz", type=float, default=20.0, help="telemetry rate stored in DB")
    args = ap.parse_args()

    result = run_one(args.vehicle, args.scenario, _kv(args.set), _kv(args.scen))
    print(f"{result.config.meta.name} {result.config.meta.variant} | {args.scenario}")
    for key, val in result.metrics.items():
        print(f"  {key:22s} {val if val is None else round(val, 3)}")

    if args.db:
        from pipeline import loader
        conn = loader.connect()
        loader.init_schema(conn)
        print("stored as", loader.save_run(conn, result, args.log_hz))
        conn.close()


if __name__ == "__main__":
    main()
