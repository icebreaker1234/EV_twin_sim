"""Rider body model: checked against closed-form second-order-system results."""
import math

import numpy as np
import pytest

from sim.config import load_config
from sim.rider import Rider
from sim.scenarios import build as build_scenario
from sim.simulate import simulate

DT = 0.001          # fine step so the numerical error is far below the test tolerances


@pytest.fixture
def cfg():
    return load_config("configs/ather_450x_2p9.yaml")


def make_rider(cfg, **over):
    p = cfg.rider_body.model_copy(update=over)
    return Rider(p, cfg.vehicle.rider_mass_kg, cfg.vehicle.gravity), p


def test_no_acceleration_no_lean(cfg):
    r, _ = make_rider(cfg)
    for _ in range(1000):
        s = r.step(0.0, DT)
    assert s.lean_rad == 0.0 and s.head_accel_ms2 == 0.0


def test_steady_state_lean_matches_a_over_L_omega_squared(cfg):
    """Small-angle step: theta_ss = a / (L * omega_n^2) (gravity is folded into k)."""
    r, p = make_rider(cfg, damping_ratio=0.7)
    a = 0.2
    for _ in range(int(10 / DT)):
        s = r.step(a, DT)
    expected = a / (p.torso_com_height_m * (2 * math.pi * p.natural_freq_hz) ** 2)
    assert s.lean_rad == pytest.approx(expected, rel=0.01)


def test_overshoot_matches_second_order_theory(cfg):
    zeta = 0.3
    r, p = make_rider(cfg, damping_ratio=zeta)
    a = 0.2
    peak = 0.0
    for _ in range(int(3 / DT)):
        peak = max(peak, r.step(a, DT).lean_rad)
    ss = a / (p.torso_com_height_m * (2 * math.pi * p.natural_freq_hz) ** 2)
    expected_overshoot = math.exp(-math.pi * zeta / math.sqrt(1 - zeta ** 2))
    assert peak / ss - 1 == pytest.approx(expected_overshoot, rel=0.03)


def test_free_oscillation_frequency(cfg):
    """Undamped, released from a small angle: the period is 1 / natural_freq."""
    r, p = make_rider(cfg, damping_ratio=0.0)
    r.reset(theta=0.01)
    crossings, prev = [], r.theta
    for k in range(int(5 / DT)):
        s = r.step(0.0, DT)
        if prev > 0 >= s.lean_rad:                  # downward zero crossings
            crossings.append(k * DT)
        prev = s.lean_rad
    period = np.mean(np.diff(crossings))
    assert period == pytest.approx(1 / p.natural_freq_hz, rel=0.01)


def test_damped_oscillation_decays(cfg):
    r, _ = make_rider(cfg, damping_ratio=0.3)
    r.reset(theta=0.05)
    peak_late = 0.0
    for k in range(int(6 / DT)):
        s = r.step(0.0, DT)
        if k > int(5 / DT):
            peak_late = max(peak_late, abs(s.lean_rad))
    assert peak_late < 0.001


def test_head_acceleration_equals_scooter_acceleration_when_rigid(cfg):
    """A very stiff torso moves with the scooter, so the head feels the scooter's acceleration."""
    r, _ = make_rider(cfg, natural_freq_hz=8.0, damping_ratio=1.0)
    a = 3.0
    for _ in range(int(3 / DT)):
        s = r.step(a, DT)
    assert s.head_accel_ms2 == pytest.approx(a, rel=0.01)


def test_rider_model_is_stable_at_simulation_step(cfg):
    """At the real 100 Hz step the torso stays bounded under a harsh input."""
    r, _ = make_rider(cfg)
    for k in range(5000):
        s = r.step(4.0 if (k // 50) % 2 == 0 else -4.0, cfg.dt_s)   # 1 Hz square wave
        assert abs(s.lean_rad) < 1.0


def test_config_rejects_unstable_rider_frequency():
    with pytest.raises(ValueError, match="too high"):
        load_config("configs/ather_450x_2p9.yaml", {"dt_s": 0.02, "rider_body.natural_freq_hz": 5.0})


def test_head_must_be_above_torso_com():
    with pytest.raises(ValueError):
        load_config("configs/ather_450x_2p9.yaml", {"rider_body.head_height_m": 0.2})


def test_rider_params_change_the_fingerprint(cfg):
    other = load_config("configs/ather_450x_2p9.yaml", {"rider_body.damping_ratio": 0.5})
    assert other.fingerprint() != cfg.fingerprint()


# ---------------------------------------------------- inside the simulation ---

def _run(cfg_over, scenario="throttle_step", **kw):
    cfg = load_config("configs/ather_450x_2p9.yaml", cfg_over)
    return simulate(cfg, build_scenario(scenario, cfg.dt_s, **kw))


def test_simulation_records_rider_columns():
    res = _run({}, level=0.7, duration_s=8.0)
    for c in ("torso_lean_deg", "head_accel_ms2", "head_jerk_ms3"):
        assert c in res.telemetry and np.isfinite(res.telemetry[c]).all()
    m = res.metrics
    assert m["peak_lean_deg"] > 1.0                      # leans back when launching
    assert m["jerk_gain"] is not None and m["jerk_gain"] > 0


def test_lean_is_backward_during_acceleration():
    res = _run({}, level=0.7, duration_s=8.0)
    i = int(res.telemetry["accel_ms2"].idxmax())
    assert res.telemetry["torso_lean_deg"].iloc[i] > 0


def test_stiffer_torso_leans_less():
    soft = _run({"rider_body.natural_freq_hz": 1.0}, level=0.7, duration_s=8.0)
    stiff = _run({"rider_body.natural_freq_hz": 3.0}, level=0.7, duration_s=8.0)
    assert soft.metrics["peak_lean_deg"] > 3 * stiff.metrics["peak_lean_deg"]


def test_sharper_torque_ramp_excites_the_body_more():
    """Same final throttle, faster ramp: the torso overshoots more."""
    slow = _run({"controller.torque_ramp_nm_per_s": 100.0}, level=0.7, duration_s=8.0)
    fast = _run({"controller.torque_ramp_nm_per_s": 3000.0}, level=0.7, duration_s=8.0)
    assert fast.metrics["peak_lean_deg"] > slow.metrics["peak_lean_deg"]
