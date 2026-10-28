"""Generate grafana/dashboards/ev_overview.json.

    python grafana/build_dashboard.py

Edit the panels here and regenerate; the JSON is committed so Grafana can load
it directly through provisioning.

Time axis: every run is stored with t_s = seconds since the scenario started,
and the queries map that to a fixed epoch (2000-01-01 00:00:00 UTC + t_s), so
runs of different vehicles / settings overlay on one axis. The dashboard time
range is therefore 00:00:00 .. 00:03:20 on 2000-01-01, not "last 6 hours".
"""
from __future__ import annotations

import json
from pathlib import Path

DS = {"type": "postgres", "uid": "ev-timescale"}
EPOCH_TIME = "TIMESTAMPTZ '2000-01-01 00:00:00+00' + t.t_s * INTERVAL '1 second' AS time"
LEGEND = "r.vehicle_name || ' | ' || r.ctrl"
FILTER = ("r.scenario = '$scenario' AND r.vehicle_name IN ($vehicle) "
          "AND r.ctrl IN ($ctrl)")

_next_id = iter(range(1, 1000))


def _target(sql: str, ref: str = "A", fmt: str = "time_series") -> dict:
    return {"datasource": DS, "refId": ref, "format": fmt, "rawQuery": True,
            "editorMode": "code", "rawSql": " ".join(sql.split())}


def ts_sql(value_expr: str, suffix: str = "") -> str:
    metric = f"{LEGEND} || '{suffix}'" if suffix else LEGEND
    return (f"SELECT {EPOCH_TIME}, {metric} AS metric, {value_expr} AS value "
            f"FROM ev.telemetry t JOIN ev.runs r ON r.run_id = t.run_id "
            f"WHERE {FILTER} ORDER BY 1")


