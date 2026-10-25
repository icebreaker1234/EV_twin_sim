from pathlib import Path

import pytest
from pydantic import ValidationError

from sim.config import load_config

CONFIGS = sorted(p for p in Path("configs").glob("*.yaml") if p.name != "base.yaml")
ATHER = "configs/ather_450x_2p9.yaml"


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_every_config_loads(path):
    cfg = load_config(path)
    assert cfg.vehicle.effective_mass_kg > cfg.vehicle.total_mass_kg
    assert cfg.motor.max_rpm > cfg.motor.base_rpm


def test_override_applies():
    cfg = load_config(ATHER, {"controller.latency_s": 0.12})
    assert cfg.controller.latency_s == 0.12


def test_variants_differ_only_where_intended():
    a = load_config("configs/ather_450x_2p9.yaml")
    b = load_config("configs/ather_450x_3p7.yaml")
    assert a.motor == b.motor and a.battery.energy_kwh != b.battery.energy_kwh
    assert a.fingerprint() != b.fingerprint()


def test_typo_rejected():
    with pytest.raises(ValidationError):
        load_config(ATHER, {"controller.latency": 0.1})


def test_out_of_range_rejected():
    with pytest.raises(ValidationError):
        load_config(ATHER, {"vehicle.wheel_radius_m": 2.0})
