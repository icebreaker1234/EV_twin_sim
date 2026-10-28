import numpy as np
import pytest

from sim.config import load_config
from sim.controller import ThrottleController
from sim.motor import Motor
from sim.scenarios import build
from sim.simulate import simulate
from sim.vehicle import Vehicle

CONFIGS = [
    "configs/ather_450x_2p9.yaml",
    "configs/ather_450x_3p7.yaml",
    "configs/ola_s1_pro_4kwh.yaml",
    "configs/ola_s1_pro_plus_5p2kwh.yaml",
]
ATHER = "configs/ather_450x_2p9.yaml"


def _ctrl(**over):
    cfg = load_config(ATHER, {f"controller.{k}": v for k, v in over.items()})
    return ThrottleController(cfg.controller, Motor(cfg.motor), cfg.dt_s), cfg


# ------------------------------------------------------------- controller ---

def test_latency_delays_response():
    ctrl, cfg = _ctrl(latency_s=0.10, filter_tau_s=0.0, torque_ramp_nm_per_s=1e6)
    out = [ctrl.step(1.0, 0.0) for _ in range(30)]
    first = next(i for i, x in enumerate(out) if x > 0)
    assert first == round(0.10 / cfg.dt_s)


def test_ramp_limit_respected():
    ctrl, cfg = _ctrl(latency_s=0.0, filter_tau_s=0.0, torque_ramp_nm_per_s=100.0)
    out = np.array([ctrl.step(1.0, 0.0) for _ in range(50)])
    assert np.max(np.diff(out)) <= 100.0 * cfg.dt_s + 1e-9


def test_full_throttle_reaches_available_torque():
    ctrl, cfg = _ctrl()
    for _ in range(500):
        t = ctrl.step(1.0, 0.0)
    assert t == pytest.approx(cfg.motor.peak_torque_nm)


def test_filter_smooths_a_step():
    fast, _ = _ctrl(latency_s=0.0, filter_tau_s=0.0, torque_ramp_nm_per_s=1e6)
    slow, _ = _ctrl(latency_s=0.0, filter_tau_s=0.2, torque_ramp_nm_per_s=1e6)
    assert slow.step(1.0, 0.0) < fast.step(1.0, 0.0)


def test_map_exponent_softens_low_throttle():
    lin, _ = _ctrl(throttle_map_exponent=1.0, torque_ramp_nm_per_s=1e6, latency_s=0.0)
    soft, _ = _ctrl(throttle_map_exponent=2.0, torque_ramp_nm_per_s=1e6, latency_s=0.0)
    for _ in range(500):
        a, b = lin.step(0.4, 0.0), soft.step(0.4, 0.0)
    assert b < a


# ---------------------------------------------------------------- vehicle ---

def test_vehicle_decelerates_when_coasting():
    v = Vehicle(load_config(ATHER).vehicle)
    v.speed = 15.0
    for _ in range(200):
        v.step(0.0, 0.0, 0.01)
    assert 0 < v.speed < 15.0


def test_vehicle_speed_never_negative():
    v = Vehicle(load_config(ATHER).vehicle)
    v.speed = 2.0
    for _ in range(500):
        v.step(0.0, 1.0, 0.01)
    assert v.speed == 0.0


def test_uphill_slows_more_than_flat():
    cfg = load_config(ATHER)
    flat, hill = Vehicle(cfg.vehicle), Vehicle(cfg.vehicle)
    flat.speed = hill.speed = 10.0
    for _ in range(100):
        flat.step(0.0, 0.0, 0.01, 0.0)
        hill.step(0.0, 0.0, 0.01, 0.05)
    assert hill.speed < flat.speed


# --------------------------------------------------------------- simulate ---

@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.split("/")[-1])
def test_wot_launch_is_physically_sensible(path):
    cfg = load_config(path)
    r = simulate(cfg, build("wot_launch", cfg.dt_s, duration_s=25.0))
    m = r.metrics
    assert 1.5 < m["t_0_40_s"] < 8.0
    assert 60 < m["top_speed_kmph"] < 160
    assert m["soc_end"] < m["soc_start"]
    assert (r.telemetry["speed_ms"] >= 0).all()
    assert r.telemetry["torque_nm"].max() <= cfg.motor.peak_torque_nm + 1e-9
    assert r.telemetry["batt_voltage_v"].min() >= cfg.battery.min_voltage_v


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.split("/")[-1])
def test_urban_cycle_tracks_target_and_uses_sane_energy(path):
    cfg = load_config(path)
    r = simulate(cfg, build("urban_stopgo", cfg.dt_s))
    df = r.telemetry
    err = np.abs(df["speed_ms"] - df["target_ms"])
    assert err.mean() < 0.8                      # m/s mean tracking error
    assert 10 < r.metrics["wh_per_km"] < 60


def test_energy_accounting_matches_soc_drop():
    cfg = load_config(ATHER)
    r = simulate(cfg, build("urban_stopgo", cfg.dt_s))
    soc_drop_wh = (r.metrics["soc_start"] - r.metrics["soc_end"]) * cfg.battery.energy_kwh * 1000
    assert r.metrics["energy_wh"] == pytest.approx(soc_drop_wh, rel=0.20)


def test_simulation_is_deterministic():
    cfg = load_config(ATHER)
    a = simulate(cfg, build("urban_stopgo", cfg.dt_s)).telemetry
    b = simulate(cfg, build("urban_stopgo", cfg.dt_s)).telemetry
    assert a.equals(b)


def test_more_latency_means_later_launch():
    times = []
    for lat in (0.0, 0.2):
        cfg = load_config(ATHER, {"controller.latency_s": lat})
        times.append(simulate(cfg, build("wot_launch", cfg.dt_s, duration_s=15.0)).metrics["t_0_40_s"])
    assert times[1] > times[0]


def test_gentler_ramp_reduces_peak_jerk_on_tip_in():
    peaks = []
    for ramp in (2000.0, 150.0):
        cfg = load_config(ATHER, {"controller.torque_ramp_nm_per_s": ramp,
                                  "controller.filter_tau_s": 0.0})
        r = simulate(cfg, build("throttle_step", cfg.dt_s, level=0.8))
        peaks.append(r.metrics["peak_jerk_ms3"])
    assert peaks[1] < peaks[0]


def test_dt_mismatch_rejected():
    cfg = load_config(ATHER)
    with pytest.raises(ValueError):
        simulate(cfg, build("wot_launch", 0.02))


def test_jerk_metrics_include_the_launch_but_not_the_stop():
    import numpy as np
    from sim.config import load_config
    from sim.scenarios import build
    from sim.simulate import simulate
    cfg = load_config("configs/ather_450x_2p9.yaml")
    res = simulate(cfg, build("throttle_step", cfg.dt_s, level=0.7))
    df = res.telemetry
    launch_peak = df["jerk_ms3"].abs().iloc[:300].max()          # first 3 s include the launch
    assert res.metrics["peak_jerk_ms3"] == pytest.approx(df["jerk_ms3"].abs().max(), rel=1e-9)
    assert res.metrics["peak_jerk_ms3"] >= launch_peak - 1e-9
