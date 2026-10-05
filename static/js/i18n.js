// ข้อความทั้งหมดอยู่ใน static/i18n.json ไฟล์เดียว (รวมคำแนะนำตามสถานะ) แก้ข้อความได้โดยไม่ต้องแตะโค้ด
let dict = {};
export let lang = "th";

export async function loadI18n(want = "th") {
  const r = await fetch("i18n.json");
  const all = await r.json();
  lang = all[want] ? want : "th";
  dict = all[lang];
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria]").forEach((n) => n.setAttribute("aria-label", t(n.dataset.i18nAria)));
  document.title = t(document.body.dataset.titleKey || "meta.title");
}

// t("fc.summary", {h: 6, v: "3.45"}) แทน {h} {v} ในข้อความ; คืน key ถ้าไม่มีข้อความ (เห็นได้ง่ายตอนทดสอบ)
export function t(key, vars) {
  const s = dict[key];
  if (s == null) return key;
  if (!vars || typeof s !== "string") return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? vars[k] : m));
}
