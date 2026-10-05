"""งานเบื้องหลัง: ดึงข้อมูลทุก 10 นาที, ดึงย้อนหลัง 1 ปีครั้งแรก, เทรนโมเดลใหม่ทุก 24 ชม."""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from zoneinfo import ZoneInfo

from . import config, forecast_log, model, store, thaiwater

log = logging.getLogger(__name__)
TH = ZoneInfo("Asia/Bangkok")
_lock = threading.Lock()


def now_th() -> dt.datetime:
    return dt.datetime.now(TH).replace(tzinfo=None)


def ensure_seed() -> None:
    if not store.get_meta("seed_loaded"):
        n = store.upsert(store.load_seed(), source="seed")
        store.set_meta("seed_loaded", n)
        log.info("loaded %d seed rows (น้ำท่วมปี 2567)", n)


def _note_429(where: str) -> None:
    c = store.get_meta("http_429", {"count": 0})
    store.set_meta("http_429", {"count": c.get("count", 0) + 1, "last_at": now_th(), "last_where": where})


def backfill(days: int = 365, pause_s: float = 3.0) -> dict:
    result = {}
    for key, st in config.STATIONS.items():
        try:
            rows = thaiwater.fetch_history(st["id"], days=days, end=now_th())
            result[key] = store.upsert(rows, source="graph")
        except Exception as e:  # สถานีหนึ่งล้มเหลวไม่ทำให้สถานีอื่นหยุด
            log.warning("backfill %s failed: %s", key, e)
            if isinstance(e, thaiwater.RateLimited):
                _note_429(f"backfill {key}")
            result[key] = f"error: {e}"
        time.sleep(pause_s)
    if any(isinstance(v, int) and v > 0 for v in result.values()):
        store.set_meta("backfill", {"at": now_th(), "result": result})   # ล้มเหลวทั้งหมด = ลองใหม่ตอนเปิดครั้งหน้า
    return result


def poll_once() -> str:
    """ดึงค่าล่าสุด 1 ครั้ง คืนผล: ok / empty (ไม่เจอสถานีของเรา อาจเปลี่ยนรูปแบบข้อมูล) / 429 / error"""
    entry = {"at": now_th()}
    try:
        rows = thaiwater.fetch_latest()
        store.upsert(rows, source="load")
        kind = "ok" if rows else "empty"
        entry.update({"ok": True, "rows": len(rows)})
        if not rows:
            entry["error"] = "ไม่พบสถานีของระบบใน waterlevel_load อาจเปลี่ยนรูปแบบข้อมูล"
    except Exception as e:
        log.warning("poll failed: %s", e)
        kind = "429" if isinstance(e, thaiwater.RateLimited) else "error"
        entry.update({"ok": False, "error": str(e)})
        if kind == "429":
            _note_429("poll")
    entry["kind"] = kind
    store.set_meta("last_fetch", entry)
    hist = store.get_meta("poll_log", [])
    store.set_meta("poll_log", (hist + [entry])[-config.POLL_LOG_MAX:])
    return kind


def next_wait(prev_min: int, kind: str) -> int:
    """ได้ 429 = ถอยระยะ poll เป็น 2 เท่า (ไม่เกิน POLL_BACKOFF_MAX_MINUTES) สำเร็จหรือ error อื่นกลับเป็นปกติ"""
    if kind == "429":
        return min(max(prev_min, config.POLL_MINUTES) * 2, config.POLL_BACKOFF_MAX_MINUTES)
    return config.POLL_MINUTES


def log_forecast() -> dict:
    """บันทึกพยากรณ์ล่าสุดลง forecast_log แล้วเติมค่าจริงให้พยากรณ์ที่ถึงเวลาแล้ว"""
    b = model.load()
    if b is None:
        return {"logged": 0, "scored": 0}
    now = now_th()
    pred = model.predict(b, store.hourly(start=now - dt.timedelta(days=4), end=now))
    return {"logged": forecast_log.record(b, pred, now), "scored": forecast_log.score()}


def retrain() -> dict:
    with _lock:
        wide = store.hourly() if not config.DEMO else store.hourly(end=dt.datetime.fromisoformat(config.DEMO_NOW))
        try:
            bundle = model.train(wide)
        except Exception as e:
            store.set_meta("last_train_error", {"at": now_th(), "error": str(e)})
            raise
        model.save(bundle)
        store.set_meta("last_train", {"at": now_th(), "hours": store.count_hours(),
                                      "rmse_cm": {h: m["metrics"].get("rmse_cm_ensemble") for h, m in bundle["horizons"].items()}})
        return bundle


def ensure_model() -> None:
    b = model.load()
    if b is None or not model.is_current(b):
        log.info("no model yet (or outdated horizons): training from available data")
        retrain()


def _loop(stop: threading.Event) -> None:
    ensure_seed()
    if config.COLLECT and not store.get_meta("backfill"):
        log.info("first run: fetching one year of history from ThaiWater")
        backfill()
    try:
        ensure_model()
    except Exception as e:
        log.error("initial training failed: %s", e)
    last_train = time.monotonic()
    wait_min = config.POLL_MINUTES
    while not stop.is_set():
        if config.COLLECT:
            wait_min = next_wait(wait_min, poll_once())
            store.set_meta("poll_wait_minutes", wait_min)
            try:
                log_forecast()
            except Exception as e:   # บันทึกพยากรณ์ล้มเหลวต้องไม่หยุดการเก็บข้อมูล
                log.error("forecast log failed: %s", e)
        if time.monotonic() - last_train > config.RETRAIN_HOURS * 3600:
            try:
                retrain()
            except Exception as e:
                log.error("retrain failed: %s", e)
            last_train = time.monotonic()
        stop.wait(wait_min * 60)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="collector").start()
    return stop
