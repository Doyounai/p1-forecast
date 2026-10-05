"""Backtest มาตรฐานของโปรเจกต์ — รันก่อนและหลังแก้โมเดลทุกครั้ง

    python scripts/backtest.py            # เขียนผลลง data/backtest/results/

ชุดทดสอบ
  SEP26   ข้อมูลจริง ThaiWater 1 ก.ย. – 3 ต.ค. 2569 (น้ำน้อย, โมเดลไม่เคยเห็น)
          S1 เทรนจากน้ำท่วม 2567 อย่างเดียว
          S2 เทรนใหม่ทุกวัน 00:00 จาก 2567 + ข้อมูล 2569 ก่อนวันนั้น  <- ตรงกับเว็บจริง ใช้เป็นเกณฑ์หลัก
          S3 เทรนใหม่ทุกวันจากข้อมูล 2569 อย่างเดียว
  F24     น้ำท่วม 2567: เทรนลูกแรก (ถึง 2 ต.ค. 12:00) ทดสอบลูกที่สอง  <- กันไม่ให้ช่วงน้ำท่วมแย่ลง

เทรนและทำนายด้วย app.model โดยตรง (train / predict_frame) ผลจึงตรงกับเว็บจริง
รวมถึงช่วงความไม่แน่นอนจาก blocked CV และการไม่ทำนายแถวที่ feature ไม่ครบ
"""
from __future__ import annotations

import json
import logging
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config, features, forecast_logic as FL, model as M  # noqa: E402

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)
OUT = ROOT / "data" / "backtest" / "results"
H = [1, 3, 6, 12]
BAND_H = [1, 3, 6]
TEST_START, TEST_END = pd.Timestamp("2026-09-08 00:00"), pd.Timestamp("2026-10-03 20:00")
F24_SPLIT = pd.Timestamp("2024-10-02 12:00")
F24_END = pd.Timestamp("2024-10-09 23:00")
STATIONS = ["P1", "P67", "P21"]


def hourly(df):
    return df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="h"))


def load():
    seed = pd.read_csv(config.SEED_CSV)
    seed["key"] = seed.station_id.map(config.ID_TO_KEY)
    seed = seed.pivot(index="t", columns="key", values="level_msl")
    seed.index = pd.to_datetime(seed.index)
    seed = hourly(seed[STATIONS])
    s26 = pd.read_csv(ROOT / "data" / "backtest" / "thaiwater_2026_sep.csv", index_col=0, parse_dates=True)
    return seed, hourly(s26)


def train(w):
    """เทรนเหมือนแอป ถ้าข้อมูลไม่พอ (MIN_SAMPLES) คืน None = วันนั้นไม่มีพยากรณ์ เหมือนเว็บที่ยังไม่มีโมเดล"""
    try:
        return M.train(w, horizons=H)
    except RuntimeError:
        return None


def daily(base, test, D):
    """โมเดลที่เทรนตอน 00:00 ของวัน D ใช้พยากรณ์ทั้งวัน D (ใช้ข้อมูลย้อนหลัง 24 ชม. เป็น feature)"""
    b = train(base[base.index < D])
    if b is None:
        return None
    te = test[(test.index >= D - pd.Timedelta(hours=24)) & (test.index < D + pd.Timedelta(days=1))]
    return {h: df[(df.index >= D) & (df.index < D + pd.Timedelta(days=1))] for h, df in M.predict_frame(b, te).items()}


def merge(parts):
    parts = [p for p in parts if p is not None]
    return {h: pd.concat([p[h] for p in parts]) for h in H}


def score(p, obs, h, start, end):
    p = p.reindex(obs.index)
    now = obs.interpolate(limit=3, limit_area="inside")
    y = obs.shift(-h)
    m = (obs.index >= start) & (obs.index <= end - pd.Timedelta(hours=h)) & y.notna() & p.notna() & now.notna()
    e, ep = (p - y)[m], (now - y)[m]
    r = {"n": int(m.sum()), "rmse_cm": round(100 * float(np.sqrt((e ** 2).mean())), 1),
         "max_err_cm": round(100 * float(e.abs().max()), 1),
         "skill": round(1 - float(np.sqrt((e ** 2).mean()) / np.sqrt((ep ** 2).mean())), 3)}
    if h == 12:
        cls = lambda d: np.where(d > 0.15, 1, np.where(d < -0.15, -1, 0))
        act, prd = cls((y - now)[m]), cls((p - now)[m])
        r["trend_acc"] = round(float((act == prd).mean()), 3)
        r["trend_acc_always_steady"] = round(float((act == 0).mean()), 3)
        r["false_rising_rate"] = round(float(((prd == 1) & (act != 1)).sum() / max((prd == 1).sum(), 1)), 3)
    return r


def trend_shown(wide, pred12, obs, start, end, label):
    """แนวโน้ม 12 ชม. เฉพาะชั่วโมงที่แอปจะแสดง (forecast_logic.trend12_visible) เทียบกับการตอบว่าทรงตัว"""
    X = features.build(wide[STATIONS])
    rise = X[["P67_d3", "P21_d3"]].max(axis=1).reindex(obs.index)
    lc = (FL.level_controlled_series(wide).detected if "Q1" in wide else pd.Series(False, index=wide.index)).reindex(obs.index)
    now = obs.interpolate(limit=3, limit_area="inside")
    y, p = obs.shift(-12), pred12.ensemble.reindex(obs.index)
    m = p.notna() & y.notna() & now.notna() & (obs.index >= start) & (obs.index <= end - pd.Timedelta(hours=12))
    shown = m & FL.trend12_visible(now, rise.fillna(0), lc.fillna(False).astype(bool))
    cls = lambda d: np.where(d > 0.15, 1, np.where(d < -0.15, -1, 0))
    act, prd = cls((y - now)[shown]), cls((p - now)[shown])
    n = int(shown.sum())
    return {"set": label, "shown": n, "of": int(m.sum()),
            "trend_acc": round(float((act == prd).mean()), 3) if n else None,
            "trend_acc_always_steady": round(float((act == 0).mean()), 3) if n else None,
            "false_rising_rate": round(float(((prd == 1) & (act != 1)).sum() / max((prd == 1).sum(), 1)), 3) if n else None}


