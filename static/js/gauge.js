// ไม้วัดระดับน้ำแบบแถบแดง-ขาว (เอกลักษณ์ของหน้า)
import { t } from "./i18n.js";
import { $, el, fmt } from "./util.js";

export function drawGauge(d, my) {
  const svg = $("gauge");
  svg.replaceChildren();
  const top = 30, bot = 530, maxM = 6;
  const y = (m) => bot - (Math.max(0, Math.min(maxM, m)) / maxM) * (bot - top);
  const sx = 78, sw = 38; // ตัวไม้วัด

  svg.append(el("rect", { class: "g-bg", x: 0, y: top - 10, width: 220, height: bot - top + 20 }));

  // ตัวไม้วัด: สีขาว แถบแดงสลับทุก 10 ซม. แบบไม้วัดจริง
  svg.append(el("rect", { class: "g-staff", x: sx, y: top, width: sw, height: bot - top }));
  for (let k = 0; k < maxM * 10; k++) {
    const m0 = k / 10, half = (k % 2 === 0) ? sx : sx + sw / 2;
    const side = Math.floor(k / 10) % 2 === 0 ? half : (half === sx ? sx + sw / 2 : sx);
    svg.append(el("rect", { class: "g-red", x: side, y: y(m0 + 0.05), width: sw / 2, height: y(m0) - y(m0 + 0.05) }));
  }
  for (let m = 0; m <= maxM; m++) {
    svg.append(el("line", { class: "g-tick", x1: sx - 8, x2: sx, y1: y(m), y2: y(m) }));
    svg.append(el("text", { class: "num g-text", x: sx - 12, y: y(m) + 6, "text-anchor": "end", "font-size": 18 }, m));
  }

  // น้ำ
  const lvl = d.p1.level_m;
  svg.append(el("rect", { class: "g-water", x: 0, y: y(lvl), width: 220, height: bot - y(lvl) }));
  svg.append(el("line", { class: "g-surface", x1: 0, x2: 220, y1: y(lvl), y2: y(lvl) }));

  // เกณฑ์
  const L = d.levels;
  ["overflow", "critical", "watch"].forEach((k) => {
    const cls = k === "watch" ? "watch" : "crit";
    svg.append(el("line", { class: `g-th g-th-${cls}${k === "watch" ? " dashed" : ""}`, x1: sx + sw, x2: 220, y1: y(L[k]), y2: y(L[k]) }));
    svg.append(el("text", { class: `gauge-label g-th-text-${cls}`, x: 218, y: y(L[k]) - 5, "text-anchor": "end", "font-size": 14 },
      `${t(`status.${k}`)} ${fmt(L[k])}`));
  });

  // ระดับน้ำของฉัน: เส้นประสีตะกอน พร้อมหมุดด้านซ้ายให้เห็นได้แม้จอแคบ
  if (my != null) {
    svg.append(el("line", { class: "g-my", x1: 0, x2: 220, y1: y(my), y2: y(my) }));
    svg.append(el("path", { class: "g-my-pin", d: `M0,${y(my) - 9} L14,${y(my)} L0,${y(my) + 9} Z` }));
    svg.append(el("text", { class: "gauge-label g-text", x: sx + sw + 4, y: y(my) + 16, "font-size": 14 }, `${t("my.line")} ${fmt(my)}`));
  }

  // พยากรณ์ 6 ชม.: ช่วงที่น่าจะเป็นและค่ากลาง ด้านซ้ายของไม้วัด
  const f6 = (d.forecast || []).find((f) => f.h === 6);
  if (f6) {
    const bx = 34;
    svg.append(el("rect", { class: "g-band", x: bx - 6, y: y(f6.hi_m), width: 12, height: Math.max(2, y(f6.lo_m) - y(f6.hi_m)) }));
    svg.append(el("circle", { class: "g-dot", cx: bx, cy: y(f6.value_m), r: 5 }));
    svg.append(el("text", { class: "g-text-soft", x: bx - 14, y: y(f6.hi_m) - 8, "font-size": 13 }, t("gauge.f6")));
  }
  $("gauge-caption").textContent = t("gauge.caption", { v: fmt(lvl) });
}
