"""บันทึกพยากรณ์ที่ออกจริงทุกครั้ง แล้วเทียบกับค่าจริงเมื่อมาถึง

- record(): เก็บพยากรณ์ของทุกโมเดลทุก horizon ครั้งแรกของแต่ละ issued_for (ครั้งหลังไม่ทับ)
  ข้ามถ้า issued_for เก่ากว่า LOG_MAX_DELAY_HOURS เพราะนั่นคือการทายย้อนหลัง ไม่ใช่พยากรณ์จริง
- score(): เติม actual_m จากค่าที่วัดได้จริงที่ target_t (ไม่ใช้ค่าที่เติมช่องว่าง)
- summary(): สรุปความแม่นย้อนหลังแยกตาม horizon และโมเดล
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import config, features, store

FMT = "%Y-%m-%d %H:%M"


def record(bundle: dict, pred: dict | None, now: dt.datetime) -> int:
    if not pred:
        return 0
    t0 = pd.Timestamp(pred["issued_for"]).to_pydatetime()
    if now - t0 > dt.timedelta(hours=config.LOG_MAX_DELAY_HOURS):
        return 0
    rows = []
    for h, p in pred["horizons"].items():
        for k in config.MODEL_KEYS:
            lo, hi = (p["lo_m"], p["hi_m"]) if k == "ensemble" else (p.get(f"{k}_lo_m"), p.get(f"{k}_hi_m"))
            rows.append((t0.strftime(FMT), int(h), k, (t0 + dt.timedelta(hours=int(h))).strftime(FMT),
                         pred["now_m"], p[f"{k}_m"], lo, hi, bundle.get("trained_at"), now.strftime(FMT)))
    with store.connect() as con:
        cur = con.executemany(
            "INSERT OR IGNORE INTO forecast_log (issued_for, h, model, target_t, now_m, pred_m, lo_m, hi_m, "
            "trained_at, logged_at) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        return cur.rowcount


def score() -> int:
    """เติมค่าจริงให้พยากรณ์ที่ถึงเวลาแล้ว คืนจำนวนแถวที่เติม"""
    with store.connect() as con:
        pending = [r[0] for r in con.execute(
            "SELECT DISTINCT target_t FROM forecast_log WHERE actual_m IS NULL ORDER BY target_t").fetchall()]
    if not pending:
        return 0
    wide = store.hourly(start=dt.datetime.strptime(pending[0], FMT), end=dt.datetime.strptime(pending[-1], FMT))
    obs = features.gauge_p1(wide).dropna() if len(wide) else pd.Series(dtype=float)
    upd = [(float(obs[pd.Timestamp(t)]), float(obs[pd.Timestamp(t)]), t)
           for t in pending if pd.Timestamp(t) in obs.index]
    if not upd:
        return 0
    with store.connect() as con:
        cur = con.executemany("UPDATE forecast_log SET actual_m=?, err_m=pred_m-? WHERE target_t=? AND actual_m IS NULL", upd)
        return cur.rowcount


def _cm(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x) * 100, 1)


def _stats(df: pd.DataFrame) -> dict:
    e = df["err_m"]
    inside = df.dropna(subset=["lo_m", "hi_m"])
    return {"n": int(len(df)), "rmse_cm": _cm(np.sqrt(np.mean(np.square(e)))), "mae_cm": _cm(np.mean(np.abs(e))),
            "bias_cm": _cm(np.mean(e)), "max_under_cm": _cm(-e.min()) if (e < 0).any() else 0.0,
            "max_over_cm": _cm(e.max()) if (e > 0).any() else 0.0,
            "coverage": round(float(((inside["actual_m"] >= inside["lo_m"]) & (inside["actual_m"] <= inside["hi_m"])).mean()), 3)
            if len(inside) else None}


def _direction(change: pd.Series) -> pd.Series:
    return np.where(change > 0.15, "rising", np.where(change < -0.15, "falling", "steady"))


def load(start: dt.datetime | None = None, end: dt.datetime | None = None) -> pd.DataFrame:
    q, args = "SELECT * FROM forecast_log WHERE 1=1", []
    if start is not None:
        q += " AND target_t >= ?"; args.append(start.strftime(FMT))
    if end is not None:
        q += " AND target_t <= ?"; args.append(end.strftime(FMT))
    with store.connect() as con:
        return pd.read_sql_query(q + " ORDER BY target_t, h, model", con, params=args)


def summary(now: dt.datetime, days: int, series_h: int = 6) -> dict:
    """ความแม่นของพยากรณ์ที่ค่าจริงมาถึงแล้ว ในช่วง days วันล่าสุด (นับตามเวลาเป้าหมาย)"""
    start = now - dt.timedelta(days=days)
    df = load(start=start, end=now)
    done = df.dropna(subset=["actual_m"])
    horizons = []
    for h in config.TABLE_HORIZONS:
        d = done[done["h"] == h]
        if d.empty:
            horizons.append({"h": h, "n": 0})
            continue
        by_model = {k: _stats(d[d["model"] == k]) for k in config.MODEL_KEYS if (d["model"] == k).any()}
        ens = d[d["model"] == "ensemble"]
        persist = ens["now_m"] - ens["actual_m"]   # การทายว่าเท่าเดิม = ใช้ระดับตอนออกพยากรณ์
        horizons.append({"h": h, "n": int(len(ens)), "models": by_model,
                         "persistence_rmse_cm": _cm(np.sqrt(np.mean(np.square(persist)))) if len(ens) else None})
    d12 = done[(done["h"] == 12) & (done["model"] == "ensemble")]
    trend12 = None
    if len(d12):
        hit = _direction(d12["pred_m"] - d12["now_m"]) == _direction(d12["actual_m"] - d12["now_m"])
        trend12 = {"n": int(len(d12)), "hit_rate": round(float(hit.mean()), 3)}
    s = df[(df["h"] == series_h) & (df["model"] == "ensemble")]
    series = [{"t": r.target_t, "issued_for": r.issued_for, "pred_m": round(r.pred_m, 2),
               "lo_m": None if pd.isna(r.lo_m) else round(r.lo_m, 2), "hi_m": None if pd.isna(r.hi_m) else round(r.hi_m, 2),
               "actual_m": None if pd.isna(r.actual_m) else round(r.actual_m, 2)} for r in s.itertuples()]
    return {"days": days, "from": start.strftime(FMT), "to": now.strftime(FMT), "horizons": horizons,
            "trend12": trend12, "series_h": series_h, "series": series,
            "pending": int(df.loc[df["model"] == "ensemble", "actual_m"].isna().sum()),
            "first_logged": first_logged()}


def first_logged() -> str | None:
    with store.connect() as con:
        return con.execute("SELECT MIN(logged_at) FROM forecast_log").fetchone()[0]


def counts() -> dict:
    with store.connect() as con:
        n, scored, last = con.execute(
            "SELECT COUNT(DISTINCT issued_for), COUNT(DISTINCT CASE WHEN actual_m IS NOT NULL THEN issued_for || h END), "
            "MAX(issued_for) FROM forecast_log WHERE model='ensemble'").fetchone()
        pend = con.execute("SELECT COUNT(*) FROM forecast_log WHERE model='ensemble' AND actual_m IS NULL").fetchone()[0]
    return {"issued": n, "scored_pairs": scored, "pending": pend, "last_issued_for": last, "first_logged": first_logged()}
