import datetime as dt

import pandas as pd
import pytest

from app import config, forecast_logic as fl

T0 = dt.datetime(2024, 10, 3, 7, 0)
L = {"watch": 3.10, "critical": 3.70, "overflow": 4.20}


def _pred(now_m, ens, band=0.10, ridge=None):
    """ens = {h: ค่า ensemble}; ช่วง = ens ± band; ridge = ens ถ้าไม่ระบุ"""
    ridge = ridge or {}
    return {"issued_for": pd.Timestamp(T0), "now_m": now_m, "horizons": {
        h: {"ensemble_m": v, "ridge_m": ridge.get(h, v), "lo_m": v - band, "hi_m": v + band}
        for h, v in ens.items()}}


@pytest.fixture(autouse=True)
def levels(monkeypatch):
    monkeypatch.setattr(config, "LEVELS", dict(L))


def test_status_boundaries():
    assert [fl.status(v) for v in (3.09, 3.10, 3.70, 4.19, 4.20)] == \
        ["normal", "watch", "critical", "critical", "overflow"]


def test_first_crossing_interpolates():
    pts = [(0, 3.0), (1, 3.2), (3, 3.6), (6, 4.2)]
    assert fl.first_crossing(pts, 3.1) == pytest.approx(0.5)
    assert fl.first_crossing(pts, 3.9) == pytest.approx(4.5)
    assert fl.first_crossing(pts, 5.0) is None
    assert fl.first_crossing(pts, 2.0) == 0


def test_next_threshold_window_from_band():
    # ensemble ข้าม 3.70 ระหว่าง 3–6 ชม.; hi ข้ามที่ ~3.4 ชม. (ปัดลง), lo ข้ามที่ ~5.1 ชม. (ปัดขึ้น)
    p = _pred(3.30, {1: 3.40, 3: 3.55, 6: 3.90, 12: 4.2}, band=0.10)
    nt = fl.next_threshold(p)
    assert nt["key"] == "critical" and nt["level_m"] == 3.70
    assert nt["earliest"] == "2024-10-03T10:00"
    assert nt["latest"] == "2024-10-03T13:00"
    assert nt["open_end"] is False


def test_next_threshold_open_end_and_never_beyond_6h():
    p = _pred(3.30, {1: 3.35, 3: 3.50, 6: 3.72, 12: 4.5}, band=0.15)
    nt = fl.next_threshold(p)
    assert nt["open_end"] is True
    assert nt["latest"] == "2024-10-03T13:00"                         # ปลาย 6 ชม. พอดี ไม่เกิน
    # 12 ชม. ข้ามเกณฑ์แต่ 6 ชม. ไม่ข้าม → ไม่แสดง (ห้ามประมาณเกิน 6 ชม.)
    assert fl.next_threshold(_pred(3.30, {1: 3.31, 3: 3.33, 6: 3.40, 12: 3.9}, band=0.05)) is None


def test_next_threshold_uses_m4_ridge_for_warning():
    p = _pred(3.30, {1: 3.35, 3: 3.45, 6: 3.60, 12: 3.8}, band=0.05, ridge={6: 3.75})
    nt = fl.next_threshold(p)
    assert nt is not None and nt["key"] == "critical"


def test_next_threshold_none_above_overflow_or_no_pred():
    assert fl.next_threshold(_pred(4.5, {1: 4.6, 3: 4.7, 6: 4.8, 12: 4.9})) is None
    assert fl.next_threshold(None) is None


def test_eta_clamped_to_now():
    p = _pred(3.30, {1: 3.60, 3: 3.80, 6: 3.90, 12: 4.0}, band=0.10)
    e = fl.eta(p, 3.70, now=T0 + dt.timedelta(hours=1, minutes=40))
    assert e["earliest"] == "2024-10-03T08:00"


def test_my_level_near_and_far():
    p = _pred(3.30, {1: 3.40, 3: 3.60, 6: 3.90, 12: 4.2}, band=0.10)
    near = fl.my_level(p, 4.15, 3.30)
    assert near["near"] is True and near["reached"] is False and near["eta"] is None   # ขอบบน 4.00 ≥ 4.15 − 0.30
    hit = fl.my_level(p, 3.80, 3.30)
    assert hit["eta"] is not None
    far = fl.my_level(p, 5.0, 3.30)
    assert far["near"] is False and far["eta"] is None
    assert fl.my_level(p, 3.0, 3.30)["reached"] is True


