// ถ่ายภาพหน้าจอโหมดสาธิต 3 เวลา × 2 ความกว้าง แล้วตรวจ console error, การล้นแนวนอน และสิ่งที่ต้องเห็นเหนือขอบจอ
// ใช้: (เปิด P1_DEMO=1 uvicorn app.main:app --port 8000 ก่อน)  node tools/screens.mjs [base_url] [out_dir]
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const OUT = process.argv[3] || "shots";
const TIMES = ["2024-09-29 12:00", "2024-10-03 07:00", "2024-10-05 02:00"];
const SIZES = [{ w: 390, h: 740 }, { w: 1280, h: 900 }];
const FOLD_IDS = ["level-value", "status-word", "fc-summary", "advice-list", "fresh-text"]; // 4 คำถามหลัก

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
let failed = 0;
for (const { w, h } of SIZES) {
  for (const at of TIMES) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("requestfailed", (r) => { if (!r.url().includes("fonts.g")) errors.push(`request failed ${r.url()}`); });
    await page.goto(`${BASE}/?at=${encodeURIComponent(at)}`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => document.getElementById("level-value").textContent !== "–");
    const report = await page.evaluate((ids) => {
      const overflowX = document.documentElement.scrollWidth > window.innerWidth;
      const below = ids.filter((id) => {
        const n = document.getElementById(id);
        return !n || n.getBoundingClientRect().bottom > window.innerHeight;
      });
      // ข้อความที่ล้นกล่องของตัวเอง (กว้างเกินพ่อแม่)
      const clipped = [...document.querySelectorAll("main *, header *")].filter((n) => {
        if (n.closest("svg") || !n.offsetParent) return false;
        return n.scrollWidth > n.clientWidth + 1 && getComputedStyle(n).overflowX === "visible" && n.children.length === 0;
      }).map((n) => n.id || n.className || n.tagName).slice(0, 5);
      return { overflowX, below, clipped };
    }, FOLD_IDS);
    const name = `${OUT}/${w}_${at.replace(/[: ]/g, "-")}`;
    await page.screenshot({ path: `${name}_fold.png` });
    await page.screenshot({ path: `${name}_full.png`, fullPage: true });
    const problems = [...errors.map((e) => `console: ${e}`),
      ...(report.overflowX ? ["page scrolls horizontally"] : []),
      ...(w <= 400 ? report.below.map((id) => `#${id} below the fold`) : []),
      ...report.clipped.map((c) => `text overflows: ${c}`)];
    console.log(`${problems.length ? "FAIL" : "ok  "} ${w}px ${at}${problems.length ? "\n     " + problems.join("\n     ") : ""}`);
    failed += problems.length ? 1 : 0;
    await page.close();
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
