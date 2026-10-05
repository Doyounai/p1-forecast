import datetime as dt
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(config, "MODEL_PATH", tmp_path / "m.joblib")
    yield


def test_parse_waterlevel_load_real_payload():
    from app import thaiwater
    rows = thaiwater.parse_waterlevel_load(json.loads((FIX / "waterlevel_load_sample.json").read_text(encoding="utf-8")))
    by = {r["station_id"]: r for r in rows}
    assert set(by) == {3226, 3247, 3240}            # สถานีอื่นถูกกรองออก
    assert by[3226]["level_msl"] == 301.68 and by[3226]["t"] == dt.datetime(2026, 9, 27, 16, 0)
    assert by[3226]["discharge"] == 89.12


def test_parse_waterlevel_graph_and_errors():
    from app import thaiwater
    payload = {"data": {"graph_data": [
        {"datetime": "2026-09-27 07:00", "value": 301.5, "discharge": 80},
        {"datetime": "2026-09-27 08:00", "value": None},
        {"datetime": "2026-09-27 09:00", "value": 999999}]}}
    rows = thaiwater.parse_waterlevel_graph(3226, payload)
    assert [(r["t"].hour, r["level_msl"]) for r in rows] == [(7, 301.5)]
    with pytest.raises(ValueError):
        thaiwater.parse_waterlevel_graph(3226, "Too many requests")


def test_hourly_prefers_on_the_hour_reading():
    from app import store
    t = dt.datetime(2026, 9, 27, 7, 0)
    store.upsert([{"station_id": 3226, "t": t + dt.timedelta(minutes=10), "level_msl": 302.0},
                  {"station_id": 3226, "t": t, "level_msl": 301.0},
                  {"station_id": 3226, "t": t + dt.timedelta(hours=2), "level_msl": 301.2}], "test")
    w = store.hourly()
    assert w.loc[t, "P1"] == 301.0
    assert len(w) == 3                                 # เติมชั่วโมงที่หายเป็น NaN


def test_train_and_predict_on_seed():
    from app import collector, model, store
    collector.ensure_seed()
    b = model.train(store.hourly())
    for h in (1, 3, 6, 12):
        m = b["horizons"][h]["metrics"]
        assert m["rmse_cm_ensemble"] < m["rmse_cm_persistence"]   # ต้องดีกว่าการทายว่าเท่าเดิม
    p = model.predict(b, store.hourly(end=dt.datetime(2024, 10, 3, 7)))
    assert p["issued_for"] == dt.datetime(2024, 10, 3, 7)
    h6 = p["horizons"][6]
    assert h6["lo_m"] < h6["ensemble_m"] < h6["hi_m"]


def test_api_demo(monkeypatch):
    from app import collector, config
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "COLLECT", False)
    collector.ensure_seed()
    collector.retrain()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        d = c.get("/api/forecast", params={"at": "2024-10-05 02:00"}).json()
    assert d["p1"]["level_m"] == 5.25 and d["p1"]["status"] == "overflow"
    assert [f["h"] for f in d["forecast"]] == [1, 3, 6]
    assert d["trend12"]["direction"] in {"rising", "falling", "steady"}
    assert len(d["upstream"]) == 2


def test_live_mode_with_mocked_thaiwater(monkeypatch):
    """จำลองการรันจริง: backfill + poll ด้วยข้อมูลปลอมที่ย้ายเวลามาเป็นปี 2569"""
    from app import collector, config, store, thaiwater
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "COLLECT", False)       # ไม่ให้ thread เบื้องหลังเรียกเน็ต
    shift = dt.datetime(2026, 9, 25, 1) - dt.datetime(2024, 9, 22, 1)
    seed = [dict(r, t=r["t"] + shift) for r in store.load_seed()]
    monkeypatch.setattr(thaiwater, "fetch_history",
                        lambda sid, days=365, end=None: [r for r in seed if r["station_id"] == sid and r["t"] <= end])
    monkeypatch.setattr(thaiwater, "fetch_latest", lambda: [])
    now = dt.datetime(2026, 10, 1, 8, 30)
    monkeypatch.setattr(collector, "now_th", lambda: now)
    monkeypatch.setattr(collector.time, "sleep", lambda s: None)
    collector.ensure_seed()                           # ระบบจริงโหลด seed ปี 2567 ทุกครั้งก่อน backfill
    res = collector.backfill()
    assert all(isinstance(v, int) and v > 0 for v in res.values())
    collector.poll_once()
    assert store.get_meta("last_fetch")["ok"] is True
    collector.retrain()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        d = c.get("/api/forecast").json()
    assert d["mode"] == "live" and d["p1"]["stale"] is False and len(d["forecast"]) == 3
    monkeypatch.setattr(collector, "now_th", lambda: now + dt.timedelta(hours=5))
    with TestClient(app) as c:
        assert c.get("/api/forecast").json()["p1"]["stale"] is True
