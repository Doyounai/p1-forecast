"""เก็บค่าระดับน้ำทุกค่าที่ดึงมาใน SQLite เพื่อสะสมข้อมูลไว้เทรนโมเดลในอนาคต"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager

import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS obs (
    station_id INTEGER NOT NULL,
    t TEXT NOT NULL,              -- เวลาไทย 'YYYY-MM-DD HH:MM'
    level_msl REAL NOT NULL,
    discharge REAL,
    source TEXT,
    PRIMARY KEY (station_id, t)
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def upsert(rows: list[dict], source: str) -> int:
    if not rows:
        return 0
    with connect() as con:
        con.executemany(
            "INSERT INTO obs (station_id, t, level_msl, discharge, source) VALUES (?,?,?,?,?) "
            "ON CONFLICT(station_id, t) DO UPDATE SET level_msl=excluded.level_msl, "
            "discharge=COALESCE(excluded.discharge, obs.discharge), source=excluded.source",
            [(r["station_id"], r["t"].strftime("%Y-%m-%d %H:%M"), r["level_msl"], r.get("discharge"), source)
             for r in rows])
    return len(rows)


def load_seed() -> list[dict]:
    df = pd.read_csv(config.SEED_CSV)
    return [{"station_id": int(r.station_id), "t": dt.datetime.strptime(r.t, "%Y-%m-%d %H:%M"),
             "level_msl": float(r.level_msl)} for r in df.itertuples()]


def _to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """แปลงเป็นตารางรายชั่วโมง คอลัมน์ P1/P67/P21 (ม.รทก.) ใช้ค่าที่ตรงชั่วโมงก่อน"""
    if df.empty:
        return pd.DataFrame(columns=list(config.STATIONS))
    df = df.copy()
    df["t"] = pd.to_datetime(df["t"])
    df["h"] = df["t"].dt.floor("h")
    df["off"] = (df["t"] - df["h"]).dt.total_seconds()
    df = df.sort_values("off").groupby(["station_id", "h"], as_index=False).first()
    df["key"] = df["station_id"].map(config.ID_TO_KEY)
    wide = df.pivot(index="h", columns="key", values="level_msl").sort_index()
    wide = wide.reindex(columns=list(config.STATIONS))
    if len(wide):
        wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="h"))
    wide.index.name = "t"
    return wide


def hourly(start: dt.datetime | None = None, end: dt.datetime | None = None) -> pd.DataFrame:
    q, args = "SELECT station_id, t, level_msl FROM obs WHERE 1=1", []
    if start is not None:
        q += " AND t >= ?"; args.append(start.strftime("%Y-%m-%d %H:%M"))
    if end is not None:
        q += " AND t <= ?"; args.append(end.strftime("%Y-%m-%d %H:%M"))
    with connect() as con:
        df = pd.read_sql_query(q, con, params=args)
    return _to_hourly(df)


def latest_discharge() -> dict:
    with connect() as con:
        rows = con.execute(
            "SELECT station_id, discharge FROM obs o WHERE t = (SELECT MAX(t) FROM obs WHERE station_id=o.station_id)"
        ).fetchall()
    return {config.ID_TO_KEY.get(sid): q for sid, q in rows}


def count_hours() -> int:
    with connect() as con:
        return con.execute("SELECT COUNT(DISTINCT substr(t,1,13)) FROM obs WHERE station_id=?",
                           (config.STATIONS["P1"]["id"],)).fetchone()[0]


def set_meta(k: str, v) -> None:
    with connect() as con:
        con.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (k, json.dumps(v, ensure_ascii=False, default=str)))


def get_meta(k: str, default=None):
    with connect() as con:
        row = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(row[0]) if row else default