def test_advice_status_takes_higher_of_now_and_m4():
    p = _pred(3.30, {1: 3.4, 3: 3.5, 6: 3.6, 12: 3.7}, ridge={6: 3.75})
    assert fl.advice_status(3.30, p) == ("critical", "forecast6")
    assert fl.advice_status(4.30, p) == ("overflow", "now")
    assert fl.advice_status(2.0, None) == ("normal", "now")


def _wide(hours_p67_missing=0):
    idx = pd.date_range(T0 - dt.timedelta(hours=10), T0, freq="h")
    w = pd.DataFrame({"P1": 303.0, "P67": 316.0, "P21": 321.0}, index=idx)
    if hours_p67_missing:
        w.loc[w.index[-hours_p67_missing:], "P67"] = None
    return w


def test_reliability_reasons():
    p = _pred(3.30, {1: 3.4, 3: 3.5, 6: 3.6, 12: 3.7})
    ok = fl.reliability(3.30, (1.76, 4.93), _wide(), T0, p, False, 0.5)
    assert ok == {"low": False, "reasons": []}
    r = fl.reliability(5.25, (1.76, 4.93), _wide(hours_p67_missing=5), T0, None, True, 2.5)
    codes = [x["code"] for x in r["reasons"]]
    assert r["low"] and codes == ["out_of_train_range", "upstream_missing", "no_forecast", "stale"]
    assert r["reasons"][0]["side"] == "above" and r["reasons"][1]["stations"] == ["P.67"]
    below = fl.reliability(0.80, (1.76, 4.93), _wide(), T0, p, False, 0)
    assert below["reasons"][0]["side"] == "below"


def test_api_demo_new_fields(monkeypatch):
    from app import collector
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "COLLECT", False)
    collector.ensure_seed()
    collector.retrain()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        peak = c.get("/api/forecast", params={"at": "2024-10-05 02:00", "my": 5.0}).json()
        calm = c.get("/api/forecast", params={"at": "2024-09-29 12:00"}).json()
        bad = c.get("/api/forecast", params={"my": 99})
    # โมเดลสาธิตเทรนก่อน 3 ต.ค. 07:00 ยอดที่เคยเห็นคือ E1 (4.93 ม.) → 5.25 ม. อยู่นอกช่วง
    assert peak["reliability"]["low"] is True
    assert peak["reliability"]["reasons"][0]["code"] == "out_of_train_range"
    assert peak["advice"] == {"status": "overflow", "basis": "now"}
    assert peak["my_level"]["reached"] is True
    assert peak["p1"]["age_minutes"] >= 0 and peak["p1"]["stale"] is False
    tr = peak["upstream"][0]["travel"]
    assert (tr["hours_min"], tr["hours_max"]) == (6, 6) and tr["source"]
    assert calm["my_level"] is None and calm["advice"]["status"] in fl.STATUS_ORDER
    assert bad.status_code == 422


def test_model_table_hourly_each_model(monkeypatch):
    from app import collector
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "COLLECT", False)
    collector.ensure_seed()
    collector.retrain()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        d = c.get("/api/forecast", params={"at": "2024-10-03 07:00"}).json()
    tab = d["model_table"]
    assert [r["h"] for r in tab["rows"]] == [1, 2, 3, 4, 5, 6]          # รายชั่วโมง ไม่เกิน 6 ชม.
    for r in tab["rows"]:
        for k in ("ridge", "gbm", "ensemble"):
            cell = r["models"][k]
            assert cell["lo_m"] <= cell["value_m"] <= cell["hi_m"]       # ทุกค่ามีช่วงความไม่แน่นอน
            assert cell["rmse_cm"] is not None
    # ค่า ensemble ในตารางต้องตรงกับตัวเลขที่แสดงด้านบน
    top = {f["h"]: f["value_m"] for f in d["forecast"]}
    assert all(tab["rows"][h - 1]["models"]["ensemble"]["value_m"] == v for h, v in top.items())


def test_outdated_bundle_is_retrained(monkeypatch):
    from app import collector, model
    b = {"horizons": {h: {"bands": {}} for h in (1, 3, 6, 12)}}
    assert model.is_current(b) is False
    called = []
    monkeypatch.setattr(model, "load", lambda: b)
    monkeypatch.setattr(collector, "retrain", lambda: called.append(1))
    collector.ensure_model()
    assert called == [1]


def test_display_status_follows_rounded_value():
    from app.main import _r, _status
    assert _status(_r(3.698)) == "critical"     # แสดง 3.70 ต้องเป็นสีวิกฤต ไม่ใช่เฝ้าระวัง