def timeseries(title: str, x: int, y: int, w: int, h: int, targets: list[dict],
               unit: str = "short", description: str = "", soft_max: float | None = None) -> dict:
    defaults = {"unit": unit, "custom": {"drawStyle": "line", "lineWidth": 1,
                                          "showPoints": "never", "spanNulls": True,
                                          "fillOpacity": 0}}
    if soft_max is not None:
        defaults["custom"]["axisSoftMax"] = soft_max
    return {"id": next(_next_id), "type": "timeseries", "title": title,
            "description": description, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom",
                                   "showLegend": True},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def build() -> dict:
    panels = [
        {"id": next(_next_id), "type": "text", "title": "", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 3},
         "options": {"mode": "markdown", "content":
             "**EV digital twin: Ather 450X vs Ola S1 Pro.** Pick a scenario and compare "
             "vehicles and controller settings. Time axis = seconds since the scenario "
             "started (shown as 00:00:SS); adjust the time range for short or long scenarios. "
             "Data is simulated; values marked ESTIMATED in the configs are not yet calibrated."}},

        timeseries("Speed vs target", 0, 3, 12, 8, [
            _target(ts_sql("t.speed_ms * 3.6"), "A"),
            _target("SELECT TIMESTAMPTZ '2000-01-01 00:00:00+00' + t.t_s * INTERVAL '1 second' AS time, "
                    "'target' AS metric, t.target_ms * 3.6 AS value FROM ev.telemetry t "
                    "WHERE t.run_id = (SELECT run_id FROM ev.runs WHERE scenario = '$scenario' "
                    "ORDER BY run_id LIMIT 1) AND t.target_ms IS NOT NULL ORDER BY 1", "B"),
        ], unit="velocitykmh", description="Closed-loop scenarios show the speed target; "
                                           "open-loop ones (launch, throttle step) have none."),
        timeseries("Acceleration", 12, 3, 12, 8, [_target(ts_sql("t.accel_ms2"))], unit="accMS2"),

        timeseries("Jerk", 0, 11, 12, 8, [_target(ts_sql("t.jerk_ms3"))], unit="suffix: m/s³",
                   description="Rate of change of acceleration: the ride-comfort metric."),
        timeseries("Torque: command vs delivered", 12, 11, 12, 8, [
            _target(ts_sql("t.torque_cmd_nm", " cmd"), "A"),
            _target(ts_sql("t.torque_nm", " actual"), "B"),
        ], unit="suffix: Nm",
            description="Delivered torque falls below the command only when the battery limits power."),

        timeseries("Pedal (throttle)", 0, 19, 12, 8, [_target(ts_sql("t.pedal"))],
                   unit="percentunit", soft_max=1.0),
        timeseries("Power: motor shaft vs battery", 12, 19, 12, 8, [
            _target(ts_sql("t.torque_nm * t.motor_rpm * 2 * PI() / 60.0", " shaft"), "A"),
            _target(ts_sql("t.batt_power_w", " battery"), "B"),
        ], unit="watt", description="Battery power exceeds shaft power by motor and inverter losses."),

        timeseries("Rider: torso lean", 0, 27, 8, 8, [_target(ts_sql("t.torso_lean_deg"))],
                   unit="suffix: °",
                   description="Backward lean of the rider's torso (spring-damper at the hips). "
                               "Body parameters are ESTIMATED from biomechanics ranges."),
        timeseries("Rider: head vs scooter acceleration", 8, 27, 8, 8, [
            _target(ts_sql("t.accel_ms2", " scooter"), "A"),
            _target(ts_sql("t.head_accel_ms2", " head"), "B"),
        ], unit="accMS2", description="The head's acceleration rings around the scooter's "
                                      "because the torso is a spring."),
        timeseries("Rider: head vs scooter jerk", 16, 27, 8, 8, [
            _target(ts_sql("t.jerk_ms3", " scooter"), "A"),
            _target(ts_sql("t.head_jerk_ms3", " head"), "B"),
        ], unit="suffix: m/s³"),

        timeseries("Battery voltage", 0, 35, 8, 7, [_target(ts_sql("t.batt_voltage_v"))], unit="volt"),
        timeseries("Battery current", 8, 35, 8, 7, [_target(ts_sql("t.batt_current_a"))], unit="amp"),
        timeseries("State of charge", 16, 35, 8, 7, [_target(ts_sql("t.soc"))], unit="percentunit"),

        {"id": next(_next_id), "type": "table", "title": "Run summary", "datasource": DS,
         "gridPos": {"x": 0, "y": 42, "w": 24, "h": 9},
         "targets": [_target(
             "SELECT r.vehicle_name AS \"Vehicle\", r.ctrl AS \"Controller\", "
             "r.t_0_40_s AS \"0-40 km/h (s)\", r.top_speed_kmph AS \"Top speed (km/h)\", "
             "r.wh_per_km AS \"Wh/km\", r.energy_wh AS \"Energy (Wh)\", "
             "r.p95_jerk_ms3 AS \"p95 |jerk|\", r.rms_jerk_ms3 AS \"RMS jerk\", "
             "r.peak_jerk_ms3 AS \"Peak jerk\", r.peak_accel_ms2 AS \"Peak accel\", "
             "r.peak_lean_deg AS \"Peak lean (deg)\", r.jerk_gain AS \"Jerk gain\", "
             "r.distance_m AS \"Distance (m)\" FROM ev.runs r WHERE " + FILTER +
             " ORDER BY r.vehicle_name, r.ctrl", fmt="table")],
         "fieldConfig": {"defaults": {"decimals": 2}, "overrides": []},
         "options": {"showHeader": True, "cellHeight": "sm"}},

        {"id": next(_next_id), "type": "barchart", "title": "Jerk by vehicle and controller setting",
         "datasource": DS, "gridPos": {"x": 0, "y": 51, "w": 12, "h": 9},
         "targets": [_target(
             "SELECT r.vehicle_name || ' | ' || r.ctrl AS run, r.p95_jerk_ms3 AS \"p95\", "
             "r.rms_jerk_ms3 AS \"rms\", r.peak_jerk_ms3 AS \"peak\" FROM ev.runs r WHERE "
             + FILTER + " ORDER BY 1", fmt="table")],
         "fieldConfig": {"defaults": {"unit": "suffix: m/s³"}, "overrides": []},
         "options": {"xField": "run", "orientation": "horizontal", "showValue": "auto",
                     "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                     "tooltip": {"mode": "multi"}}},

        {"id": next(_next_id), "type": "barchart", "title": "Energy consumption (Wh/km)",
         "datasource": DS, "gridPos": {"x": 12, "y": 51, "w": 12, "h": 9},
         "targets": [_target(
             "SELECT r.vehicle_name || ' | ' || r.ctrl AS run, r.wh_per_km AS \"Wh/km\" "
             "FROM ev.runs r WHERE " + FILTER + " AND r.wh_per_km IS NOT NULL ORDER BY 1",
             fmt="table")],
         "fieldConfig": {"defaults": {"unit": "suffix: Wh/km"}, "overrides": []},
         "options": {"xField": "run", "orientation": "horizontal", "showValue": "auto",
                     "legend": {"showLegend": False}, "tooltip": {"mode": "multi"}}},

        {"id": next(_next_id), "type": "barchart", "title": "Peak torso lean (deg)",
         "datasource": DS, "gridPos": {"x": 0, "y": 60, "w": 12, "h": 9},
         "targets": [_target(
             "SELECT r.vehicle_name || ' | ' || r.ctrl AS run, r.peak_lean_deg AS \"lean\" "
             "FROM ev.runs r WHERE " + FILTER + " AND r.peak_lean_deg IS NOT NULL ORDER BY 1",
             fmt="table")],
         "fieldConfig": {"defaults": {"unit": "suffix: °"}, "overrides": []},
         "options": {"xField": "run", "orientation": "horizontal", "showValue": "auto",
                     "legend": {"showLegend": False}, "tooltip": {"mode": "multi"}}},

        {"id": next(_next_id), "type": "barchart", "title": "Jerk gain: head RMS jerk / scooter RMS jerk",
         "description": "Above 1 the rider's body amplifies the scooter's jerk.",
         "datasource": DS, "gridPos": {"x": 12, "y": 60, "w": 12, "h": 9},
         "targets": [_target(
             "SELECT r.vehicle_name || ' | ' || r.ctrl AS run, r.jerk_gain AS \"gain\" "
             "FROM ev.runs r WHERE " + FILTER + " AND r.jerk_gain IS NOT NULL ORDER BY 1",
             fmt="table")],
         "fieldConfig": {"defaults": {"decimals": 2}, "overrides": []},
         "options": {"xField": "run", "orientation": "horizontal", "showValue": "auto",
                     "legend": {"showLegend": False}, "tooltip": {"mode": "multi"}}},
    ]

    def query_var(name: str, label: str, sql: str, multi: bool, default: str | None = None) -> dict:
        var = {"name": name, "label": label, "type": "query", "datasource": DS,
               "query": sql, "definition": sql, "refresh": 1, "sort": 1, "hide": 0,
               "multi": multi, "includeAll": multi, "allValue": None, "options": [],
               "current": {}}
        if default:
            var["current"] = {"text": default, "value": default}
        else:
            var["current"] = {"text": ["All"], "value": ["$__all"]}
        return var

    templating = [
        query_var("scenario", "Scenario", "SELECT DISTINCT scenario FROM ev.runs ORDER BY 1",
                  multi=False, default="urban_stopgo"),
        query_var("vehicle", "Vehicle",
                  "SELECT DISTINCT vehicle_name FROM ev.runs WHERE scenario = '$scenario' ORDER BY 1",
                  multi=True),
        query_var("ctrl", "Controller settings",
                  "SELECT DISTINCT ctrl FROM ev.runs WHERE scenario = '$scenario' "
                  "AND vehicle_name IN ($vehicle) ORDER BY 1", multi=True),
    ]

    return {
        "uid": "ev-overview", "title": "EV Digital Twin: Overview",
        "tags": ["ev", "simulation"], "timezone": "utc", "schemaVersion": 39, "version": 1,
        "editable": True, "graphTooltip": 1, "refresh": "",
        "time": {"from": "2000-01-01T00:00:00.000Z", "to": "2000-01-01T00:03:20.000Z"},
        "panels": panels, "templating": {"list": templating},
        "annotations": {"list": []}, "links": [],
    }


if __name__ == "__main__":
    out = Path(__file__).with_name("dashboards") / "ev_overview.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(build(), indent=2) + "\n")
    print("wrote", out)
