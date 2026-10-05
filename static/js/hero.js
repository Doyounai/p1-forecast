// ส่วนเหนือขอบจอ: ระดับน้ำตอนนี้, อีกไม่กี่ชั่วโมง, ควรทำอะไร, ความเชื่อถือได้ของพยากรณ์
import { t } from "./i18n.js";
import { $, fmt, h, hhmm, parseT } from "./util.js";

function levelSentence(d) {
  const v = d.p1.level_m, L = d.levels;
  if (v >= L.overflow) return t("level.over_overflow", { d: fmt(v - L.overflow) });
  if (v >= L.critical) return t("level.over_critical", { d: fmt(v - L.critical) });
  return t("level.below_critical", { d: fmt(L.critical - v) });
}

function setLine(id, text, cls) {
  const n = $(id);
  n.hidden = !text;
  n.textContent = text || "";
  n.className = cls || n.dataset.base || "";
}

function windowText(w, key, vars) {
  const from = hhmm(parseT(w.earliest)), to = hhmm(parseT(w.latest));
  return t(w.open_end ? `${key}_open` : key, { ...vars, from, to });
}

export function renderNow(d) {
  const st = d.p1.status;
  $("level-value").textContent = fmt(d.p1.level_m);
  const word = $("status-word");
  word.textContent = t(`status.${st}`);
  word.className = `status-word is-${st}`;
  $("level-note").textContent = levelSentence(d);
  $("discharge").textContent = d.p1.discharge_m3s != null ? t("level.discharge", { q: fmt(d.p1.discharge_m3s, 0) }) : "";
}

export function renderOutlook(d) {
  const f6 = d.forecast.find((f) => f.h === 6);
  if (f6) {
    $("fc-summary").textContent = t("fc.summary", { h: 6, v: fmt(f6.value_m) });
    $("fc-range").textContent = t("fc.range", { lo: fmt(f6.lo_m), hi: fmt(f6.hi_m) });
  } else {
    $("fc-summary").textContent = t("fc.none");
    $("fc-range").textContent = "";
  }

  // เวลาที่อาจถึงเกณฑ์ถัดไป (backend คำนวณจากค่าพยากรณ์และช่วงความไม่แน่นอน ไม่เกิน 6 ชม.)
  const nt = d.next_threshold;
  let warn = null, warnCls = "";
  if (nt) {
    warn = windowText(nt, "fc.eta", { label: t(`status.${nt.key}`), level: fmt(nt.level_m) });
    warnCls = `is-${nt.key}`;
  } else if (d.warning && d.warning.level === "possible") {
    warn = t("alert.possible", { h: d.warning.h });
    warnCls = "is-watch";
  }
  setLine("fc-eta", warn, `fc-eta ${warnCls}`);

  const my = d.my_level;
  let myText = null;
  if (my) {
    const level = fmt(my.level_m);
    if (my.reached) myText = t("my.reached", { level });
    else if (my.eta) myText = windowText(my.eta, "my.eta", { level });
    else if (my.near) myText = t("my.near", { level });
  }
  setLine("my-status", myText, "my-status");

  const tr = d.trend12;
  // แนวโน้มที่ถูกซ่อน: บอกเหตุผลสั้น ๆ ห้ามแสดงว่า "ทรงตัว" แทน (no_forecast ไม่ต้องบอก มีข้อความอื่นอยู่แล้ว)
  const hidden = !tr && ["low_flow", "level_controlled"].includes(d.trend12_hidden_reason);
  $("trend").textContent = tr ? t(`fc.trend.${tr.direction}`) : hidden ? t(`fc.trend_hidden.${d.trend12_hidden_reason}`) : "";
  $("trend-note").textContent = tr ? t("fc.trend_note") : "";

  // ความแม่นต่ำ: บอกเหตุผลทุกข้อที่ backend ส่งมา
  const rel = d.reliability;
  const box = $("reliability");
  box.hidden = !rel || !rel.low;
  if (rel && rel.low) {
    const ul = $("rel-reasons");
    ul.replaceChildren(...rel.reasons.map((r) => {
      const key = r.code === "out_of_train_range" ? `rel.out_of_train_range.${r.side}` : `rel.${r.code}`;
      return h("li", null, t(key, { max: fmt(r.train_max), min: fmt(r.train_min), stations: (r.stations || []).join(", "), age: fmt(r.age_hours, 1) }));
    }));
  }
}

export function renderAdvice(d) {
  const a = d.advice || { status: d.p1.status, basis: "now" };
  const card = $("advice");
  card.className = `advice is-${a.status}`;
  $("advice-basis").textContent = t(`advice.basis.${a.basis}`, { status: t(`status.${a.status}`) });
  const items = t(`advice.${a.status}`);
  $("advice-list").replaceChildren(...(Array.isArray(items) ? items : []).map((s) => h("li", null, s)));
}

export function renderTable(d) {
  const ol = $("forecast");
  ol.replaceChildren();
  if (!d.forecast.length) {
    ol.append(h("li", null, t("fc.none")));
    return;
  }
  d.forecast.forEach((f) => {
    const st = f.status;
    const li = h("li", `is-${st}`);
    const when = h("span", "when", t("fc.row_when", { h: f.h }) + " ");
    when.append(h("span", "small", t("fc.row_time", { time: hhmm(parseT(f.t)) })));
    li.append(when, h("span", "val", fmt(f.value_m)),
      h("span", "range", `${fmt(f.lo_m)}–${fmt(f.hi_m)} ม.${st !== "normal" ? ` ${t(`status.${st}`)}` : ""}`));
    ol.append(li);
  });
}
