"""ดึงและแปลงข้อมูลจาก ThaiWater (สสน.)

endpoint เหล่านี้เป็น JSON ที่หน้าเว็บ thaiwater.net เรียกใช้เอง ไม่ใช่ API ทางการ
จึงอาจเปลี่ยนรูปแบบหรือตอบ 429 ได้ ให้เรียกไม่ถี่กว่า 10 นาทีต่อครั้ง
"""
from __future__ import annotations

import datetime as dt
import logging

import requests

from . import config

log = logging.getLogger(__name__)


def _float(v):
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if -100 < f < 2000 else None   # ตัดค่า sentinel เช่น 999999


def _time(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(str(s)[:19], fmt)
        except ValueError:
            continue
    return None


class RateLimited(RuntimeError):
    """ThaiWater ตอบ 429 แยกจาก error อื่นเพื่อให้ collector ถอยระยะ poll และนับลง meta"""


def get_json(path: str, params: dict | None = None, timeout: int = 60):
    r = requests.get(f"{config.THAIWATER_BASE}/{path}", params=params,
                     headers=config.HTTP_HEADERS, timeout=timeout)
    if r.status_code == 429:
        raise RateLimited("ThaiWater ตอบ 429 (เรียกถี่เกินไป) ลองใหม่ภายหลัง")
    r.raise_for_status()
    return r.json()


def parse_waterlevel_load(payload: dict) -> list[dict]:
    """คืนค่าล่าสุดของสถานีที่ระบบใช้ เวลาเป็นเวลาไทย (naive)"""
    rows = ((payload or {}).get("waterlevel_data") or {}).get("data") or []
    out = []
    for r in rows:
        st = r.get("station") or {}
        if st.get("id") not in config.ID_TO_KEY:
            continue
        t, lvl = _time(r.get("waterlevel_datetime")), _float(r.get("waterlevel_msl"))
        if t is None or lvl is None:
            continue
        out.append({"station_id": st["id"], "t": t, "level_msl": lvl,
                    "discharge": _float(r.get("discharge"))})
    return out


def parse_waterlevel_graph(station_id: int, payload) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data") or {}, dict):
        raise ValueError(f"waterlevel_graph ตอบรูปแบบที่ไม่รู้จักสำหรับสถานี {station_id}: {str(payload)[:80]!r}")
    out = []
    for p in (payload.get("data") or {}).get("graph_data") or []:
        t, lvl = _time(p.get("datetime")), _float(p.get("value"))
        if t is None or lvl is None:
            continue
        out.append({"station_id": station_id, "t": t, "level_msl": lvl,
                    "discharge": _float(p.get("discharge"))})
    return out


def fetch_latest() -> list[dict]:
    return parse_waterlevel_load(get_json("waterlevel_load"))


def fetch_history(station_id: int, days: int = 365, end: dt.datetime | None = None) -> list[dict]:
    """ประวัติย้อนหลังสูงสุดประมาณ 1 ปี (ข้อจำกัดของ ThaiWater)"""
    end = end or dt.datetime.now()
    start = end - dt.timedelta(days=min(days, 365))
    payload = get_json("waterlevel_graph", {
        "station_type": "tele_waterlevel", "station_id": station_id,
        "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d %H:%M"),
    }, timeout=120)
    return parse_waterlevel_graph(station_id, payload)
