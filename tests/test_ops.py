"""forecast_log, ความแม่นย้อนหลัง, API ข้อมูลสำหรับนักวิจัย และสถานะระบบ"""
import datetime as dt
import io

import pandas as pd
import pytest

from app import config

T0 = dt.datetime(2026, 10, 1, 8, 0)


def _pred(now_m=2.0, delta=0.10, band=0.05):
    """ทุก horizon ทายว่าขึ้น delta × h"""
    hs = {}
    for h in config.HORIZONS:
        v = now_m + delta * h
        hs[h] = {"ensemble_m": v, "ridge_m": v + 0.02, "gbm_m": v - 0.02, "lo_m": v - band, "hi_m": v + band,
                 "ridge_lo_m": v - band, "ridge_hi_m": v + band + 0.04, "gbm_lo_m": v - band - 0.04, "gbm_hi_m": v + band}
    return {"issued_for": pd.Timestamp(T0), "now_m": now_m, "horizons": hs}


def _obs(start, levels_m):
    from app import store
    store.upsert([{"station_id": 3226, "t": start + dt.timedelta(hours=i), "level_msl": v + config.P1_GAUGE_ZERO_MSL}
                  for i, v in enumerate(levels_m)], "test")


def test_record_once_per_issued_for_and_skip_late():
    from app import forecast_log
    b = {"trained_at": "2026-10-01T00:00"}
    n = forecast_log.record(b, _pred(), T0 + dt.timedelta(minutes=20))
    assert n == len(config.HORIZONS) * 3                       # ทุก horizon × 3 โมเดล
    assert forecast_log.record(b, _pred(now_m=9.0), T0 + dt.timedelta(minutes=30)) == 0   # ครั้งหลังไม่ทับ
    df = forecast_log.load()
    assert (df["now_m"] == 2.0).all()
    # issued_for เก่ากว่า 3 ชม. = ทายย้อนหลัง ไม่บันทึก
    late = dict(_pred(), issued_for=pd.Timestamp(T0 - dt.timedelta(hours=5)))
    assert forecast_log.record(b, late, T0) == 0


def test_score_uses_measured_values_and_summary_stats():
    from app import forecast_log
    forecast_log.record({"trained_at": "x"}, _pred(now_m=2.0, delta=0.10, band=0.05), T0)
    # ค่าจริง: ขึ้น 0.08 ม./ชม. → ensemble ทายสูงไป 0.02 × h; ชั่วโมงที่ 4 หาย (ต้องไม่เติม)
    real = [2.0 + 0.08 * i for i in range(8)]
    _obs(T0, real[:4])
    _obs(T0 + dt.timedelta(hours=5), real[5:])
    n = forecast_log.score()
    assert n == 5 * 3                                          # มีค่าจริงที่ h=1,2,3,5,6 (h=4 หาย, h=12 ยังไม่ถึง)
    df = forecast_log.load()
    assert df[(df.h == 4)]["actual_m"].isna().all()
    e3 = df[(df.h == 3) & (df.model == "ensemble")].iloc[0]
    assert e3.actual_m == pytest.approx(2.24) and e3.err_m == pytest.approx(0.06)
    s = forecast_log.summary(T0 + dt.timedelta(hours=8), days=7, series_h=3)
    h3 = next(x for x in s["horizons"] if x["h"] == 3)
    ens = h3["models"]["ensemble"]
    assert ens["n"] == 1 and ens["rmse_cm"] == pytest.approx(6.0) and ens["bias_cm"] == pytest.approx(6.0)
    assert ens["coverage"] == 0.0                               # ค่าจริง 2.24 อยู่นอกช่วง 2.25–2.35
    assert h3["persistence_rmse_cm"] == pytest.approx(24.0)
    assert next(x for x in s["horizons"] if x["h"] == 4)["n"] == 0
    assert s["series"][0]["actual_m"] == pytest.approx(2.24)


def test_poll_kinds_count_429_and_backoff(monkeypatch):
    from app import collector, store, thaiwater
    monkeypatch.setattr(collector, "now_th", lambda: T0)

    def boom():
        raise thaiwater.RateLimited("429")
    monkeypatch.setattr(thaiwater, "fetch_latest", boom)
    assert collector.poll_once() == "429"
    assert collector.poll_once() == "429"
    assert store.get_meta("http_429")["count"] == 2
    monkeypatch.setattr(thaiwater, "fetch_latest", lambda: [])
    assert collector.poll_once() == "empty"                    # ไม่เจอสถานีของเรา = อาจเปลี่ยนรูปแบบข้อมูล
    assert [p["kind"] for p in store.get_meta("poll_log")] == ["429", "429", "empty"]
    assert collector.next_wait(10, "429") == 20 and collector.next_wait(40, "429") == 60
    assert collector.next_wait(60, "ok") == config.POLL_MINUTES


