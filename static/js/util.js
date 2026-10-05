// เครื่องมือเล็ก ๆ ที่ทุก module ใช้ร่วมกัน
import { t } from "./i18n.js";

const NS = "http://www.w3.org/2000/svg";
export const $ = (id) => document.getElementById(id);
export const fmt = (v, n = 2) => (v == null ? "–" : Number(v).toFixed(n));
export const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
export const dayLabel = (d) => `${d.getDate()} ${t("months")[d.getMonth()]}`;
export const fullDate = (d) => `${dayLabel(d)} ${d.getFullYear() + t("year_offset")}`;
export const parseT = (s) => new Date(s.length === 16 ? s + ":00" : s); // เวลาไทยแบบไม่มี timezone

// สร้าง element ของ SVG; สีให้ใช้ class ที่อิง CSS variables ไม่ใส่ hex ตรง ๆ (รองรับธีมมืด)
export function el(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}

// สร้าง element HTML พร้อมข้อความ (ใช้ textContent เสมอ ไม่ประกอบ HTML จากข้อความ)
export function h(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
