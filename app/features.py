"""สร้าง features แบบเดียวกับในรายงานการทดลอง (M4/M6/M7)

ทุก feature ใช้เฉพาะข้อมูลที่รู้ ณ เวลา t
- P.1: ระดับตามไม้วัด และการเปลี่ยนแปลงย้อนหลัง 1, 3, 6 ชม.
- P.67, P.21: ระดับเทียบตลิ่งที่ lag 0–12 ชม. (ทุก 2 ชม.) และการเปลี่ยนแปลงย้อนหลัง 1, 3, 6 ชม.
"""
from __future__ import annotations

import pandas as pd

from . import config

LAGS = (0, 2, 4, 6, 8, 10, 12)
DIFFS = (1, 3, 6)
MAX_GAP_FILL = 3   # เติมช่องว่างได้ไม่เกิน 3 ชม. (เช่นช่วง 23:00–00:00 ที่มักหาย)


def gauge_p1(wide: pd.DataFrame) -> pd.Series:
    return wide["P1"] - config.P1_GAUGE_ZERO_MSL


def build(wide: pd.DataFrame) -> pd.DataFrame:
    d = wide.interpolate(limit=MAX_GAP_FILL, limit_area="inside")
    X = pd.DataFrame(index=d.index)
    p1 = d["P1"] - config.P1_GAUGE_ZERO_MSL
    X["p1"] = p1
    for w in DIFFS:
        X[f"p1_d{w}"] = p1 - p1.shift(w)
    for key in ("P67", "P21"):
        g = d[key] - config.STATIONS[key]["bank_msl"]
        for L in LAGS:
            X[f"{key}_l{L}"] = g.shift(L)
        for w in DIFFS:
            X[f"{key}_d{w}"] = g - g.shift(w)
    return X


def target_delta(wide: pd.DataFrame, h: int) -> pd.Series:
    """การเปลี่ยนแปลงของระดับ P.1 จาก t ถึง t+h ใช้เฉพาะค่าที่วัดได้จริง (ไม่ใช่ค่าที่เติม)"""
    obs = gauge_p1(wide)
    now = gauge_p1(wide.interpolate(limit=MAX_GAP_FILL, limit_area="inside"))
    return obs.shift(-h) - now


FEATURE_COLUMNS = list(build(pd.DataFrame(columns=list(config.STATIONS), dtype=float)).columns)
