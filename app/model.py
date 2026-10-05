"""โมเดลที่เลือกจากรายงานการทดลอง

- M4 Ridge-delta: ทำนายการเปลี่ยนแปลงของระดับน้ำด้วย Ridge (ใช้สำหรับการเตือนที่ 6 ชม.)
- M6 GBM-delta: ทำนายการเปลี่ยนแปลงด้วย HistGradientBoosting
- M7 ensemble = ค่าเฉลี่ย M4 และ M6 (ใช้แสดงตัวเลขพยากรณ์)

ช่วงความไม่แน่นอน (5–95%, กว้างอย่างน้อย ±RMSE) มาจาก residual ของ blocked cross-validation
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config, features

log = logging.getLogger(__name__)
MIN_SAMPLES = 150
# เปลี่ยนทุกครั้งที่วิธีพยากรณ์เปลี่ยน เพื่อแยกความแม่นของแต่ละรุ่นใน forecast_log
MODEL_VERSION = "2026-10-05.1"
N_FOLDS = 4


def _ridge():
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


def _gbm():
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                         min_samples_leaf=10, random_state=0)


def _dataset(wide: pd.DataFrame, h: int):
    X = features.build(wide)
    y = features.target_delta(wide, h)
    ok = X.notna().all(axis=1) & y.notna()
    return X[ok], y[ok]


def _blocked_oof(X: pd.DataFrame, y: pd.Series, h: int) -> pd.DataFrame:
    """ทำนายแต่ละช่วงเวลาด้วยโมเดลที่ไม่เคยเห็นช่วงนั้น เว้นขอบ h+12 ชม. กันข้อมูลรั่ว"""
    n = len(X)
    edges = np.linspace(0, n, N_FOLDS + 1).astype(int)
    out = []
    t = X.index
    for k in range(N_FOLDS):
        a, b = edges[k], edges[k + 1]
        if b <= a:
            continue
        lo, hi = t[a] - pd.Timedelta(hours=h + 12), t[b - 1] + pd.Timedelta(hours=h + 12)
        tr = (t < lo) | (t > hi)
        if tr.sum() < MIN_SAMPLES // 2:
            continue
        r, g = _ridge().fit(X[tr], y[tr]), _gbm().fit(X[tr], y[tr])
        te = X.iloc[a:b]
        out.append(pd.DataFrame({"y": y.iloc[a:b], "ridge": r.predict(te), "gbm": g.predict(te)}, index=te.index))
    return pd.concat(out) if out else pd.DataFrame(columns=["y", "ridge", "gbm"])


def _rmse_cm(e) -> float:
    return round(float(np.sqrt(np.mean(np.square(e)))) * 100, 1)


def _band(res: pd.Series) -> tuple[float, float]:
    """ช่วง 5–95% ของ residual แต่กว้างอย่างน้อย ±RMSE เพราะข้อมูลเทรนยังน้อย (ดูรายงาน: ช่วงน้ำขึ้นเร็วพลาดได้ถึง 50 ซม.)"""
    spread = _rmse_cm(res) / 100
    return min(float(res.quantile(0.05)), -spread), max(float(res.quantile(0.95)), spread)


def fit_horizon(X: pd.DataFrame, y: pd.Series, h: int) -> dict:
    """fit Ridge + GBM ของ horizon เดียว พร้อมช่วงความไม่แน่นอนจาก blocked CV (ใช้ทั้งแอปและ scripts/backtest.py)"""
    oof = _blocked_oof(X, y, h)
    if len(oof):
        res = {"ridge": oof["y"] - oof["ridge"], "gbm": oof["y"] - oof["gbm"],
               "ensemble": oof["y"] - (oof["ridge"] + oof["gbm"]) / 2}
        bands = {k: _band(r) for k, r in res.items()}
        metrics = {"rmse_cm_ensemble": _rmse_cm(res["ensemble"]), "rmse_cm_ridge": _rmse_cm(res["ridge"]),
                   "rmse_cm_gbm": _rmse_cm(res["gbm"]), "rmse_cm_persistence": _rmse_cm(oof["y"]),
                   "n_oof": int(len(oof))}
    else:
        bands, metrics = {k: (-0.1 * h, 0.1 * h) for k in config.MODEL_KEYS}, {}
    return {"ridge": _ridge().fit(X, y), "gbm": _gbm().fit(X, y),
            "band": bands["ensemble"], "bands": bands, "metrics": metrics, "n_train": int(len(X)),
            "train_range": [str(X.index.min()), str(X.index.max())]}


def train(wide: pd.DataFrame, horizons: list[int] | None = None) -> dict:
    now_th = dt.datetime.now(ZoneInfo("Asia/Bangkok")).replace(tzinfo=None)
    bundle = {"trained_at": now_th.isoformat(timespec="minutes"), "horizons": {},
              "feature_columns": features.FEATURE_COLUMNS, "version": MODEL_VERSION}
    for h in horizons or config.HORIZONS:
        X, y = _dataset(wide, h)
        if len(X) < MIN_SAMPLES:
            raise RuntimeError(f"ข้อมูลไม่พอสำหรับ h={h} ({len(X)} ชั่วโมง ต้องการอย่างน้อย {MIN_SAMPLES})")
        if "p1_range" not in bundle:   # ช่วงระดับ P.1 ที่โมเดลเคยเห็น ใช้บอกผู้ใช้เมื่อน้ำอยู่นอกช่วงนี้
            bundle["p1_range"] = (float(X["p1"].min()), float(X["p1"].max()))
        bundle["horizons"][h] = fit_horizon(X, y, h)
        log.info("trained h=%d on %d hours %s", h, len(X), bundle["horizons"][h]["metrics"])
    return bundle


def _predict_rows(bundle: dict, X: pd.DataFrame, horizons=None) -> dict[int, pd.DataFrame]:
    """ทำนายทุกแถวของ X (ต้องมี feature ครบ) คืน {h: DataFrame} ระดับตามไม้วัด P.1"""
    now = X["p1"]
    out = {}
    for h, m in bundle["horizons"].items():
        if horizons is not None and h not in horizons:
            continue
        r, g = m["ridge"].predict(X), m["gbm"].predict(X)
        df = pd.DataFrame({"now": now, "ridge": now + r, "gbm": now + g}, index=X.index)
        df["ensemble"] = now + (r + g) / 2
        df["lo"], df["hi"] = df["ensemble"] + m["band"][0], df["ensemble"] + m["band"][1]
        if "bands" in m:   # ช่วงของแต่ละโมเดล (bundle รุ่นเก่าไม่มี)
            for k in ("ridge", "gbm"):
                df[f"{k}_lo"], df[f"{k}_hi"] = df[k] + m["bands"][k][0], df[k] + m["bands"][k][1]
        out[int(h)] = df
    return out


def predict_frame(bundle: dict, wide: pd.DataFrame, horizons=None) -> dict[int, pd.DataFrame]:
    """ทำนายทุกชั่วโมงที่มี feature ครบ (ใช้ใน backtest) แถวที่ feature ไม่ครบไม่ถูกทำนาย เหมือนแอปจริง"""
    X = features.build(wide)
    return _predict_rows(bundle, X[X.notna().all(axis=1)], horizons)


def save(bundle: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, config.MODEL_PATH)


def load() -> dict | None:
    try:
        return joblib.load(config.MODEL_PATH)
    except FileNotFoundError:
        return None


def p1_range(bundle: dict, wide_all: pd.DataFrame | None = None) -> tuple[float, float] | None:
    """ช่วงระดับ P.1 (ตามไม้วัด) ในข้อมูลเทรน bundle รุ่นเก่าไม่มีค่านี้ จึงคำนวณจาก train_range แทน"""
    if "p1_range" in bundle:
        return tuple(bundle["p1_range"])
    if wide_all is None:
        return None
    a, b = (pd.Timestamp(t) for t in bundle["horizons"][config.HORIZONS[0]]["train_range"])
    s = features.gauge_p1(wide_all.loc[a:b]).dropna()
    return (float(s.min()), float(s.max())) if len(s) else None


def predict(bundle: dict, wide: pd.DataFrame) -> dict | None:
    """พยากรณ์จากชั่วโมงล่าสุดที่มี feature ครบ"""
    X = features.build(wide)
    ok = X.notna().all(axis=1)
    if not ok.any():
        return None
    t0 = X.index[ok][-1]
    rows = _predict_rows(bundle, X.loc[[t0]])
    out = {"issued_for": t0, "now_m": float(X.at[t0, "p1"]), "horizons": {}}
    for h, df in rows.items():
        r = df.iloc[0]
        p = {"ensemble_m": r["ensemble"], "ridge_m": r["ridge"], "gbm_m": r["gbm"], "lo_m": r["lo"], "hi_m": r["hi"]}
        for k in ("ridge", "gbm"):
            if f"{k}_lo" in df:
                p[f"{k}_lo_m"], p[f"{k}_hi_m"] = r[f"{k}_lo"], r[f"{k}_hi"]
        out["horizons"][h] = {k: float(v) for k, v in p.items()}
    return out


def is_current(bundle: dict) -> bool:
    """bundle ที่เทรนก่อนเพิ่ม horizon รายชั่วโมงหรือช่วงรายโมเดล ต้องเทรนใหม่"""
    hs = bundle.get("horizons", {})
    return set(hs) == set(config.HORIZONS) and all("bands" in m for m in hs.values())