def test_live_forecast_log_end_to_end(monkeypatch):
    """จำลองการรันจริง: บันทึกพยากรณ์ตอน 08:30 แล้วค่าจริงมาถึงใน 7 ชม. ต่อมา"""
    from app import collector, store, thaiwater
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "COLLECT", False)
    shift = dt.datetime(2026, 9, 25, 1) - dt.datetime(2024, 9, 22, 1)
    seed = [dict(r, t=r["t"] + shift) for r in store.load_seed()]
    now = dt.datetime(2026, 10, 1, 8, 30)
    collector.ensure_seed()                                    # ระบบจริงมีข้อมูลปี 2567 ก่อนเสมอ
    store.upsert([r for r in seed if r["t"] <= now], "graph")
    clock = {"now": now}
    monkeypatch.setattr(collector, "now_th", lambda: clock["now"])
    collector.retrain()
    first = collector.log_forecast()
    assert first["logged"] == len(config.HORIZONS) * 3 and first["scored"] == 0
    clock["now"] = now + dt.timedelta(hours=7)
    store.upsert([r for r in seed if r["t"] <= clock["now"]], "load")
    assert collector.log_forecast()["scored"] >= 6 * 3
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        a = c.get("/api/accuracy", params={"days": 7, "h": 6}).json()
        assert c.get("/api/accuracy", params={"days": 5}).status_code == 422
        hl = c.get("/api/health").json()
    assert a["mode"] == "live" and len(a["cv"]) == 6
    assert all(x["n"] >= 1 for x in a["log"]["horizons"])
    assert a["log"]["series"][0]["actual_m"] is not None
    assert hl["forecast_log"]["issued"] >= 1 and hl["model_info"]["horizons"] == config.HORIZONS


def test_accuracy_demo_explains_no_log(monkeypatch):
    from app import collector
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "COLLECT", False)
    collector.ensure_seed()
    collector.retrain()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        a = c.get("/api/accuracy").json()
    assert a["mode"] == "demo" and a["log"] is None and a["cv"][5]["h"] == 6


def test_data_api_hourly_csv_json_and_stations(monkeypatch):
    from app import collector
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "COLLECT", False)
    collector.ensure_seed()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        st = c.get("/api/stations").json()
        js = c.get("/api/data/hourly", params={"start": "2024-10-05", "end": "2024-10-05"}).json()
        csv = c.get("/api/data/hourly.csv", params={"start": "2024-10-05", "end": "2024-10-05"})
        default = c.get("/api/data/hourly").json()
        too_long = c.get("/api/data/hourly.csv", params={"start": "2023-01-01", "end": "2024-10-05"})
        bad = c.get("/api/data/hourly", params={"start": "5/10/2024"})
        log_csv = c.get("/api/data/forecast_log.csv")
        docs = c.get("/openapi.json").json()
    p1 = next(s for s in st if s["key"] == "P1")
    assert p1["thaiwater_id"] == 3226 and p1["gauge_zero_msl"] == 300.50
    assert next(s for s in st if s["key"] == "P21")["gauge_zero_msl"] is None   # ยังไม่ยืนยัน ไม่ใส่
    assert len(js["rows"]) == 24 and js["columns"][:3] == ["t_th", "P1_msl", "P1_gauge_m"]
    row12 = dict(zip(js["columns"], js["rows"][12]))
    assert row12["t_th"] == "2024-10-05 12:00" and row12["P1_gauge_m"] == pytest.approx(5.30)
    assert csv.headers["content-type"].startswith("text/csv") and "attachment" in csv.headers["content-disposition"]
    df = pd.read_csv(io.StringIO(csv.text))
    assert len(df) == 24 and df["P1_gauge_m"].max() == pytest.approx(5.30)
    assert default["end"] == "2024-10-09 23:00" or default["end"].startswith("2024-10-")   # ค่าล่าสุดใน seed
    assert too_long.status_code == 422 and bad.status_code == 422
    assert log_csv.status_code == 200 and log_csv.text.startswith("issued_for,")
    assert "/api/data/hourly.csv" in docs["paths"] and "/api/accuracy" in docs["paths"]


def test_health_issues(monkeypatch):
    from app import collector, store, thaiwater
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "COLLECT", True)
    monkeypatch.setattr(collector, "start", lambda: __import__("threading").Event())   # ไม่เปิด thread จริง
    monkeypatch.setattr(collector, "now_th", lambda: T0)

    def boom():
        raise thaiwater.RateLimited("429")
    monkeypatch.setattr(thaiwater, "fetch_latest", boom)
    collector.poll_once()
    _obs(T0 - dt.timedelta(hours=5), [2.0])
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        hl = c.get("/api/health").json()
    codes = [i["code"] for i in hl["issues"]]
    assert codes[:2] == ["no_model", "last_poll_failed"]
    assert "rate_limited_24h" in codes and "backfill_missing" in codes
    stale = [i for i in hl["issues"] if i["code"] == "station_stale"]
    assert {i["station"] for i in stale} == {"P.1", "P.67", "P.21"}
    assert hl["poll"]["counts_24h"]["429"] == 1 and hl["http_429"]["count"] == 1
    assert hl["stations"]["P1"]["age_hours"] == 5.0
