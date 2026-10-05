"use strict";

const TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const fmt = (v, n = 2) => (v == null ? "–" : Number(v).toFixed(n));
const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const dayLabel = (d) => `${d.getDate()} ${TH_MONTHS[d.getMonth()]}`;
const parseT = (s) => new Date(s.length === 16 ? s + ":00" : s); // เวลาไทยแบบไม่มี timezone

function el(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}

const STATUS_WORD = { normal: "ปกติ", watch: "เฝ้าระวัง", critical: "ถึงระดับวิกฤต", overflow: "ล้นตลิ่ง" };

/* ---------- ไม้วัดระดับน้ำ ---------- */
function drawGauge(d) {
  const svg = $("gauge");
  svg.replaceChildren();
  const top = 30, bot = 530, maxM = 6;
  const y = (m) => bot - (Math.max(0, Math.min(maxM, m)) / maxM) * (bot - top);
  const sx = 78, sw = 38; // ตัวไม้วัด

  // พื้นหลังแม่น้ำและตลิ่ง
  svg.append(el("rect", { x: 0, y: top - 10, width: 220, height: bot - top + 20, fill: "#F7F9F8" }));

  // ตัวไม้วัด: สีขาว แถบแดงสลับทุก 10 ซม. แบบไม้วัดจริง
  svg.append(el("rect", { x: sx, y: top, width: sw, height: bot - top, fill: "#fff", stroke: "#17262B", "stroke-width": 1 }));
  for (let k = 0; k < maxM * 10; k++) {
    const m0 = k / 10, half = (k % 2 === 0) ? sx : sx + sw / 2;
    const side = Math.floor(k / 10) % 2 === 0 ? half : (half === sx ? sx + sw / 2 : sx);
    svg.append(el("rect", { x: side, y: y(m0 + 0.05), width: sw / 2, height: y(m0) - y(m0 + 0.05), fill: "#C23A2B" }));
  }
  for (let m = 0; m <= maxM; m++) {
    svg.append(el("line", { x1: sx - 8, x2: sx, y1: y(m), y2: y(m), stroke: "#17262B", "stroke-width": 1.5 }));
    svg.append(el("text", { x: sx - 12, y: y(m) + 6, "text-anchor": "end", "font-size": 18, class: "num", fill: "#17262B" }, m));
  }

  // น้ำ
  const lvl = d.p1.level_m;
  const water = el("rect", { class: "water-fill", x: 0, y: y(lvl), width: 220, height: bot - y(lvl), fill: "#2C6E7A", "fill-opacity": 0.55 });
  svg.append(water);
  svg.append(el("line", { x1: 0, x2: 220, y1: y(lvl), y2: y(lvl), stroke: "#2C6E7A", "stroke-width": 3 }));

  // เกณฑ์
  const L = d.levels;
  [["overflow", "ล้นตลิ่ง", "#C23A2B"], ["critical", "วิกฤต", "#C23A2B"], ["watch", "เฝ้าระวัง", "#B97D0A"]].forEach(([k, label, c]) => {
    svg.append(el("line", { x1: sx + sw, x2: 220, y1: y(L[k]), y2: y(L[k]), stroke: c, "stroke-width": 1.5, "stroke-dasharray": k === "watch" ? "4 3" : "none" }));
    svg.append(el("text", { x: 218, y: y(L[k]) - 5, "text-anchor": "end", "font-size": 14, fill: c, class: "gauge-label" }, `${label} ${fmt(L[k])}`));
  });

  // พยากรณ์ 6 ชม.: ช่วงที่น่าจะเป็นและค่ากลาง ด้านซ้ายของไม้วัด
  const f6 = (d.forecast || []).find((f) => f.h === 6);
  if (f6) {
    const bx = 22;
    svg.append(el("rect", { x: bx - 6, y: y(f6.hi_m), width: 12, height: Math.max(2, y(f6.lo_m) - y(f6.hi_m)), fill: "#9CC3C9" }));
    svg.append(el("circle", { cx: bx, cy: y(f6.value_m), r: 5, fill: "#2C6E7A", stroke: "#fff", "stroke-width": 1.5 }));
    svg.append(el("text", { x: bx - 8, y: y(f6.hi_m) - 8, "font-size": 13, fill: "#4A5B60" }, "6 ชม."));
  }
  $("gauge-caption").textContent = `ระดับน้ำตอนนี้ ${fmt(lvl)} เมตร`;
}

