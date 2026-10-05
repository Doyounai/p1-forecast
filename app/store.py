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
-- พยากรณ์ทุกครั้งที่ออกจริง (ไม่ใช่ย้อนหลัง) เก็บครั้งแรกของแต่ละ issued_for แล้วเติมค่าจริงเมื่อมาถึง
CREATE TABLE IF NOT EXISTS forecast_log (
    issued_for TEXT NOT NULL,     -- ชั่วโมงล่าสุดที่มี feature ครบ (เวลาไทย)
    h INTEGER NOT NULL,
    model TEXT NOT NULL,          -- ridge (M4) / gbm (M6) / ensemble (M7)
    target_t TEXT NOT NULL,
    now_m REAL NOT NULL,          -- ระดับ P.1 ตามไม้วัด ณ issued_for (ใช้เทียบกับการทายว่าเท่าเดิม)
    pred_m REAL NOT NULL,
    lo_m REAL,
    hi_m REAL,
    trained_at TEXT,
    logged_at TEXT NOT NULL,
    actual_m REAL,                -- ระดับจริงที่ target_t (ตามไม้วัด) เติมทีหลัง
    err_m REAL,                   -- pred_m − actual_m (บวก = ทายสูงกว่าจริง)
    PRIMARY KEY (issued_for, h, model)
);
CREATE INDEX IF NOT EXISTS forecast_log_target ON forecast_log (target_t);
"""


# คอลัมน์ที่เพิ่มทีหลัง: ฐานข้อมูลเก่าจะถูกเพิ่มคอลัมน์ให้เองตอนเปิด (ไม่ลบข้อมูลเดิม)
MIGRATIONS = {
    "forecast_log": {
        "model_version": "TEXT",   # รุ่นของวิธีพยากรณ์ (model.MODEL_VERSION) ใช้แยกความแม่นก่อน/หลังแก้โมเดล
        "flags": "TEXT",           # JSON ของสภาพตอนออกพยากรณ์ เช่น {"level_controlled": true}
    },
}


def _migrate(con) -> None:
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    try:
        con.executescript(SCHEMA)
        _migrate(con)
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


# คอลัมน์ของ hourly(): ระดับน้ำทุกสถานี (ม.รทก.) + Q1 = ปริมาณน้ำ P.1 (m³/s, ข้อมูล seed ปี 2567 ไม่มี)
# Q1 ใช้ตรวจ "ระดับเปลี่ยน ปริมาณน้ำไม่เปลี่ยน" เท่านั้น ไม่ใช่ feature ของโมเดล (backtest: ไม่ช่วย)
HOURLY_COLUMNS = list(config.STATIONS) + ["Q1"]


def _to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """แปลงเป็นตารางรายชั่วโมง ใช้ค่าที่ตรงชั่วโมงก่อน"""
    if df.empty:
        return pd.DataFrame(columns=HOURLY_COLUMNS)
    df = df.copy()
    # ค่าที่เป็นไปไม่ได้ที่เข้าฐานข้อมูลไปก่อนมีการตรวจ (เช่น P.21 = 493.70 เมื่อ 4 ก.ค. 2569) ไม่ใช้
    ok = [config.plausible(s, v) for s, v in zip(df["station_id"], df["level_msl"])]
    df = df[ok]
    if df.empty:
        return pd.DataFrame(columns=HOURLY_COLUMNS)
    df["t"] = pd.to_datetime(df["t"])
    df["h"] = df["t"].dt.floor("h")
    df["off"] = (df["t"] - df["h"]).dt.total_seconds()
    df = df.sort_values("off").groupby(["station_id", "h"], as_index=False).first()
    df["key"] = df["station_id"].map(config.ID_TO_KEY)
    wide = df.pivot(index="h", columns="key", values="level_msl").sort_index()
    if "discharge" in df:
        p1 = df[df["station_id"] == config.STATIONS["P1"]["id"]].set_index("h")["discharge"]
        wide["Q1"] = p1.reindex(wide.index)
    wide = wide.reindex(columns=HOURLY_COLUMNS).astype(float)
    if len(wide):
        wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="h"))
    wide.index.name = "t"
    return wide


def hourly(start: dt.datetime | None = None, end: dt.datetime | None = None) -> pd.DataFrame:
    q, args = "SELECT station_id, t, level_msl, discharge FROM obs WHERE 1=1", []
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


def station_coverage(now: dt.datetime) -> dict:
    """ค่าล่าสุดและจำนวนชั่วโมงที่มีข้อมูลของแต่ละสถานี (ใช้ในหน้าสถานะระบบ)"""
    d24 = (now - dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    with connect() as con:
        rows = con.execute(
            "SELECT station_id, MAX(t), COUNT(DISTINCT substr(t,1,13)), "
            "COUNT(DISTINCT CASE WHEN t >= ? THEN substr(t,1,13) END) FROM obs GROUP BY station_id", (d24,)).fetchall()
    return {config.ID_TO_KEY[sid]: {"last_t": last, "hours_total": n, "hours_24h": n24}
            for sid, last, n, n24 in rows if sid in config.ID_TO_KEY}


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
