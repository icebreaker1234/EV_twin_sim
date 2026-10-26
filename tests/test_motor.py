import math

import numpy as np
import pytest

from sim.config import load_config
from sim.motor import RPM_TO_RADS, Motor

CONFIGS = [
    "configs/ather_450x_2p9.yaml",
    "configs/ather_450x_3p7.yaml",
    "configs/ola_s1_pro_4kwh.yaml",
    "configs/ola_s1_pro_plus_5p2kwh.yaml",
]


@pytest.fixture(params=CONFIGS, ids=lambda p: p.split("/")[-1])
def motor(request):
    return Motor(load_config(request.param).motor)


def test_constant_torque_below_base_speed(motor):
    assert motor.torque_limit(0.0) == pytest.approx(motor.p.peak_torque_nm)
    assert motor.torque_limit(0.9 * motor.base_omega) == pytest.approx(motor.p.peak_torque_nm)


def test_constant_power_above_base_speed(motor):
    w = 1.5 * motor.base_omega
    assert motor.torque_limit(w) * w == pytest.approx(motor.p.peak_power_w)


def test_zero_torque_beyond_max_speed(motor):
    assert motor.torque_limit(1.01 * motor.max_omega) == 0.0


def test_base_speed_matches_config_property(motor):
    assert motor.base_omega / RPM_TO_RADS == pytest.approx(motor.p.base_rpm)


def test_clip_is_symmetric_for_regen(motor):
    w = 100.0
    lim = float(motor.torque_limit(w))
    assert motor.clip_torque(1e6, w) == pytest.approx(lim)
    assert motor.clip_torque(-1e6, w) == pytest.approx(-lim)
    assert motor.clip_torque(1.0, w) == pytest.approx(1.0)


def test_electrical_power_losses(motor):
    w = 200.0
    drive = float(motor.electrical_power(10.0, w))
    regen = float(motor.electrical_power(-10.0, w))
    assert drive > 10.0 * w          # draws more than it delivers
    assert regen < 0.0               # returns power
    assert abs(regen) < 10.0 * w     # but less than the mechanical input


def test_vectorised_and_zero_speed(motor):
    w = np.array([0.0, 50.0, 500.0])
    out = motor.electrical_power(np.array([5.0, 5.0, 5.0]), w)
    assert out.shape == (3,) and out[0] == 0.0 and not np.isnan(out).any()
