// กราฟ 72 ชม. ที่ผ่านมา + พยากรณ์ 6 ชม. (เฟส 2 จะเพิ่มช่วงเวลา tooltip และเส้นเทียบปี 2567)
import { t } from "./i18n.js";
import { $, dayLabel, el, fmt, hhmm, parseT } from "./util.js";

export function drawChart(d, my) {
  const svg = $("chart");
  svg.replaceChildren();
  const W = Math.max(320, Math.round(svg.getBoundingClientRect().width) || 900);
  const H = W < 600 ? 280 : 340, ml = W < 600 ? 40 : 52, mr = 16, mt = 30, mb = 40;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const now = parseT(d.p1.t);
  const t0 = new Date(now.getTime() - 72 * 3600e3), t1 = new Date(now.getTime() + 6.5 * 3600e3);
  const hist = d.history.map((p) => ({ t: parseT(p.t), m: p.m }));
  const fc = d.forecast.map((f) => ({ t: parseT(f.t), m: f.value_m, lo: f.lo_m, hi: f.hi_m }));
  const vals = hist.map((p) => p.m).concat(fc.flatMap((f) => [f.lo, f.hi]), [d.levels.critical], my != null ? [my] : []);
  const lo = Math.floor((Math.min(...vals) - 0.2) * 2) / 2, hi = Math.ceil((Math.max(...vals) + 0.2) * 2) / 2;
  const x = (tt) => ml + ((tt - t0) / (t1 - t0)) * (W - ml - mr);
  const y = (m) => H - mb - ((m - lo) / (hi - lo)) * (H - mt - mb);

  const step = hi - lo > 4 ? 1 : 0.5;
  for (let m = lo; m <= hi + 1e-9; m += step) {
    svg.append(el("line", { class: "c-grid", x1: ml, x2: W - mr, y1: y(m), y2: y(m) }));
    svg.append(el("text", { class: "num c-text-soft", x: ml - 8, y: y(m) + 5, "text-anchor": "end", "font-size": 13 }, m.toFixed(1)));
  }
  svg.append(el("text", { class: "c-text-soft", x: 4, y: 16, "font-size": 12 }, t("chart.axis")));

  for (let tt = new Date(t0); tt <= t1; tt = new Date(tt.getTime() + 3600e3)) {
    if (tt.getHours() !== 0) continue;
    svg.append(el("line", { class: "c-grid", x1: x(tt), x2: x(tt), y1: mt, y2: H - mb }));
    svg.append(el("text", { class: "c-text-soft", x: x(tt) + 4, y: H - mb + 22, "font-size": 13 }, dayLabel(tt)));
  }

  [["critical", "crit", ""], ["overflow", "crit", " dashed-long"], ["watch", "watch", " dashed"]].forEach(([k, cls, dash]) => {
    const v = d.levels[k];
    if (v < lo || v > hi) return;
    svg.append(el("line", { class: `c-th g-th-${cls}${dash}`, x1: ml, x2: W - mr, y1: y(v), y2: y(v) }));
    svg.append(el("text", { class: `g-th-text-${cls}`, x: ml + 6, y: y(v) - 5, "font-size": 13 }, `${t(`status.${k}`)} ${v.toFixed(2)} ม.`));
  });

  if (my != null && my >= lo && my <= hi) {
    svg.append(el("line", { class: "g-my", x1: ml, x2: W - mr, y1: y(my), y2: y(my) }));
    svg.append(el("text", { class: "c-text", x: W - mr - 4, y: y(my) - 5, "text-anchor": "end", "font-size": 13 }, `${t("chart.my")} ${fmt(my)} ม.`));
  }

  // เส้นค่าที่วัดได้ (ตัดเส้นเมื่อข้อมูลหายเกิน 3 ชม.)
  let path = "", prev = null;
  hist.forEach((p) => {
    const gap = prev && (p.t - prev.t) > 3 * 3600e3;
    path += `${!prev || gap ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.m).toFixed(1)} `;
    prev = p;
  });
  svg.append(el("path", { class: "c-obs", d: path }));

  // พยากรณ์
  if (fc.length) {
    const start = { t: now, m: d.p1.level_m, lo: d.p1.level_m, hi: d.p1.level_m };
    const pts = [start, ...fc];
    const band = pts.map((p) => `${x(p.t)},${y(p.hi)}`).concat(pts.slice().reverse().map((p) => `${x(p.t)},${y(p.lo)}`)).join(" ");
    svg.append(el("polygon", { class: "c-band", points: band }));
    svg.append(el("path", { class: "c-fc", d: pts.map((p, i) => `${i ? "L" : "M"}${x(p.t)},${y(p.m)}`).join(" ") }));
    fc.forEach((p, i) => {
      const c = el("circle", { class: "g-dot", cx: x(p.t), cy: y(p.m), r: 4.5 });
      c.append(el("title", {}, t("chart.point", { h: d.forecast[i].h, time: hhmm(p.t), v: fmt(p.m), lo: fmt(p.lo), hi: fmt(p.hi) })));
      svg.append(c);
    });
  }
  svg.append(el("line", { class: "c-now", x1: x(now), x2: x(now), y1: mt, y2: H - mb }));
  svg.append(el("text", { class: "c-text", x: x(now) - 6, y: mt + 12, "text-anchor": "end", "font-size": 13 }, t("chart.now", { time: hhmm(now) })));
}
