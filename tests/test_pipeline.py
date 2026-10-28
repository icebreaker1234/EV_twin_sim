"""Database and dashboard tests.

The Postgres-backed tests run only when EV_TEST_DSN points at a scratch database,
e.g.  EV_TEST_DSN=postgresql://ev:ev@localhost:5432/ev_test pytest tests/test_pipeline.py
They are skipped otherwise, so the normal test run needs no database.
"""
import json
import os
import re
from pathlib import Path

import pytest

from grafana.build_dashboard import build
from sim.config import load_config
from sim.scenarios import build as build_scenario
from sim.simulate import simulate

DASHBOARD_JSON = Path("grafana/dashboards/ev_overview.json")
DSN = os.environ.get("EV_TEST_DSN")
needs_db = pytest.mark.skipif(not DSN, reason="set EV_TEST_DSN to run database tests")


# ------------------------------------------------- no-database dashboard checks

def test_committed_dashboard_matches_generator():
    assert json.loads(DASHBOARD_JSON.read_text()) == build(), \
        "ev_overview.json is stale: run `python grafana/build_dashboard.py`"


def test_dashboard_structure():
    d = build()
    ids = [p["id"] for p in d["panels"]]
    assert len(ids) == len(set(ids))
    assert {v["name"] for v in d["templating"]["list"]} == {"scenario", "vehicle", "ctrl"}
    for p in d["panels"]:
        for t in p.get("targets", []):
            assert t["datasource"]["uid"] == "ev-timescale"


def test_provisioned_datasource_uid_matches_dashboard():
    text = Path("grafana/provisioning/datasources/timescaledb.yml").read_text()
    assert "uid: ev-timescale" in text


# ---------------------------------------------------------- database-backed ---

@pytest.fixture(scope="module")
def conn():
    from pipeline import loader
    c = loader.connect(DSN)
    with c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS ev CASCADE")
    c.commit()
    loader.init_schema(c)
    yield c
    c.close()


def _store(conn, vehicle, scenario, overrides=None, **kw):
    from pipeline import loader
    cfg = load_config(f"configs/{vehicle}.yaml", overrides)
    result = simulate(cfg, build_scenario(scenario, cfg.dt_s, **kw))
    return loader.save_run(conn, result), result


@needs_db
def test_save_run_roundtrip_and_idempotent(conn):
    run_id, result = _store(conn, "ather_450x_2p9", "throttle_step", level=0.6)
    run_id2, _ = _store(conn, "ather_450x_2p9", "throttle_step", level=0.6)
    assert run_id == run_id2
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ev.runs WHERE run_id = %s", (run_id,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*), max(t_s) FROM ev.telemetry WHERE run_id = %s", (run_id,))
        rows, t_max = cur.fetchone()
        assert rows == pytest.approx(result.scenario.n / 5, abs=2)     # 20 Hz from 100 Hz
        assert t_max == pytest.approx(result.scenario.time_s[-1], abs=0.06)
        cur.execute("SELECT peak_jerk_ms3, vehicle_name FROM ev.runs WHERE run_id = %s", (run_id,))
        jerk, name = cur.fetchone()
        assert jerk == pytest.approx(result.metrics["peak_jerk_ms3"])
        assert name == "Ather 450X 2.9 kWh"


@needs_db
def test_open_loop_target_stored_as_null(conn):
    run_id, _ = _store(conn, "ola_s1_pro_4kwh", "wot_launch", duration_s=5.0)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ev.telemetry WHERE run_id = %s AND target_ms IS NOT NULL",
                    (run_id,))
        assert cur.fetchone()[0] == 0


def test_clean_flushes_denormals_and_maps_nan_to_null():
    from pipeline.loader import _clean
    assert _clean(1.3e-322) == 0.0 and _clean(-1e-40) == 0.0
    assert _clean(float("nan")) is None and _clean(float("inf")) is None
    assert _clean(1e-9) == 1e-9 and _clean(None) is None


def _render(sql: str, scenario: str, vehicles: list[str], ctrls: list[str]) -> str:
    quote = lambda xs: ", ".join("'" + x.replace("'", "''") + "'" for x in xs)
    sql = sql.replace("IN ($vehicle)", f"IN ({quote(vehicles)})")
    sql = sql.replace("IN ($ctrl)", f"IN ({quote(ctrls)})")
    return sql.replace("$scenario", scenario)


@needs_db
def test_every_dashboard_query_executes_and_returns_rows(conn):
    from pipeline import loader
    for v in ("ather_450x_2p9", "ola_s1_pro_plus_5p2kwh"):
        for lat in (0.05, 0.2):
            _store(conn, v, "urban_stopgo", {"controller.latency_s": lat})
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT vehicle_name FROM ev.runs WHERE scenario='urban_stopgo'")
        vehicles = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT ctrl FROM ev.runs WHERE scenario='urban_stopgo'")
        ctrls = [r[0] for r in cur.fetchall()]

    d = build()
    # Variable queries
    for var in d["templating"]["list"]:
        sql = _render(var["query"], "urban_stopgo", vehicles, ctrls)
        with conn.cursor() as cur:
            cur.execute(sql)
            assert cur.fetchall(), f"variable {var['name']} returned nothing"

    # Panel queries
    checked = 0
    for p in d["panels"]:
        for t in p.get("targets", []):
            sql = _render(t["rawSql"], "urban_stopgo", vehicles, ctrls)
            assert "$" not in re.sub(r"\$\$", "", sql), f"unresolved variable in: {p['title']}"
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
            assert rows, f"panel '{p['title']}' returned no rows"
            if t["format"] == "time_series":
                assert cols == ["time", "metric", "value"], p["title"]
            checked += 1
    assert checked >= 18


@needs_db
def test_init_schema_upgrades_a_database_made_before_the_rider_columns(conn):
    from pipeline import loader
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE ev.runs DROP COLUMN jerk_gain")
        cur.execute("ALTER TABLE ev.telemetry DROP COLUMN head_jerk_ms3")
    conn.commit()
    loader.init_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='ev' AND column_name IN ('jerk_gain','head_jerk_ms3')")
        assert {r[0] for r in cur.fetchall()} == {"jerk_gain", "head_jerk_ms3"}