/* ---------- กราฟ ---------- */
function drawChart(d) {
  const svg = $("chart");
  svg.replaceChildren();
  const W = Math.max(340, Math.round(svg.getBoundingClientRect().width) || 900);
  const H = W < 600 ? 280 : 340, ml = W < 600 ? 40 : 52, mr = 16, mt = 30, mb = 40;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const now = parseT(d.p1.t);
  const t0 = new Date(now.getTime() - 72 * 3600e3), t1 = new Date(now.getTime() + 6.5 * 3600e3);
  const hist = d.history.map((p) => ({ t: parseT(p.t), m: p.m }));
  const fc = d.forecast.map((f) => ({ t: parseT(f.t), m: f.value_m, lo: f.lo_m, hi: f.hi_m }));
  const vals = hist.map((p) => p.m).concat(fc.flatMap((f) => [f.lo, f.hi]), [d.levels.critical]);
  let lo = Math.floor((Math.min(...vals) - 0.2) * 2) / 2, hi = Math.ceil((Math.max(...vals) + 0.2) * 2) / 2;
  const x = (t) => ml + ((t - t0) / (t1 - t0)) * (W - ml - mr);
  const y = (m) => H - mb - ((m - lo) / (hi - lo)) * (H - mt - mb);

  const step = hi - lo > 4 ? 1 : 0.5;
  for (let m = lo; m <= hi + 1e-9; m += step) {
    svg.append(el("line", { x1: ml, x2: W - mr, y1: y(m), y2: y(m), stroke: "#DDE4E2" }));
    svg.append(el("text", { x: ml - 8, y: y(m) + 5, "text-anchor": "end", "font-size": 13, class: "num", fill: "#4A5B60" }, `${m.toFixed(1)}`));
  }
  svg.append(el("text", { x: 4, y: 16, "font-size": 12, fill: "#4A5B60" }, "ระดับตามไม้วัด (ม.)"));

  for (let t = new Date(t0); t <= t1; t = new Date(t.getTime() + 3600e3)) {
    if (t.getHours() !== 0) continue;
    svg.append(el("line", { x1: x(t), x2: x(t), y1: mt, y2: H - mb, stroke: "#DDE4E2" }));
    svg.append(el("text", { x: x(t) + 4, y: H - mb + 22, "font-size": 13, fill: "#4A5B60" }, dayLabel(t)));
  }

  [["critical", "วิกฤต", "#C23A2B", "none"], ["overflow", "ล้นตลิ่ง", "#C23A2B", "6 4"], ["watch", "เฝ้าระวัง", "#B97D0A", "4 3"]].forEach(([k, label, c, dash]) => {
    const v = d.levels[k];
    if (v < lo || v > hi) return;
    svg.append(el("line", { x1: ml, x2: W - mr, y1: y(v), y2: y(v), stroke: c, "stroke-width": 1.4, "stroke-dasharray": dash }));
    svg.append(el("text", { x: ml + 6, y: y(v) - 5, "font-size": 13, fill: c }, `${label} ${v.toFixed(2)} ม.`));
  });

  // เส้นค่าที่วัดได้ (ตัดเส้นเมื่อข้อมูลหายเกิน 3 ชม.)
  let path = "", prev = null;
  hist.forEach((p) => {
    const gap = prev && (p.t - prev.t) > 3 * 3600e3;
    path += `${!prev || gap ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.m).toFixed(1)} `;
    prev = p;
  });
  svg.append(el("path", { d: path, fill: "none", stroke: "#17262B", "stroke-width": 2.5, "stroke-linejoin": "round" }));

  // พยากรณ์
  if (fc.length) {
    const start = { t: now, m: d.p1.level_m, lo: d.p1.level_m, hi: d.p1.level_m };
    const pts = [start, ...fc];
    const band = pts.map((p) => `${x(p.t)},${y(p.hi)}`).concat(pts.slice().reverse().map((p) => `${x(p.t)},${y(p.lo)}`)).join(" ");
    svg.append(el("polygon", { points: band, fill: "#9CC3C9", "fill-opacity": 0.7 }));
    svg.append(el("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${x(p.t)},${y(p.m)}`).join(" "), fill: "none", stroke: "#2C6E7A", "stroke-width": 2.5, "stroke-dasharray": "6 4" }));
    fc.forEach((p, i) => {
      const c = el("circle", { cx: x(p.t), cy: y(p.m), r: 4.5, fill: "#2C6E7A" });
      c.append(el("title", {}, `อีก ${d.forecast[i].h} ชม. (${hhmm(p.t)} น.): ${fmt(p.m)} ม. ช่วง ${fmt(p.lo)}–${fmt(p.hi)} ม.`));
      svg.append(c);
    });
  }
  svg.append(el("line", { x1: x(now), x2: x(now), y1: mt, y2: H - mb, stroke: "#17262B", "stroke-dasharray": "2 3" }));
  svg.append(el("text", { x: x(now) - 6, y: mt + 12, "text-anchor": "end", "font-size": 13, fill: "#17262B" }, `ตอนนี้ ${hhmm(now)}`));
}

/* ---------- ข้อความ ---------- */
function levelSentence(d) {
  const v = d.p1.level_m, L = d.levels;
  if (v >= L.overflow) return `สูงกว่าระดับล้นตลิ่ง ${fmt(v - L.overflow)} ม. น้ำล้นเข้าพื้นที่ริมน้ำแล้ว`;
  if (v >= L.critical) return `สูงกว่าระดับวิกฤต ${fmt(v - L.critical)} ม.`;
  const word = v >= L.watch ? "เฝ้าระวัง" : "ปกติ";
  return `${word} ต่ำกว่าระดับวิกฤต ${fmt(L.critical - v)} ม.`;
}

function renderAlert(d) {
  const box = $("alert");
  box.className = "alert";
  let msg = null;
  if (d.p1.stale) {
    msg = `ข้อมูลล่าสุดวัดเมื่อ ${fmt(d.p1.age_hours, 1)} ชั่วโมงที่แล้ว ThaiWater อาจยังไม่อัปเดต ตัวเลขพยากรณ์อาจไม่ตรงกับสถานการณ์ตอนนี้`;
    box.classList.add("is-stale");
  } else if (d.p1.level_m >= d.levels.critical) {
    msg = `ระดับน้ำเกินระดับวิกฤต ${fmt(d.levels.critical)} ม. แล้ว ติดตามประกาศของจังหวัดเชียงใหม่และกรมชลประทาน`;
  } else if (d.warning && d.warning.level === "likely") {
    msg = `มีแนวโน้มว่าน้ำจะถึงระดับวิกฤต ${fmt(d.levels.critical)} ม. ภายใน ${d.warning.h} ชั่วโมง ยกของขึ้นที่สูงหากอยู่ริมน้ำ`;
  } else if (d.warning && d.warning.level === "possible") {
    msg = `มีโอกาสที่น้ำจะแตะระดับวิกฤตภายใน ${d.warning.h} ชั่วโมง ถ้าน้ำขึ้นเร็วกว่าที่โมเดลคาด`;
    box.classList.add("is-possible");
  }
  box.hidden = !msg;
  box.textContent = msg || "";
}

function renderForecast(d) {
  const ol = $("forecast");
  ol.replaceChildren();
  if (!d.forecast.length) {
    ol.innerHTML = "<li>ยังพยากรณ์ไม่ได้ เพราะข้อมูลต้นน้ำยังไม่ครบ 12 ชั่วโมงล่าสุด</li>";
  }
  d.forecast.forEach((f) => {
    const li = document.createElement("li");
    li.className = `is-${f.status}`;
    li.innerHTML = `<span class="when">อีก ${f.h} ชม. <span class="small">${hhmm(parseT(f.t))} น.</span></span>
      <span class="val">${fmt(f.value_m)}</span>
      <span class="range">${fmt(f.lo_m)}–${fmt(f.hi_m)} ม.${f.status !== "normal" ? ` ${STATUS_WORD[f.status]}` : ""}</span>`;
    ol.append(li);
  });
  const tr = d.trend12;
  const words = { rising: "น้ำน่าจะขึ้นต่อ", falling: "น้ำน่าจะลดลง", steady: "น้ำน่าจะทรงตัว" };
  $("trend").textContent = tr ? `ใน 12 ชั่วโมง ${words[tr.direction]} (บอกเป็นแนวโน้ม เพราะยังแม่นไม่พอจะให้ตัวเลข)` : "";
}

function renderUpstream(d) {
  const box = $("upstream");
  box.replaceChildren();
  d.upstream.forEach((u) => {
    const div = document.createElement("div");
    div.className = "up-item";
    const over = u.vs_bank_m != null && u.vs_bank_m >= 0;
    const bank = u.vs_bank_m == null ? "ไม่มีข้อมูล" : over ? `สูงกว่าตลิ่ง ${fmt(u.vs_bank_m)} ม.` : `ต่ำกว่าตลิ่ง ${fmt(-u.vs_bank_m)} ม.`;
    const ch = u.change_3h_m == null ? "" : Math.abs(u.change_3h_m) < 0.02 ? "3 ชม. ที่ผ่านมาแทบไม่เปลี่ยน"
      : `3 ชม. ที่ผ่านมา${u.change_3h_m > 0 ? "ขึ้น" : "ลง"} ${fmt(Math.abs(u.change_3h_m))} ม.`;
    div.innerHTML = `<h3>${u.river} ${u.name}<span class="code">${u.code}</span></h3>
      <p class="bank ${over ? "is-over" : ""}">${bank}</p><p>${ch}</p><p class="small">${u.travel}</p>`;
    box.append(div);
  });
}

let last = null;
function render(d) {
  last = d;
  const t = parseT(d.p1.t);
  $("updated").textContent = ` วัดเมื่อ ${hhmm(t)} น. ${dayLabel(t)} ${t.getFullYear() + 543}`;
  $("level-value").textContent = fmt(d.p1.level_m);
  $("level-note").textContent = levelSentence(d);
  $("discharge").textContent = d.p1.discharge_m3s != null ? `ปริมาณน้ำ ${fmt(d.p1.discharge_m3s, 0)} ลบ.ม./วินาที` : "";
  renderAlert(d);
  renderForecast(d);
  drawGauge(d);
  drawChart(d);
  renderUpstream(d);
  const f6 = d.forecast.find((f) => f.h === 6);
  const tr = parseT(d.model.trained_at);
  $("model-info").textContent = `โมเดลเทรนล่าสุด ${dayLabel(tr)} ${hhmm(tr)} น. จากข้อมูล ${d.model.train_hours.toLocaleString("th-TH")} ชั่วโมง`
    + (f6 && f6.rmse_cm ? ` ทดสอบย้อนหลังแล้วคลาดเคลื่อนเฉลี่ยประมาณ ${f6.rmse_cm} ซม. ที่ล่วงหน้า 6 ชั่วโมง` : "");
}

/* ---------- โหลดข้อมูล ---------- */
let demo = null, playing = null, pending = null;

async function load(at) {
  const url = at ? `/api/forecast?at=${encodeURIComponent(at)}` : "/api/forecast";
  try {
    const r = await fetch(url);
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
    render(d);
    if (d.mode === "demo" && !demo) setupDemo(d);
  } catch (e) {
    $("level-note").textContent = `โหลดข้อมูลไม่ได้: ${e.message}`;
    setTimeout(() => load(at), 30000);
  }
}

function setupDemo(d) {
  const [a, b] = d.demo_range.map(parseT);
  demo = { start: a, hours: Math.round((b - a) / 3600e3) };
  const s = $("demo-slider");
  s.max = demo.hours;
  s.value = Math.round((parseT(d.now) - a) / 3600e3);
  $("demo-bar").hidden = false;
  const label = () => {
    const t = new Date(demo.start.getTime() + s.value * 3600e3);
    $("demo-time").textContent = `${dayLabel(t)} ${hhmm(t)} น.`;
    return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")} ${hhmm(t)}`;
  };
  label();
  s.addEventListener("input", () => {
    const at = label();
    clearTimeout(pending);
    pending = setTimeout(() => load(at), 120);
  });
  $("demo-play").addEventListener("click", (ev) => {
    if (playing) {
      clearInterval(playing); playing = null;
      ev.target.textContent = "เล่น"; ev.target.setAttribute("aria-pressed", "false");
      return;
    }
    ev.target.textContent = "หยุด"; ev.target.setAttribute("aria-pressed", "true");
    playing = setInterval(() => {
      if (+s.value >= demo.hours) s.value = 13; else s.value = +s.value + 1;
      load(label());
    }, 700);
  });
}

window.addEventListener("resize", () => { if (last) drawChart(last); });
load(new URLSearchParams(location.search).get("at")); // โหมดสาธิต: ?at=2024-10-05 02:00
setInterval(() => { if (!demo) load(); }, 5 * 60 * 1000);
