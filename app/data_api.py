"""API สำหรับนักวิจัย: ข้อมูลรายชั่วโมงทุกสถานี (JSON/CSV), รายชื่อสถานี และ log พยากรณ์

เอกสารอัตโนมัติอยู่ที่ /docs (OpenAPI) และคำอธิบายภาษาไทยที่ /data.html
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from . import config, forecast_log, store

router = APIRouter(prefix="/api", tags=["ข้อมูลสำหรับนักวิจัย"])
MAX_DAYS = 366
DEFAULT_DAYS = 30


def _parse(s: str | None, end_of_day: bool = False) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.strip())
    except ValueError:
        raise HTTPException(422, f"รูปแบบเวลาไม่ถูกต้อง: {s!r} ใช้ 'YYYY-MM-DD' หรือ 'YYYY-MM-DD HH:MM'")
    if end_of_day and len(s.strip()) == 10:
        t = t.replace(hour=23)
    return t


def _last_obs() -> dt.datetime | None:
    with store.connect() as con:
        last = con.execute("SELECT MAX(t) FROM obs").fetchone()[0]
    return dt.datetime.fromisoformat(last) if last else None


def _range(start: str | None, end: str | None) -> tuple[dt.datetime, dt.datetime]:
    """ค่าเริ่มต้น: 30 วันจนถึงค่าล่าสุดที่มี; ยาวสุด 366 วันต่อครั้ง"""
    e = _parse(end, end_of_day=True)
    if e is None:
        e = _last_obs() or dt.datetime(2000, 1, 1)
    s = _parse(start) or e - dt.timedelta(days=DEFAULT_DAYS)
    if s > e:
        raise HTTPException(422, "start ต้องไม่หลัง end")
    if e - s > dt.timedelta(days=MAX_DAYS):
        raise HTTPException(422, f"ขอได้ไม่เกิน {MAX_DAYS} วันต่อครั้ง แบ่งเป็นหลายช่วงแทน")
    return s, e


def hourly_frame(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    """ตารางรายชั่วโมง: ค่าที่วัดจริง (ไม่เติมช่องว่าง) เป็น ม.รทก. พร้อมระดับตามไม้วัด P.1 และระดับเทียบตลิ่ง"""
    wide = store.hourly(start=start, end=end)
    # ตารางครบทุกชั่วโมงในช่วงที่ขอ ชั่วโมงที่ไม่มีค่า = ช่องว่าง (ไม่เติม) แต่ไม่เกินค่าล่าสุดในฐานข้อมูล
    grid = pd.date_range(pd.Timestamp(start).ceil("h"), pd.Timestamp(end).floor("h"), freq="h")
    last = _last_obs()
    if last is not None:
        grid = grid[grid <= pd.Timestamp(last).floor("h")]
    wide = wide.reindex(grid)
    out = pd.DataFrame(index=wide.index)
    for key, st in config.STATIONS.items():
        s = wide[key] if key in wide else pd.Series(index=wide.index, dtype=float)
        out[f"{key}_msl"] = s.round(2)
        if key == "P1":
            out["P1_gauge_m"] = (s - config.P1_GAUGE_ZERO_MSL).round(2)
        out[f"{key}_vs_bank_m"] = (s - st["bank_msl"]).round(2)
    out.index = out.index.strftime("%Y-%m-%d %H:%M")
    out.index.name = "t_th"
    return out.reset_index()


def _csv(df: pd.DataFrame, filename: str) -> Response:
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/stations", summary="รายชื่อสถานี รหัส ThaiWater ตลิ่ง และ datum")
def stations():
    return [{"key": k, "code": st["code"], "thaiwater_id": st["id"], "name": st["name"], "river": st["river"],
             "bank_msl": st["bank_msl"], "gauge_zero_msl": config.P1_GAUGE_ZERO_MSL if k == "P1" else None,
             "travel_hours": list(st["travel"]["hours"]) if st.get("travel", {}).get("hours") else None,
             "travel_source": st.get("travel", {}).get("source", "")}
            for k, st in config.STATIONS.items()]


@router.get("/data/hourly", summary="ระดับน้ำรายชั่วโมงทุกสถานี (JSON)")
def hourly_json(start: str | None = Query(None, description="เริ่ม 'YYYY-MM-DD' หรือ 'YYYY-MM-DD HH:MM' (เวลาไทย)"),
                end: str | None = Query(None, description="สิ้นสุด (รวม) ค่าเริ่มต้น = ค่าล่าสุดที่มี")):
    s, e = _range(start, end)
    df = hourly_frame(s, e)
    return {"timezone": "Asia/Bangkok (ไม่มี offset)", "start": s.strftime("%Y-%m-%d %H:%M"), "end": e.strftime("%Y-%m-%d %H:%M"),
            "units": "เมตร: *_msl = ม.รทก., P1_gauge_m = ตามไม้วัด P.1, *_vs_bank_m = เทียบตลิ่ง (บวก = ล้นตลิ่ง)",
            "columns": list(df.columns),
            "rows": [[None if pd.isna(v) else v for v in row] for row in df.itertuples(index=False)]}


@router.get("/data/hourly.csv", summary="ระดับน้ำรายชั่วโมงทุกสถานี (CSV)")
def hourly_csv(start: str | None = Query(None), end: str | None = Query(None)):
    s, e = _range(start, end)
    return _csv(hourly_frame(s, e), f"p1_hourly_{s:%Y%m%d}_{e:%Y%m%d}.csv")


@router.get("/data/forecast_log.csv", summary="พยากรณ์ที่ออกจริงทุกครั้งเทียบค่าจริง (CSV)")
def forecast_log_csv(start: str | None = Query(None, description="กรองตามเวลาเป้าหมาย (target_t)"),
                     end: str | None = Query(None)):
    df = forecast_log.load(_parse(start), _parse(end, end_of_day=True))
    return _csv(df, "p1_forecast_log.csv")
