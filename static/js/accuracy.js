// หน้าความแม่นย้อนหลัง: สรุป error ของพยากรณ์ที่ออกจริง (forecast_log) และกราฟพยากรณ์เทียบจริง
import { loadI18n, t } from "./i18n.js";
import { $, dayLabel, el, fmt, h, hhmm, parseT } from "./util.js";

let days = 7, horizon = 6, last = null;
const cell = (v, n = 1) => (v == null ? "–" : fmt(v, n));

function row(cells, mainIdx) {
  const tr = h("tr");
  cells.forEach((c, i) => {
    const n = h(i === 0 ? "th" : "td", i === mainIdx ? "is-main" : null, c);
    if (i === 0) n.scope = "row";
    tr.append(n);
  });
  return tr;
}

function renderCv(d) {
  $("acc-cv").hidden = !d.cv.length;
  if (d.model_trained_at) {
    const tr = parseT(d.model_trained_at);
    $("acc-cv-lead").textContent = t("acc.cv_lead", { date: dayLabel(tr), time: hhmm(tr) });
  }
  $("cv-body").replaceChildren(...d.cv.map((c) => row([t("acc.row_h", { h: c.h }), cell(c.rmse_cm_ensemble),
    cell(c.rmse_cm_ridge), cell(c.rmse_cm_gbm), cell(c.rmse_cm_persistence)], 1)));
}

function renderSummary(d) {
  const log = d.log, cv = Object.fromEntries(d.cv.map((c) => [c.h, c.rmse_cm_ensemble]));
  const since = log.first_logged ? parseT(log.first_logged.replace(" ", "T").slice(0, 16)) : null;
  $("acc-since").textContent = since ? t("acc.since", { date: dayLabel(since), time: hhmm(since), pending: log.pending }) : "";
  const any = log.horizons.some((x) => x.n > 0);
  const status = $("acc-status");
  status.hidden = any;
  status.textContent = any ? "" : t("acc.empty");
  $("acc-body").replaceChildren(...log.horizons.map((x) => {
    if (!x.n) return row([t("acc.row_h", { h: x.h }), "0", t("acc.no_rows"), "–", "–", "–", "–", "–", cell(cv[x.h])], 2);
    const m = x.models;
    const cover = m.ensemble.coverage == null ? "–" : `${Math.round(m.ensemble.coverage * 100)}%`;
    const bias = m.ensemble.bias_cm == null ? "–" : `${m.ensemble.bias_cm > 0 ? "+" : ""}${fmt(m.ensemble.bias_cm, 1)}`;
    return row([t("acc.row_h", { h: x.h }), String(x.n), cell(m.ensemble.rmse_cm), cell(m.ridge?.rmse_cm), cell(m.gbm?.rmse_cm),
      cell(x.persistence_rmse_cm), cover, bias, cell(cv[x.h])], 2);
  }));
  const tr = log.trend12;
  $("acc-trend12").textContent = tr ? t("acc.trend12", { pct: Math.round(tr.hit_rate * 100), n: tr.n }) : t("acc.trend12_none");
}

function drawChart(d) {
  const svg = $("acc-chart");
  svg.replaceChildren();
  svg.setAttribute("aria-label", t("acc.chart_aria", { h: horizon }));
  const pts = d.log.series.map((p) => ({ ...p, t: parseT(p.t) }));
  const W = Math.max(320, Math.round(svg.getBoundingClientRect().width) || 900);
  const H = W < 600 ? 260 : 320, ml = W < 600 ? 40 : 52, mr = 16, mt = 26, mb = 40;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (!pts.length) {
    svg.append(el("text", { class: "c-text-soft", x: W / 2, y: H / 2, "text-anchor": "middle", "font-size": 15 }, t("acc.chart_empty")));
    return;
  }
  const t0 = parseT(d.log.from.replace(" ", "T")), t1 = parseT(d.log.to.replace(" ", "T"));
  const vals = pts.flatMap((p) => [p.actual_m, p.lo_m, p.hi_m, p.pred_m]).filter((v) => v != null);
  const lo = Math.floor((Math.min(...vals) - 0.1) * 2) / 2, hi = Math.ceil((Math.max(...vals) + 0.1) * 2) / 2;
  const x = (tt) => ml + ((tt - t0) / (t1 - t0)) * (W - ml - mr);
  const y = (m) => H - mb - ((m - lo) / (hi - lo)) * (H - mt - mb);
  const step = hi - lo > 4 ? 1 : hi - lo > 1.5 ? 0.5 : 0.25;
  for (let m = lo; m <= hi + 1e-9; m += step) {
    svg.append(el("line", { class: "c-grid", x1: ml, x2: W - mr, y1: y(m), y2: y(m) }));
    svg.append(el("text", { class: "num c-text-soft", x: ml - 8, y: y(m) + 5, "text-anchor": "end", "font-size": 13 }, m.toFixed(2)));
  }
  svg.append(el("text", { class: "c-text-soft", x: 4, y: 16, "font-size": 12 }, t("acc.chart_axis")));
  const dayStep = days > 10 ? 5 : 1;
  for (let tt = new Date(t0); tt <= t1; tt = new Date(tt.getTime() + 3600e3)) {
    if (tt.getHours() !== 0 || (tt.getDate() % dayStep)) continue;
    svg.append(el("line", { class: "c-grid", x1: x(tt), x2: x(tt), y1: mt, y2: H - mb }));
    svg.append(el("text", { class: "c-text-soft", x: x(tt) + 4, y: H - mb + 22, "font-size": 13 }, dayLabel(tt)));
  }
  // เส้นตัดเมื่อเว้นเกิน 3 ชม. เพื่อไม่ลากผ่านช่วงที่ไม่มีข้อมูล
  const path = (key) => {
    let s = "", prev = null;
    pts.forEach((p) => {
      if (p[key] == null) { prev = null; return; }
      s += `${!prev || p.t - prev.t > 3 * 3600e3 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p[key]).toFixed(1)} `;
      prev = p;
    });
    return s;
  };
  const band = pts.filter((p) => p.lo_m != null);
  band.forEach((p) => svg.append(el("line", { class: "c-band-tick", x1: x(p.t), x2: x(p.t), y1: y(p.hi_m), y2: y(p.lo_m) })));
  svg.append(el("path", { class: "c-fc", d: path("pred_m") }));
  svg.append(el("path", { class: "c-obs", d: path("actual_m") }));
}

async function load() {
  try {
    const r = await fetch(`/api/accuracy?days=${days}&h=${horizon}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
    last = d;
    renderCv(d);
    const live = d.log != null;
    $("acc-live").hidden = !live;
    if (!live) {
      $("acc-status").hidden = false;
      $("acc-status").textContent = t("acc.demo");
      return;
    }
    renderSummary(d);
    drawChart(d);
  } catch (e) {
    $("acc-status").hidden = false;
    $("acc-status").textContent = t("adm.err", { msg: e.message });
  }
}

await loadI18n(new URLSearchParams(location.search).get("lang") || "th");
const hs = $("acc-h");
[1, 2, 3, 4, 5, 6].forEach((k) => {
  const lab = h("label");
  const inp = h("input");
  Object.assign(inp, { type: "radio", name: "h", value: String(k), checked: k === horizon });
  lab.append(inp, " ", t("acc.row_h", { h: k }));
  hs.append(lab);
});
document.querySelectorAll("input[name=days]").forEach((n) => n.addEventListener("change", () => { days = +n.value; load(); }));
hs.addEventListener("change", (ev) => { horizon = +ev.target.value; load(); });
window.addEventListener("resize", () => { if (last && last.log) drawChart(last); });
load();
