"""การแก้โมเดลจากผล backtest: ค่าผิดปกติจากต้นทาง, forecast_log รุ่นใหม่, ช่วง, ปริมาณน้ำ, level_controlled, แนวโน้ม 12 ชม."""
import datetime as dt
import json
import sqlite3

import pandas as pd
import pytest

from app import config

T0 = dt.datetime(2026, 9, 10, 8, 0)


# ---------- ขั้นที่ 0: ค่าที่เป็นไปไม่ได้จาก ThaiWater ----------

def test_plausible_range_rejects_known_bad_value():
    assert config.plausible(3240, 321.47) is True
    assert config.plausible(3240, 493.70) is False          # P.21 เมื่อ 4 ก.ค. 2569 13:00 (ตลิ่ง 323.50)
    assert config.plausible(3226, 305.80) is True            # P.1 ยอดปี 2567 = 5.30 ม. ตามไม้วัด
    assert config.plausible(99999, 1500.0) is True           # สถานีที่ระบบไม่รู้จัก ไม่ตัดสิน


def test_parsers_and_hourly_drop_implausible_values():
    from app import store, thaiwater
    rows = thaiwater.parse_waterlevel_graph(3240, {"data": {"graph_data": [
        {"datetime": "2026-07-04 12:00", "value": 321.47},
        {"datetime": "2026-07-04 13:00", "value": 493.70},
        {"datetime": "2026-07-04 14:00", "value": 321.42}]}})
    assert [r["t"].hour for r in rows] == [12, 14]
    load = {"waterlevel_data": {"data": [{"station": {"id": 3240}, "waterlevel_datetime": "2026-07-04 13:00",
                                          "waterlevel_msl": "493.70"}]}}
    assert thaiwater.parse_waterlevel_load(load) == []
    # ค่าเสียที่อยู่ในฐานข้อมูลก่อนมีการตรวจ ต้องไม่ถูกใช้ใน hourly()
    t = dt.datetime(2026, 7, 4, 12)
    store.upsert([{"station_id": 3240, "t": t + dt.timedelta(hours=i), "level_msl": v}
                  for i, v in enumerate([321.47, 493.70, 321.42])], "graph")
    w = store.hourly()
    assert w["P21"].notna().sum() == 2 and pd.isna(w.loc[t + dt.timedelta(hours=1), "P21"])


# ---------- ขั้นที่ 1: forecast_log รุ่นใหม่ ----------

def test_forecast_log_migrates_old_database(tmp_path):
    from app import store
    con = sqlite3.connect(config.DB_PATH)
    con.executescript("""CREATE TABLE forecast_log (issued_for TEXT NOT NULL, h INTEGER NOT NULL, model TEXT NOT NULL,
        target_t TEXT NOT NULL, now_m REAL NOT NULL, pred_m REAL NOT NULL, lo_m REAL, hi_m REAL, trained_at TEXT,
        logged_at TEXT NOT NULL, actual_m REAL, err_m REAL, PRIMARY KEY (issued_for, h, model));
        INSERT INTO forecast_log VALUES ('2026-09-01 00:00', 1, 'ensemble', '2026-09-01 01:00', 1.0, 1.1, 1.0, 1.2,
        'x', '2026-09-01 00:10', NULL, NULL);""")
    con.commit(); con.close()
    with store.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(forecast_log)")}
        n = c.execute("SELECT COUNT(*) FROM forecast_log").fetchone()[0]
    assert {"model_version", "flags"} <= cols and n == 1          # เพิ่มคอลัมน์โดยข้อมูลเดิมยังอยู่


def _pred(now_m=1.5, delta=0.02):
    hs = {h: {"ensemble_m": now_m + delta * h, "ridge_m": now_m + delta * h, "gbm_m": now_m + delta * h,
              "lo_m": now_m + delta * h - 0.05, "hi_m": now_m + delta * h + 0.05} for h in config.HORIZONS}
    return {"issued_for": pd.Timestamp(T0), "now_m": now_m, "horizons": hs}


def test_forecast_log_records_version_flags_and_splits_by_condition():
    from app import forecast_log, store
    b = {"trained_at": "x", "version": "test-1"}
    forecast_log.record(b, _pred(), T0, flags={"level_controlled": True, "trend12_shown": False})
    forecast_log.record(b, dict(_pred(), issued_for=pd.Timestamp(T0 + dt.timedelta(hours=1))),
                        T0 + dt.timedelta(hours=1), flags={"level_controlled": False, "trend12_shown": True})
    df = forecast_log.load()
    assert set(df["model_version"]) == {"test-1"}
    assert json.loads(df.iloc[0]["flags"])["level_controlled"] in (True, False)
    store.upsert([{"station_id": 3226, "t": T0 + dt.timedelta(hours=i), "level_msl": 1.5 + config.P1_GAUGE_ZERO_MSL}
                  for i in range(15)], "test")
    forecast_log.score()
    s = forecast_log.summary(T0 + dt.timedelta(hours=16), days=7)
    h1 = next(x for x in s["horizons"] if x["h"] == 1)
    assert set(h1["by_condition"]) == {"normal", "level_controlled"}
    assert h1["by_condition"]["level_controlled"]["n"] == 1
    assert s["trend12"]["n"] == 1                                  # นับเฉพาะครั้งที่แนวโน้มแสดงจริง


