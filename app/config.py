"""ค่าตั้งต้นทั้งหมดของระบบ แก้ที่ไฟล์นี้หรือผ่าน environment variable"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("P1_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "p1.sqlite3"
SEED_CSV = ROOT / "data" / "seed" / "thaiwater_2024_flood.csv"

THAIWATER_BASE = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (P1-forecast; research prototype)",
    "Referer": "https://www.thaiwater.net/",
    "Accept": "application/json",
}

# station_id = รหัสตัวเลขของ ThaiWater, bank_msl = ระดับตลิ่งต่ำสุด (ม.รทก.)
STATIONS = {
    "P1": {"id": 3226, "code": "P.1", "name": "สะพานนวรัฐ", "river": "แม่น้ำปิง", "bank_msl": 304.20},
    # travel = เวลาที่น้ำเดินทางถึง P.1 (ชม.) ใส่เฉพาะค่าที่มีแหล่งอ้างอิง ถ้าไม่มีให้ hours=None และ source=""
    "P67": {"id": 3247, "code": "P.67", "name": "บ้านแม่แต สันทราย", "river": "แม่น้ำปิง", "bank_msl": 318.93,
            "travel": {"hours": (6, 6), "source": "docs/experiment-findings.md: lag 6 ชม. r = 0.67 ข้อมูลปี 2567"}},
    "P21": {"id": 3240, "code": "P.21", "name": "บ้านริมใต้ แม่ริม", "river": "น้ำแม่ริม", "bank_msl": 323.50,
            "travel": {"hours": (2, 3), "source": "docs/experiment-findings.md: lag 2–3 ชม. เช้า 3 ต.ค. 2567"}},
}
ID_TO_KEY = {v["id"]: k for k, v in STATIONS.items()}

# ช่วงระดับที่เป็นไปได้ เทียบตลิ่ง (ม.) ค่านอกช่วงคือค่าผิดพลาดจากต้นทาง ไม่ใช้ทั้งตอนรับข้อมูลและตอนเทรน
# เคยเจอ P.21 = 493.70 ม.รทก. (ตลิ่ง 323.50) เมื่อ 4 ก.ค. 2569 13:00 ทำให้ Ridge ใน CV พังจน RMSE 6 ชม. เกิน 150 ซม.
# ช่วงนี้กว้างกว่าที่เคยวัดได้มาก (2567: P.1 สูงสุดตลิ่ง +1.10, P.21 +2.98; ต่ำสุดราวตลิ่ง −3.9)
PLAUSIBLE_VS_BANK_M = (-10.0, 8.0)


def plausible(station_id: int, level_msl: float) -> bool:
    key = ID_TO_KEY.get(station_id)
    if key is None:
        return True
    lo, hi = PLAUSIBLE_VS_BANK_M
    return lo <= level_msl - STATIONS[key]["bank_msl"] <= hi
MODEL_UPSTREAM = ("P67", "P21")   # สถานีต้นน้ำที่โมเดลใช้เป็น feature

# P.1: ศูนย์ไม้วัดระดับ = ตลิ่ง 304.20 ม.รทก. − 3.70 ม.
P1_GAUGE_ZERO_MSL = 300.50

# เกณฑ์ตามไม้วัด P.1 (ม.) — ตรวจกับประกาศล่าสุดของกรมชลประทาน/จังหวัดก่อนใช้งานจริง
LEVELS = {
    "watch": float(os.getenv("P1_WATCH_M", 3.10)),
    "critical": float(os.getenv("P1_CRITICAL_M", 3.70)),
    "overflow": float(os.getenv("P1_OVERFLOW_M", 4.20)),
}

# "ระดับเปลี่ยน ปริมาณน้ำไม่เปลี่ยน" (น่าจะเป็นการบริหารประตูระบายน้ำท้ายน้ำ ยังไม่ยืนยันกับกรมชลฯ)
# ภายใน LC_WINDOW_HOURS ชม. P.1 เปลี่ยน ≥ LC_MIN_CHANGE_M ขณะที่ปริมาณน้ำ P.1 เปลี่ยน < LC_MAX_DISCHARGE_PCT
# และ P.67/P.21 เปลี่ยนไม่ถึง LC_MAX_UPSTREAM_M (มองย้อนเพิ่ม LC_UPSTREAM_LEAD_HOURS ชม. เพราะน้ำต้นน้ำใช้เวลาเดินทาง)
# ตั้งจากเหตุการณ์ ก.ย. 2569 ใน docs/experiment-findings.md: จับได้ 5/5 และไม่จับน้ำมาจริงเมื่อ 26 ก.ย.
LC_WINDOW_HOURS = 6
LC_MIN_CHANGE_M = 0.15
LC_MAX_DISCHARGE_PCT = 0.08
LC_MAX_UPSTREAM_M = 0.20
LC_UPSTREAM_LEAD_HOURS = 6

# แนวโน้ม 12 ชม. แสดงเฉพาะเมื่อ P.1 ≥ เกณฑ์เฝ้าระวัง หรือต้นน้ำ (P.67/P.21) ขึ้น ≥ ค่านี้ใน 3 ชม. และไม่ใช่ช่วง level_controlled
# backtest: ช่วงน้ำน้อยทายทิศทางแทบไม่ดีกว่าตอบ "ทรงตัว" ทุกครั้ง (62% เทียบ 60%) ส่วนเมื่อผ่านกฎนี้ถูก 51% เทียบ 37% (S2) และ 74% เทียบ 19% (F24)
TREND12_UPSTREAM_RISE_M = 0.15

HORIZONS = [1, 2, 3, 4, 5, 6, 12] # ชั่วโมงล่วงหน้า (2, 4, 5 ใช้ในตารางรายชั่วโมงของแต่ละโมเดล ไม่อยู่ในรายงานการทดลอง)
NUMERIC_HORIZONS = [1, 3, 6]      # แสดงเป็นตัวเลข; 12 ชม. แสดงเป็นแนวโน้มเท่านั้น (ดูรายงานการทดลอง)
TABLE_HORIZONS = [1, 2, 3, 4, 5, 6]  # ตารางเทียบโมเดลรายชั่วโมงท้ายหน้า (ห้ามเกิน 6 ชม.)
MODEL_KEYS = ("ridge", "gbm", "ensemble")  # M4, M6, M7
WARNING_HORIZON = 6               # ใช้ Ridge-delta (M4) ที่ 6 ชม. สำหรับการเตือน

POLL_MINUTES = int(os.getenv("P1_POLL_MINUTES", 10))
POLL_BACKOFF_MAX_MINUTES = 60     # หลังได้ 429 ถอยระยะ poll เป็น 2 เท่าทีละรอบ ไม่เกินค่านี้
POLL_LOG_MAX = 144                # เก็บผล poll ล่าสุดกี่รอบใน meta (144 รอบ × 10 นาที = 24 ชม.)
LOG_MAX_DELAY_HOURS = 3           # พยากรณ์ที่ issued_for เก่ากว่านี้ไม่บันทึกลง forecast_log (เป็นการทายย้อนหลัง)
RETRAIN_HOURS = int(os.getenv("P1_RETRAIN_HOURS", 24))
STALE_AFTER_HOURS = 2             # ข้อมูลเก่ากว่านี้ = แจ้งผู้ใช้ว่าข้อมูลไม่สด (กรมชลฯ ป้อนช้า 1–2 ชม. เป็นปกติ)
UPSTREAM_STALE_HOURS = 3          # สถานีต้นน้ำไม่มีค่าใหม่นานกว่านี้ = พยากรณ์เชื่อถือได้น้อยลง
MY_LEVEL_NEAR_M = 0.30            # พยากรณ์ขอบบนเข้าใกล้ "ระดับน้ำของฉัน" ในระยะนี้ = แจ้งในหน้า

# DEMO: เล่นข้อมูลน้ำท่วมปี 2567 แทนการดึงข้อมูลจริง (ใช้ตอนไม่มีเน็ตหรืออยากดูหน้าตาตอนน้ำขึ้น)
DEMO = os.getenv("P1_DEMO", "0") == "1"
DEMO_NOW = os.getenv("P1_DEMO_NOW", "2024-10-03 07:00")
COLLECT = os.getenv("P1_COLLECT", "1") == "1" and not DEMO
# โหมด demo ใช้ไฟล์โมเดลแยก และเทรนจากข้อมูลก่อน DEMO_NOW เท่านั้น (ไม่เห็นอนาคต)
MODEL_PATH = DATA_DIR / ("model_demo.joblib" if DEMO else "model.joblib")
