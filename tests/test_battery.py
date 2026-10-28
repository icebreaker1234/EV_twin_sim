import pytest

from sim.battery import Battery
from sim.config import load_config

CONFIGS = [
    "configs/ather_450x_2p9.yaml",
    "configs/ather_450x_3p7.yaml",
    "configs/ola_s1_pro_4kwh.yaml",
    "configs/ola_s1_pro_plus_5p2kwh.yaml",
]


@pytest.fixture(params=CONFIGS, ids=lambda p: p.split("/")[-1])
def cfg(request):
    return load_config(request.param)


@pytest.fixture
def bat(cfg):
    return Battery(cfg.battery)


def test_ocv_monotonic_and_brackets_nominal(bat):
    socs = [i / 20 for i in range(21)]
    v = [bat.open_circuit_voltage(s) for s in socs]
    assert all(b >= a for a, b in zip(v, v[1:]))
    assert v[0] < bat.p.nominal_voltage_v < v[-1]


def test_empty_pack_ocv_not_below_cutoff(bat):
    assert bat.open_circuit_voltage(0.0) >= bat.p.min_voltage_v - 1e-9


def test_delivered_power_matches_request(bat):
    s = bat.step(3000.0, 0.01)
    assert not s.limited
    assert s.power_w == pytest.approx(3000.0)
    assert s.voltage_v * s.current_a == pytest.approx(3000.0)


def test_voltage_sags_under_load(bat):
    voc = bat.open_circuit_voltage()
    assert bat.step(4000.0, 0.01).voltage_v < voc


def test_loss_is_i_squared_r(bat):
    s = bat.step(4000.0, 0.01)
    assert s.loss_w == pytest.approx(s.current_a ** 2 * bat.p.internal_resistance_ohm)


def test_regen_charges_pack(bat):
    bat.reset(0.5)
    s = bat.step(-1500.0, 1.0)
    assert s.current_a < 0 and s.soc > 0.5


def test_full_pack_rejects_regen(bat):
    bat.reset(1.0)
    s = bat.step(-1500.0, 1.0)
    assert s.power_w == 0.0 and s.limited and s.soc == 1.0


def test_impossible_request_is_limited(bat):
    s = bat.step(1e7, 0.01)
    assert s.limited and s.power_w < 1e7
    assert s.voltage_v >= bat.p.min_voltage_v - 1e-6


def test_cutoff_limits_power_on_empty_pack(bat):
    bat.reset(0.02)
    assert bat.max_discharge_power() < bat.step(0.0, 0.01).voltage_v * 1e6
    s = bat.step(1e6, 0.01)
    assert s.limited and s.voltage_v >= bat.p.min_voltage_v - 1e-6


def test_energy_roughly_matches_rated_capacity(cfg):
    """Discharge slowly (negligible I^2R) from full to empty; energy ~ rating."""
    bat = Battery(cfg.battery)
    bat.reset(1.0)
    energy_wh, dt = 0.0, 10.0
    while True:
        s = bat.step(300.0, dt)
        if s.limited:                      # cutoff reached: pack is "empty"
            break
        energy_wh += s.power_w * dt / 3600.0
    assert energy_wh == pytest.approx(cfg.battery.energy_kwh * 1000.0, rel=0.10)


def test_empty_pack_cannot_discharge(bat):
    bat.reset(0.0)
    s = bat.step(500.0, 1.0)
    assert s.power_w == 0.0 and s.limited and s.soc == 0.0