def coverage(pred, obs, h, start, end, label):
    df = pred[h].reindex(obs.index)
    y = obs.shift(-h)
    m = df["lo"].notna() & y.notna() & (obs.index >= start) & (obs.index <= end - pd.Timedelta(hours=h))
    inside = (y >= df["lo"]) & (y <= df["hi"])
    return {"set": label, "h": h, "n": int(m.sum()), "coverage": round(float(inside[m].mean()), 3),
            "mean_width_cm": round(100 * float((df["hi"] - df["lo"])[m].mean()), 1)}


def run():
    t_start = time.time()
    seed, s26 = load()
    test26 = s26[STATIONS]
    both = hourly(pd.concat([seed, test26]))
    obs26 = s26.P1 - config.P1_GAUGE_ZERO_MSL
    obs24 = seed.P1 - config.P1_GAUGE_ZERO_MSL
    days = pd.date_range(TEST_START.normalize(), TEST_END.normalize(), freq="D")

    jobs = [("S2", D) for D in days] + [("S3", D) for D in days]
    bases = {"S2": both, "S3": test26}
    res = Parallel(n_jobs=-1)(delayed(daily)(bases[sc], test26, D) for sc, D in jobs)
    s1 = M.predict_frame(M.train(seed, horizons=H), test26)
    preds = {"S1": s1,
             "S2": merge(res[:len(days)]), "S3": merge(res[len(days):]),
             "F24": M.predict_frame(M.train(seed[seed.index <= F24_SPLIT], horizons=H), seed)}
    skipped = {sc: sum(r is None for r in res[i * len(days):(i + 1) * len(days)]) for i, sc in enumerate(("S2", "S3"))}

    rows = []
    for h in H:
        now = obs26.interpolate(limit=3, limit_area="inside")
        rows.append({"set": "SEP26", "scenario": "-", "model": "M0 persistence", "h": h, **score(now, obs26, h, TEST_START, TEST_END)})
        rows.append({"set": "SEP26", "scenario": "S1", "model": "M7", "h": h, **score(preds["S1"][h].ensemble, obs26, h, TEST_START, TEST_END)})
        for sc in ("S2", "S3"):
            rows.append({"set": "SEP26", "scenario": sc, "model": "M7", "h": h, **score(preds[sc][h].ensemble, obs26, h, TEST_START, TEST_END)})
            rows.append({"set": "SEP26", "scenario": sc, "model": "M4", "h": h, **score(preds[sc][h].ridge, obs26, h, TEST_START, TEST_END)})
        rows.append({"set": "F24", "scenario": "forward", "model": "M7", "h": h, **score(preds["F24"][h].ensemble, obs24, h, F24_SPLIT, F24_END)})

    cov = [coverage(preds[k], obs, h, a, b, lbl) for k, obs, a, b, lbl in
           (("S1", obs26, TEST_START, TEST_END, "SEP26 S1"), ("S2", obs26, TEST_START, TEST_END, "SEP26 S2"),
            ("F24", obs24, F24_SPLIT, F24_END, "F24")) for h in BAND_H]
    trend = pd.DataFrame([trend_shown(s26, preds["S2"][12], obs26, TEST_START, TEST_END, "SEP26 S2"),
                          trend_shown(seed, preds["F24"][12], obs24, F24_SPLIT, F24_END, "F24")])
    return pd.DataFrame(rows), pd.DataFrame(cov), skipped, preds, round(time.time() - t_start), trend


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res, cov, skipped, _, secs, trend = run()
    trend.to_csv(OUT / "trend12_shown.csv", index=False)
    res.to_csv(OUT / "summary.csv", index=False)
    cov.to_csv(OUT / "band_coverage.csv", index=False)
    json.dump(cov.to_dict("records"), open(OUT / "band_coverage.json", "w"), indent=1)
    pivot = res.pivot_table(index=["set", "scenario", "model"], columns="h", values="rmse_cm")
    n = res.pivot_table(index=["set", "scenario", "model"], columns="h", values="n")
    md = ["# Backtest summary", "", f"เทรนและทำนายด้วย app.model · ใช้เวลา {secs} วินาที · "
          f"วันที่ข้ามเพราะข้อมูลเทรนไม่พอ: S2 {skipped['S2']} วัน, S3 {skipped['S3']} วัน", "",
          "RMSE (ซม.)", "", pivot.to_markdown(), "", "จำนวนจุดที่ให้คะแนน", "", n.to_markdown(), "",
          "แนวโน้ม 12 ชม.", "", res[res.h == 12][["set", "scenario", "model", "trend_acc",
                                                    "trend_acc_always_steady", "false_rising_rate"]].to_markdown(index=False),
          "", "แนวโน้ม 12 ชม. เฉพาะชั่วโมงที่หน้าเว็บแสดง (forecast_logic.trend12_visible)", "", trend.to_markdown(index=False),
          "", "ความครอบคลุมของช่วงความไม่แน่นอน (เป้าหมาย 85–95%)", "", cov.to_markdown(index=False)]
    (OUT / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
