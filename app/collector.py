"""งานเบื้องหลัง: ดึงข้อมูลทุก 10 นาที, ดึงย้อนหลัง 1 ปีครั้งแรก, เทรนโมเดลใหม่ทุก 24 ชม."""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from zoneinfo import ZoneInfo

from . import config, model, store, thaiwater

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


def backfill(days: int = 365, pause_s: float = 3.0) -> dict:
    result = {}
    for key, st in config.STATIONS.items():
        try:
            rows = thaiwater.fetch_history(st["id"], days=days, end=now_th())
            result[key] = store.upsert(rows, source="graph")
        except Exception as e:  # สถานีหนึ่งล้มเหลวไม่ทำให้สถานีอื่นหยุด
            log.warning("backfill %s failed: %s", key, e)
            result[key] = f"error: {e}"
        time.sleep(pause_s)
    if any(isinstance(v, int) and v > 0 for v in result.values()):
        store.set_meta("backfill", {"at": now_th(), "result": result})   # ล้มเหลวทั้งหมด = ลองใหม่ตอนเปิดครั้งหน้า
    return result


def poll_once() -> None:
    try:
        rows = thaiwater.fetch_latest()
        store.upsert(rows, source="load")
        store.set_meta("last_fetch", {"at": now_th(), "ok": True, "rows": len(rows)})
    except Exception as e:
        log.warning("poll failed: %s", e)
        store.set_meta("last_fetch", {"at": now_th(), "ok": False, "error": str(e)})


def retrain() -> dict:
    with _lock:
        wide = store.hourly() if not config.DEMO else store.hourly(end=dt.datetime.fromisoformat(config.DEMO_NOW))
        bundle = model.train(wide)
        model.save(bundle)
        store.set_meta("last_train", {"at": now_th(), "hours": store.count_hours()})
        return bundle


def ensure_model() -> None:
    if model.load() is None:
        log.info("no model yet: training from available data")
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
    while not stop.is_set():
        if config.COLLECT:
            poll_once()
        if time.monotonic() - last_train > config.RETRAIN_HOURS * 3600:
            try:
                retrain()
            except Exception as e:
                log.error("retrain failed: %s", e)
            last_train = time.monotonic()
        stop.wait(config.POLL_MINUTES * 60)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="collector").start()
    return stop
