"""คำสั่งช่วยเหลือ

python -m app.cli backfill        ดึงข้อมูลย้อนหลัง 1 ปีของ P.1, P.67, P.21
python -m app.cli poll            ดึงค่าล่าสุด 1 ครั้ง
python -m app.cli train           เทรนโมเดลใหม่จากข้อมูลทั้งหมดในฐานข้อมูล
python -m app.cli info            ดูสรุปข้อมูลและความแม่นของโมเดล
"""
import argparse
import json
import logging

from . import collector, config, model, store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    ap = argparse.ArgumentParser(description="P.1 forecast tools")
    ap.add_argument("cmd", choices=["backfill", "poll", "train", "info"])
    ap.add_argument("--days", type=int, default=365)
    a = ap.parse_args()
    collector.ensure_seed()
    if a.cmd == "backfill":
        print(json.dumps(collector.backfill(days=a.days), ensure_ascii=False, indent=1))
    elif a.cmd == "poll":
        collector.poll_once()
        print(store.get_meta("last_fetch"))
    elif a.cmd == "train":
        b = collector.retrain()
        for h, m in b["horizons"].items():
            print(f"h={h:>2} ชม.  train={m['n_train']:>5} ชม.  {m['metrics']}")
    elif a.cmd == "info":
        print("ชั่วโมงที่มีข้อมูล P.1:", store.count_hours())
        print("ดึงล่าสุด:", store.get_meta("last_fetch"))
        b = model.load()
        if b:
            print("โมเดลเทรนเมื่อ:", b["trained_at"])
            for h, m in b["horizons"].items():
                print(f"h={h:>2} ชม.  {m['metrics']}  ช่วงข้อมูล {m['train_range']}")
        else:
            print("ยังไม่มีโมเดล:", config.MODEL_PATH)


if __name__ == "__main__":
    main()
