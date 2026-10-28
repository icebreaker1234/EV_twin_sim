"""Run one simulation from a config path + scenario name + overrides."""
from __future__ import annotations

from pathlib import Path

from sim.config import load_config
from sim.scenarios import build
from sim.simulate import SimResult, simulate

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"

VEHICLES = [
    "ather_450x_2p9",
    "ather_450x_3p7",
    "ola_s1_pro_4kwh",
    "ola_s1_pro_plus_5p2kwh",
]


def config_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p
    candidate = CONFIG_DIR / f"{name_or_path}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"No config '{name_or_path}' (looked in {CONFIG_DIR})")


def run_one(vehicle: str, scenario: str, overrides: dict | None = None,
            scenario_kwargs: dict | None = None) -> SimResult:
    cfg = load_config(config_path(vehicle), overrides)
    scen = build(scenario, cfg.dt_s, **(scenario_kwargs or {}))
    return simulate(cfg, scen)
