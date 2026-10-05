// ความสดของข้อมูล: นับ "กี่นาทีที่แล้ว" ใหม่ทุกนาที โดยไม่ต้องโหลดข้อมูลใหม่
import { t } from "./i18n.js";
import { $, fullDate, hhmm, parseT } from "./util.js";

const STALE_MIN = 120; // ตรงกับ config.STALE_AFTER_HOURS
let st = null;

function ago(min) {
  if (min < 5) return t("fresh.just_now");
  if (min < 60) return t("fresh.ago_min", { n: min });
  return t("fresh.ago_hm", { h: Math.floor(min / 60), m: min % 60 });
}

function tick() {
  if (!st) return;
  // โหมดสาธิตเวลาไม่เดินตามนาฬิกาจริง ใช้อายุข้อมูล ณ เวลาที่เลือก
  const min = st.demo ? st.ageMin : st.ageMin + Math.floor((Date.now() - st.loadedAt) / 60000);
  const stale = st.serverStale || (!st.demo && min > STALE_MIN);
  $("fresh-text").textContent = t("fresh.measured", { ago: ago(min) });
  $("fresh-at").textContent = t("fresh.at", { time: hhmm(st.measured), date: fullDate(st.measured) });
  $("fresh-badge").hidden = !stale;
  $("fresh").classList.toggle("is-stale", stale);
  $("fresh-stale").hidden = !stale;
}

// sameAsBefore = รีเฟรชแล้วได้ค่าวัดเดิม: บอกตรง ๆ ว่ายังไม่มีค่าใหม่ ไม่ทำให้ดูเหมือนข้อมูลใหม่
export function setFresh(d, sameAsBefore) {
  st = { measured: parseT(d.p1.t), ageMin: d.p1.age_minutes ?? Math.round((d.p1.age_hours || 0) * 60),
    loadedAt: Date.now(), demo: d.mode === "demo", serverStale: d.p1.stale };
  const parts = [];
  if (st.demo) parts.push(t("fresh.demo"));
  if (d.fetch && d.fetch.at) {
    parts.push(t("fresh.checked", { time: hhmm(parseT(d.fetch.at.replace(" ", "T").slice(0, 16))) }));
    if (d.fetch.ok === false) parts.push(t("fresh.fetch_failed"));
  }
  if (sameAsBefore) parts.push(t("fresh.no_new"));
  $("fresh-checked").textContent = parts.join(" · ");
  tick();
}

setInterval(tick, 60000);