# ---------- ขั้นที่ 4: ระดับเปลี่ยน ปริมาณน้ำไม่เปลี่ยน ----------

def _sep26():
    df = pd.read_csv(config.ROOT / "data" / "backtest" / "thaiwater_2026_sep.csv", index_col=0, parse_dates=True)
    return df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="h"))


KNOWN_CONTROLLED = [("2026-09-05 06:00", "2026-09-05 10:00"), ("2026-09-08 16:00", "2026-09-08 22:00"),
                    ("2026-09-23 07:00", "2026-09-23 13:00"), ("2026-09-28 08:00", "2026-09-28 14:00"),
                    ("2026-09-30 08:00", "2026-09-30 14:00")]


def test_level_controlled_finds_known_events_not_real_flow():
    from app import forecast_logic as fl
    s = fl.level_controlled_series(_sep26())
    for a, b in KNOWN_CONTROLLED:                        # เหตุการณ์ใน docs/experiment-findings.md
        assert s.loc[a:b, "detected"].any(), (a, b)
    assert not s.loc["2026-09-26 07:00":"2026-09-26 13:00", "detected"].any()   # น้ำมาจริง ปริมาณน้ำ +22%
    assert s["detected"].mean() < 0.15                 # ไม่ติดธงพร่ำเพรื่อ


def test_level_controlled_point_and_no_discharge():
    from app import forecast_logic as fl
    w = _sep26()
    r = fl.level_controlled(w.loc[:"2026-09-30 14:00"])   # ตรวจพบเมื่อหลักฐานครบตอนปลายเหตุการณ์
    assert r["detected"] is True and r["change_m"] < -0.15 and abs(r["discharge_change_pct"]) < 8
    assert fl.level_controlled(w.loc[:"2026-09-26 12:00"]) == {"detected": False}
    assert fl.level_controlled(w.drop(columns="Q1")) == {"detected": False, "reason": "no_discharge"}


# ---------- ขั้นที่ 5: แนวโน้ม 12 ชม. เฉพาะเมื่อเชื่อถือได้ ----------

def _p(now_m, d12=0.3):
    return {"issued_for": pd.Timestamp("2026-09-10 08:00"), "now_m": now_m,
            "horizons": {12: {"ensemble_m": now_m + d12}}}


def _wide(p67_rise=0.0):
    idx = pd.date_range("2026-09-10 00:00", "2026-09-10 08:00", freq="h")
    w = pd.DataFrame({"P1": 302.0, "P67": 316.0, "P21": 321.0, "Q1": 100.0}, index=idx)
    w.loc[idx[-3:], "P67"] += p67_rise
    return w


def test_trend12_hidden_in_low_flow_shown_when_high_or_upstream_rising():
    from app import forecast_logic as fl
    tr, why = fl.trend12(_p(1.5), _wide(), {"detected": False})
    assert tr is None and why == "low_flow"
    tr, why = fl.trend12(_p(1.5), _wide(p67_rise=0.2), {"detected": False})
    assert tr["direction"] == "rising" and why is None
    tr, why = fl.trend12(_p(3.5, d12=-0.05), _wide(), {"detected": False})
    assert tr["direction"] == "steady" and why is None
    assert fl.trend12(_p(3.5), _wide(), {"detected": True}) == (None, "level_controlled")
    assert fl.trend12(None, _wide(), {"detected": False}) == (None, "no_forecast")


def test_api_exposes_level_controlled_and_trend_reason(monkeypatch):
    from app import collector
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "COLLECT", False)
    collector.ensure_seed()
    collector.retrain()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        calm = c.get("/api/forecast", params={"at": "2024-09-29 12:00"}).json()
        peak = c.get("/api/forecast", params={"at": "2024-10-05 02:00"}).json()
    assert calm["level_controlled"] == {"detected": False, "reason": "no_discharge"}   # seed 2567 ไม่มีปริมาณน้ำ
    assert peak["trend12"] is not None and peak["trend12_hidden_reason"] is None
    assert (calm["trend12"] is None) == (calm["trend12_hidden_reason"] is not None)
