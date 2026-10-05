"""ตีความผลพยากรณ์ให้เป็นสิ่งที่หน้าเว็บใช้ได้ทันที (ฟังก์ชันล้วน ไม่แตะฐานข้อมูล)

- สถานะตามเกณฑ์ และสถานะที่ใช้เลือกคำแนะนำ
- เวลาที่อาจถึงเกณฑ์ถัดไป (หรือระดับน้ำของผู้ใช้) จากค่าพยากรณ์และช่วงความไม่แน่นอน ไม่เกิน 6 ชม.
- เหตุที่ทำให้ตัวเลขพยากรณ์เชื่อถือได้น้อยลง
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from . import config

STATUS_ORDER = ["normal", "watch", "critical", "overflow"]
THRESHOLD_KEYS = ["watch", "critical", "overflow"]


def status(level_m: float, levels: dict | None = None) -> str:
    L = levels or config.LEVELS
    for key in reversed(THRESHOLD_KEYS):
        if level_m >= L[key]:
            return key
    return "normal"


def _rank(s: str) -> int:
    return STATUS_ORDER.index(s)


def _path(pred: dict, field: str) -> list[tuple[float, float]]:
    """จุด (ชั่วโมงจาก issued_for, ค่า) เริ่มจากค่าปัจจุบันที่ 0 ชม. จนถึง horizon การเตือน"""
    pts = [(0.0, pred["now_m"])]
    for h in sorted(pred["horizons"]):
        if h <= config.WARNING_HORIZON:
            pts.append((float(h), pred["horizons"][h][field]))
    return pts


def _upper(pred: dict) -> list[tuple[float, float]]:
    """ขอบบนของช่วง: ใช้ค่าที่สูงกว่าระหว่าง hi ของ ensemble กับ M4 ridge (M4 ใช้สำหรับการเตือน)"""
    hi, ridge = _path(pred, "hi_m"), _path(pred, "ridge_m")
    return [(h, max(a, b)) for (h, a), (_, b) in zip(hi, ridge)]


def first_crossing(points: list[tuple[float, float]], threshold: float) -> float | None:
    """ชั่วโมงแรกที่เส้น (interpolate เชิงเส้น) ขึ้นถึง threshold, None ถ้าไม่ถึง"""
    if points[0][1] >= threshold:
        return points[0][0]
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if v1 >= threshold > v0:
            return h0 + (threshold - v0) / (v1 - v0) * (h1 - h0)
    return None


def eta(pred: dict, threshold: float, now: dt.datetime | None = None) -> dict | None:
    """ช่วงเวลาที่อาจถึง threshold ภายใน WARNING_HORIZON ชม.

    earliest = ขอบบนของช่วงถึงเกณฑ์, latest = ขอบล่างถึงเกณฑ์
    ถ้าขอบล่างไม่ถึงภายใน 6 ชม. ใช้ปลาย 6 ชม. และ open_end=True (อาจช้ากว่านั้นหรือไม่ถึงเลย)
    """
    h_early = first_crossing(_upper(pred), threshold)
    if h_early is None:
        return None
    h_late = first_crossing(_path(pred, "lo_m"), threshold)
    open_end = h_late is None
    H = config.WARNING_HORIZON
    t0 = pd.Timestamp(pred["issued_for"]).to_pydatetime()
    early = t0 + dt.timedelta(hours=math.floor(h_early))
    late = t0 + dt.timedelta(hours=H if open_end else min(H, math.ceil(h_late)))
    if now is not None:
        early = max(early, now.replace(minute=0, second=0, microsecond=0))
    if late <= early:
        late = min(early + dt.timedelta(hours=1), t0 + dt.timedelta(hours=H))
    if late <= early:
        return None
    return {"earliest": early.isoformat(timespec="minutes"), "latest": late.isoformat(timespec="minutes"),
            "open_end": open_end}


def next_threshold(pred: dict | None, levels: dict | None = None, now: dt.datetime | None = None) -> dict | None:
    """เกณฑ์ถัดไปเหนือระดับปัจจุบัน ถ้าค่า ensemble หรือ M4 ridge ที่ 6 ชม. ถึงเกณฑ์นั้น"""
    if not pred:
        return None
    L = levels or config.LEVELS
    above = [k for k in THRESHOLD_KEYS if L[k] > pred["now_m"]]
    if not above:
        return None
    key = above[0]
    w = pred["horizons"][config.WARNING_HORIZON]
    if max(w["ensemble_m"], w["ridge_m"]) < L[key]:
        return None
    e = eta(pred, L[key], now)
    return {"key": key, "level_m": L[key], **e} if e else None


def my_level(pred: dict | None, my_m: float, now_m: float, now: dt.datetime | None = None) -> dict:
    """เทียบพยากรณ์กับระดับน้ำที่ผู้ใช้บอกว่าน้ำเริ่มเข้าบ้าน/ร้าน"""
    out = {"level_m": round(my_m, 2), "reached": now_m >= my_m, "near": now_m >= my_m - config.MY_LEVEL_NEAR_M,
           "eta": None}
    if pred and not out["reached"]:
        upper6 = _upper(pred)[-1][1]
        out["near"] = out["near"] or upper6 >= my_m - config.MY_LEVEL_NEAR_M
        out["eta"] = eta(pred, my_m, now)
    return out


def advice_status(now_m: float, pred: dict | None, levels: dict | None = None) -> tuple[str, str]:
    """สถานะที่ใช้เลือกคำแนะนำ: สูงกว่าระหว่างตอนนี้กับพยากรณ์ 6 ชม. ของ M4 (ตามรายงาน M4 เตือนได้เร็วกว่า)"""
    cur = status(now_m, levels)
    if not pred:
        return cur, "now"
    fut = status(pred["horizons"][config.WARNING_HORIZON]["ridge_m"], levels)
    return (fut, "forecast6") if _rank(fut) > _rank(cur) else (cur, "now")


def level_controlled_series(wide: pd.DataFrame) -> pd.DataFrame:
    """ทุกชั่วโมง: ระดับ P.1 เปลี่ยนมากแต่ปริมาณน้ำและต้นน้ำแทบไม่เปลี่ยนหรือไม่ (คอลัมน์ detected, change_m, q_pct, k)"""
    w = wide.interpolate(limit=3, limit_area="inside")
    p1, q = w["P1"], w["Q1"] if "Q1" in w else pd.Series(float("nan"), index=w.index)
    out = pd.DataFrame({"detected": False, "change_m": float("nan"), "q_pct": float("nan"), "k": 0}, index=w.index)
    for k in range(2, config.LC_WINDOW_HOURS + 1):
        dp, dq = p1 - p1.shift(k), q / q.shift(k) - 1
        n = k + config.LC_UPSTREAM_LEAD_HOURS + 1
        dup = pd.concat([w[s].rolling(n).max() - w[s].rolling(n).min() for s in config.MODEL_UPSTREAM], axis=1).max(axis=1)
        hit = (dp.abs() >= config.LC_MIN_CHANGE_M) & (dq.abs() < config.LC_MAX_DISCHARGE_PCT) & (dup < config.LC_MAX_UPSTREAM_M)
        new = hit & (~out["detected"] | (dp.abs() > out["change_m"].abs()))   # เก็บช่วงที่ระดับเปลี่ยนมากสุด
        out.loc[new, ["detected", "change_m", "q_pct", "k"]] = list(zip([True] * new.sum(), dp[new], dq[new], [k] * new.sum()))
    return out


def level_controlled(wide: pd.DataFrame) -> dict:
    """ตรวจที่ชั่วโมงล่าสุดที่มีระดับ P.1 (ไม่มีปริมาณน้ำ = ตรวจไม่ได้ เช่นโหมดสาธิตที่ใช้ข้อมูลปี 2567)"""
    p1 = wide["P1"].dropna() if "P1" in wide else pd.Series(dtype=float)
    if p1.empty:
        return {"detected": False, "reason": "no_data"}
    t = p1.index[-1]
    recent = wide.loc[t - pd.Timedelta(hours=config.LC_WINDOW_HOURS):t]
    if "Q1" not in wide or recent["Q1"].notna().sum() < 2:
        return {"detected": False, "reason": "no_discharge"}
    r = level_controlled_series(wide.loc[:t]).iloc[-1]
    if not r["detected"]:
        return {"detected": False}
    return {"detected": True, "at": t.isoformat(timespec="minutes"),
            "since": (t - pd.Timedelta(hours=int(r["k"]))).isoformat(timespec="minutes"),
            "change_m": round(float(r["change_m"]), 2), "discharge_change_pct": round(float(r["q_pct"]) * 100, 1)}


def trend12_visible(now_m, upstream_rise_3h, lc_detected, levels: dict | None = None):
    """กฎแสดงแนวโน้ม 12 ชม. ใช้ได้ทั้งค่าเดี่ยวและ Series (scripts/backtest.py ใช้กฎเดียวกันนี้)"""
    L = levels or config.LEVELS
    return ((np.asarray(now_m) >= L["watch"]) | (np.asarray(upstream_rise_3h) >= config.TREND12_UPSTREAM_RISE_M))         & ~np.asarray(lc_detected, dtype=bool)


def trend12(pred: dict | None, wide: pd.DataFrame, lc: dict, levels: dict | None = None) -> tuple[dict | None, str | None]:
    """แนวโน้ม 12 ชม. (ขึ้น/ทรง/ลง) หรือ None พร้อมเหตุผลที่ซ่อน: no_forecast / level_controlled / low_flow"""
    if not pred or 12 not in pred["horizons"]:
        return None, "no_forecast"
    if lc.get("detected"):
        return None, "level_controlled"
    L = levels or config.LEVELS
    t0 = pd.Timestamp(pred["issued_for"])
    d = wide.loc[:t0].interpolate(limit=3, limit_area="inside")
    rise = max((float(d[k].iloc[-1] - d[k].iloc[-4]) for k in config.MODEL_UPSTREAM
                if len(d) >= 4 and pd.notna(d[k].iloc[-1]) and pd.notna(d[k].iloc[-4])), default=0.0)
    if not trend12_visible(pred["now_m"], rise, False, L):
        return None, "low_flow"
    d12 = pred["horizons"][12]["ensemble_m"] - pred["now_m"]
    return {"h": 12, "change_m": round(d12, 2),
            "direction": "rising" if d12 > 0.15 else "falling" if d12 < -0.15 else "steady"}, None


def conditions(pred: dict | None, wide: pd.DataFrame, p1_range=None) -> dict:
    """สภาพตอนออกพยากรณ์ ใช้ทั้งใน API และบันทึกลง forecast_log.flags"""
    lc = level_controlled(wide)
    tr, reason = trend12(pred, wide, lc)
    out = {"level_controlled": lc, "trend12": tr, "trend12_hidden_reason": reason}
    if pred and p1_range:
        out["out_of_train_range"] = not (p1_range[0] <= pred["now_m"] <= p1_range[1])
    return out


def flags(cond: dict) -> dict:
    return {"level_controlled": bool(cond["level_controlled"].get("detected")),
            "trend12_shown": cond["trend12"] is not None,
            "out_of_train_range": bool(cond.get("out_of_train_range"))}


def reliability(now_m: float, p1_range: tuple[float, float] | None, wide: pd.DataFrame,
                now: dt.datetime, pred: dict | None, stale: bool, age_hours: float) -> dict:
    """เหตุที่ทำให้ตัวเลขพยากรณ์เชื่อถือได้น้อยลง (ว่าง = ปกติ)"""
    reasons = []
    if p1_range is not None:
        lo, hi = p1_range
        if now_m < lo or now_m > hi:
            reasons.append({"code": "out_of_train_range", "side": "below" if now_m < lo else "above",
                            "train_min": round(lo, 2), "train_max": round(hi, 2)})
    missing = []
    for key in config.MODEL_UPSTREAM:
        s = wide[key].dropna() if key in wide else pd.Series(dtype=float)
        if s.empty or (pd.Timestamp(now) - s.index[-1]) > pd.Timedelta(hours=config.UPSTREAM_STALE_HOURS):
            missing.append(config.STATIONS[key]["code"])
    if missing:
        reasons.append({"code": "upstream_missing", "stations": missing})
    if pred is None:
        reasons.append({"code": "no_forecast"})
    if stale:
        reasons.append({"code": "stale", "age_hours": round(age_hours, 1)})
    return {"low": bool(reasons), "reasons": reasons}
