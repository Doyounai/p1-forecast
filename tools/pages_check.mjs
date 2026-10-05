// ตรวจหน้ารอง (ความแม่นย้อนหลัง, ข้อมูลสำหรับนักวิจัย, สถานะระบบ) ที่ 390 และ 1280 px
// ใช้: node tools/pages_check.mjs [base_url] [out_dir]
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const OUT = process.argv[3] || "shots";
// ready = เงื่อนไขว่าหน้าโหลดข้อมูลเสร็จ
const PAGES = [
  { path: "accuracy.html", ready: () => document.getElementById("acc-cv-lead").textContent !== "" || !document.getElementById("acc-status").hidden },
  { path: "data.html", ready: () => document.getElementById("st-body").children.length > 0 },
  { path: "admin.html", ready: () => document.getElementById("adm-issues").children.length > 0 },
];

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
let failed = 0;
for (const w of [390, 1280]) {
  for (const p of PAGES) {
    const page = await browser.newPage({ viewport: { width: w, height: 900 } });
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("requestfailed", (r) => { if (!r.url().includes("fonts.g")) errors.push(`request failed ${r.url()}`); });
    await page.goto(`${BASE}/${p.path}`, { waitUntil: "networkidle" });
    await page.waitForFunction(p.ready);
    const rep = await page.evaluate(() => ({
      overflowX: document.documentElement.scrollWidth > window.innerWidth,
      missingKeys: [...document.querySelectorAll("body *")].filter((n) => n.children.length === 0 && /^[a-z]+\.[a-z0-9_.]+$/.test(n.textContent.trim())).map((n) => n.textContent.trim()).slice(0, 5),
    }));
    await page.screenshot({ path: `${OUT}/${w}_${p.path.replace(".html", "")}.png`, fullPage: true });
    const problems = [...errors, ...(rep.overflowX ? ["page scrolls horizontally"] : []), ...rep.missingKeys.map((k) => `missing i18n: ${k}`)];
    console.log(`${problems.length ? "FAIL" : "ok  "} ${w}px ${p.path}${problems.length ? "\n     " + problems.join("\n     ") : ""}`);
    failed += problems.length ? 1 : 0;
    await page.close();
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
