// "ระดับน้ำของฉัน" เก็บใน localStorage ของเครื่องนี้เท่านั้น (อ่าน/เขียนผิดพลาดได้ในโหมดส่วนตัว จึงครอบ try/catch)
import { t } from "./i18n.js";
import { $, fmt } from "./util.js";

const KEY = "p1.myLevel";
const MIN = 0.5, MAX = 8;

export function getMyLevel() {
  try {
    const v = parseFloat(localStorage.getItem(KEY));
    return Number.isFinite(v) && v >= MIN && v <= MAX ? v : null;
  } catch { return null; }
}

function store(v) {
  try { v == null ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, String(v)); } catch { /* ใช้ได้เฉพาะรอบนี้ */ }
}

function showCurrent(v) {
  $("my-current").textContent = v == null ? t("my.unset") : t("my.current", { level: fmt(v) });
  $("my-input").value = v == null ? "" : v.toFixed(2);
}

export function setupMyLevel(onChange) {
  let current = getMyLevel();
  showCurrent(current);
  $("my-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = parseFloat($("my-input").value.replace(",", "."));
    const err = $("my-error");
    if (!Number.isFinite(v) || v < MIN || v > MAX) { err.textContent = t("my.invalid"); err.hidden = false; return; }
    err.hidden = true;
    current = Math.round(v * 100) / 100;
    store(current); showCurrent(current); onChange(current);
  });
  $("my-clear").addEventListener("click", () => {
    current = null;
    store(null); showCurrent(null); $("my-error").hidden = true; onChange(null);
  });
  return current;
}
