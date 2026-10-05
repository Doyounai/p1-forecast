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


def train(wide: pd.DataFrame) -> dict:
    now_th = dt.datetime.now(ZoneInfo("Asia/Bangkok")).replace(tzinfo=None)
    bundle = {"trained_at": now_th.isoformat(timespec="minutes"), "horizons": {},
              "feature_columns": features.FEATURE_COLUMNS}
    for h in config.HORIZONS:
        X, y = _dataset(wide, h)
        if len(X) < MIN_SAMPLES:
            raise RuntimeError(f"ข้อมูลไม่พอสำหรับ h={h} ({len(X)} ชั่วโมง ต้องการอย่างน้อย {MIN_SAMPLES})")
        if "p1_range" not in bundle:   # ช่วงระดับ P.1 ที่โมเดลเคยเห็น ใช้บอกผู้ใช้เมื่อน้ำอยู่นอกช่วงนี้
            bundle["p1_range"] = (float(X["p1"].min()), float(X["p1"].max()))
        oof = _blocked_oof(X, y, h)
        if len(oof):
            ens = (oof["ridge"] + oof["gbm"]) / 2
            res = oof["y"] - ens
            rmse = lambda e: round(float(np.sqrt(np.mean(np.square(e)))) * 100, 1)
            # ช่วง 5–95% แต่กว้างอย่างน้อย ±RMSE เพราะข้อมูลเทรนยังน้อย (ดูรายงาน: ช่วงน้ำขึ้นเร็วพลาดได้ถึง 50 ซม.)
            spread = rmse(res) / 100
            q_lo, q_hi = min(float(res.quantile(0.05)), -spread), max(float(res.quantile(0.95)), spread)
            metrics = {"rmse_cm_ensemble": rmse(res), "rmse_cm_ridge": rmse(oof["y"] - oof["ridge"]),
                       "rmse_cm_persistence": rmse(oof["y"]), "n_oof": int(len(oof))}
        else:
            q_lo, q_hi, metrics = -0.1 * h, 0.1 * h, {}
        bundle["horizons"][h] = {
            "ridge": _ridge().fit(X, y), "gbm": _gbm().fit(X, y),
            "band": (q_lo, q_hi), "metrics": metrics, "n_train": int(len(X)),
            "train_range": [str(X.index.min()), str(X.index.max())],
        }
        log.info("trained h=%d on %d hours %s", h, len(X), metrics)
    return bundle


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
    x = X.loc[[t0]]
    now = float(x["p1"].iloc[0])
    out = {"issued_for": t0, "now_m": now, "horizons": {}}
    for h, m in bundle["horizons"].items():
        r = float(m["ridge"].predict(x)[0])
        g = float(m["gbm"].predict(x)[0])
        ens = now + (r + g) / 2
        lo, hi = m["band"]
        out["horizons"][int(h)] = {"ensemble_m": ens, "ridge_m": now + r, "lo_m": ens + lo, "hi_m": ens + hi}
    return out
