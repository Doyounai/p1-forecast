"""เว็บพยากรณ์ระดับน้ำปิง สถานี P.1 สะพานนวรัฐ — เวอร์ชันแรก

รัน:  uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import datetime as dt
import logging
import math
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import collector, config, features, forecast_logic, model, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = collector.start()
    yield
    stop.set()


app = FastAPI(title="P.1 Ping River forecast", lifespan=lifespan)


def _r(v, n=2):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), n)


_status = forecast_logic.status


def _now(at: str | None) -> dt.datetime:
    if config.DEMO:
        return dt.datetime.fromisoformat(at or config.DEMO_NOW)
    return collector.now_th()


def _travel(st: dict) -> dict:
    tr = st.get("travel") or {}
    lo, hi = tr.get("hours") or (None, None)
    return {"hours_min": lo, "hours_max": hi, "source": tr.get("source", "")}


def _upstream(wide: pd.DataFrame) -> list[dict]:
    out = []
    for key in config.MODEL_UPSTREAM:
        st = config.STATIONS[key]
        item = {"key": key, "code": st["code"], "name": st["name"], "river": st["river"], "travel": _travel(st)}
        s = wide[key].dropna()
        if not s.empty:
            t, v = s.index[-1], s.iloc[-1]
            prev = s[s.index <= t - pd.Timedelta(hours=3)]
            item.update({"t": t.isoformat(), "vs_bank_m": _r(v - st["bank_msl"]),
                         "change_3h_m": _r(v - prev.iloc[-1]) if len(prev) else None})
        out.append(item)
    return out


def _p1_range(bundle: dict):
    rng = model.p1_range(bundle)
    if rng is None:
        a, b = (pd.Timestamp(t).to_pydatetime() for t in bundle["horizons"][config.HORIZONS[0]]["train_range"])
        rng = model.p1_range(bundle, store.hourly(start=a, end=b))
    return rng


@app.get("/api/forecast")
def forecast(at: str | None = Query(None, description="เฉพาะโหมดสาธิต: เวลาที่ต้องการดู 'YYYY-MM-DD HH:MM'"),
             my: float | None = Query(None, ge=0, le=10, description="ระดับน้ำของผู้ใช้ (ม. ตามไม้วัด P.1)")):
    bundle = model.load()
    if bundle is None:
        raise HTTPException(503, "กำลังเตรียมโมเดลครั้งแรก รอประมาณ 1 นาทีแล้วรีเฟรชหน้า")
    now = _now(at)
    wide = store.hourly(start=now - dt.timedelta(days=4), end=now)
    if wide["P1"].dropna().empty:
        raise HTTPException(503, "ยังไม่มีข้อมูลระดับน้ำ P.1 ในช่วง 4 วันที่ผ่านมา ตรวจการเชื่อมต่อ ThaiWater")

    p1 = features.gauge_p1(wide).dropna()
    last_t, last_v = p1.index[-1], float(p1.iloc[-1])
    age_h = (now - last_t.to_pydatetime()).total_seconds() / 3600
    pred = model.predict(bundle, wide)

    fc, warning, trend = [], None, None
    if pred:
        t0 = pred["issued_for"]
        for h in config.NUMERIC_HORIZONS:
            p = pred["horizons"][h]
            m = bundle["horizons"][h]["metrics"]
            fc.append({"h": h, "t": (t0 + pd.Timedelta(hours=h)).isoformat(), "value_m": _r(p["ensemble_m"]),
                       "lo_m": _r(p["lo_m"]), "hi_m": _r(p["hi_m"]), "status": _status(p["ensemble_m"]),
                       "rmse_cm": m.get("rmse_cm_ensemble")})
        d12 = pred["horizons"][12]["ensemble_m"] - pred["now_m"]
        trend = {"h": 12, "change_m": _r(d12), "direction": "rising" if d12 > 0.15 else "falling" if d12 < -0.15 else "steady"}
        crit = config.LEVELS["critical"]
        w = pred["horizons"][config.WARNING_HORIZON]
        if pred["now_m"] < crit:
            if w["ridge_m"] >= crit:
                warning = {"level": "likely", "h": config.WARNING_HORIZON, "value_m": _r(w["ridge_m"])}
            elif w["hi_m"] >= crit:
                warning = {"level": "possible", "h": config.WARNING_HORIZON, "value_m": _r(w["hi_m"])}

    hist = p1[p1.index >= now - pd.Timedelta(hours=72)]
    fetch = store.get_meta("last_fetch")
    stale = (not config.DEMO) and age_h > config.STALE_AFTER_HOURS
    adv, basis = forecast_logic.advice_status(last_v, pred)
    return {
        "mode": "demo" if config.DEMO else "live",
        "now": now.isoformat(timespec="minutes"),
        "levels": config.LEVELS,
        "p1": {"t": last_t.isoformat(), "level_m": _r(last_v), "level_msl": _r(last_v + config.P1_GAUGE_ZERO_MSL),
               "status": _status(last_v), "age_hours": _r(age_h, 1), "age_minutes": max(0, round(age_h * 60)),
               "stale": stale,
               "discharge_m3s": None if config.DEMO else _r(store.latest_discharge().get("P1"), 1)},
        "forecast": fc,
        "trend12": trend,
        "warning": warning,
        "next_threshold": forecast_logic.next_threshold(pred, now=now),
        "my_level": forecast_logic.my_level(pred, my, last_v, now=now) if my is not None else None,
        "advice": {"status": adv, "basis": basis},
        "reliability": forecast_logic.reliability(last_v, _p1_range(bundle), wide, now, pred, stale, age_h),
        "history": [{"t": t.isoformat(), "m": _r(v)} for t, v in hist.items()],
        "upstream": _upstream(wide),
        "model": {"trained_at": bundle["trained_at"],
                  "train_hours": bundle["horizons"][1]["n_train"],
                  "train_range": bundle["horizons"][1]["train_range"]},
        "fetch": fetch,
        "demo_range": _demo_range() if config.DEMO else None,
    }


def _demo_range():
    idx = store.hourly().dropna(subset=["P1"]).index
    return [idx.min().isoformat(), idx.max().isoformat()]


@app.get("/api/health")
def health():
    return {"mode": "demo" if config.DEMO else "live", "model": model.load() is not None,
            "hours_stored": store.count_hours(), "last_fetch": store.get_meta("last_fetch"),
            "last_train": store.get_meta("last_train"), "backfill": store.get_meta("backfill")}


app.mount("/", StaticFiles(directory=config.ROOT / "static", html=True), name="static")
