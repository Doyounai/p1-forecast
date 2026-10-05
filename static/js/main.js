import { drawChart } from "./chart.js";
import { setupDemo, isDemo } from "./demo.js";
import { setFresh } from "./fresh.js";
import { drawGauge } from "./gauge.js";
import { renderAdvice, renderNow, renderOutlook, renderTable } from "./hero.js";
import { loadI18n, t } from "./i18n.js";
import { getMyLevel, setupMyLevel } from "./mylevel.js";
import { renderUpstream } from "./upstream.js";
import { $, dayLabel, hhmm, parseT } from "./util.js";

let last = null, at = new URLSearchParams(location.search).get("at"), my = getMyLevel(), retry = null;

function renderModel(d) {
  const f6 = d.forecast.find((f) => f.h === 6);
  const tr = parseT(d.model.trained_at);
  $("model-info").textContent = t("about.model", { date: dayLabel(tr), time: hhmm(tr), hours: d.model.train_hours.toLocaleString("th-TH") })
    + (f6 && f6.rmse_cm ? t("about.model_rmse", { rmse: f6.rmse_cm }) : "");
}

function render(d) {
  const same = last != null && last.p1.t === d.p1.t && last.now === d.now;
  last = d;
  setFresh(d, same);
  renderNow(d);
  renderOutlook(d);
  renderAdvice(d);
  renderTable(d);
  drawGauge(d, my);
  drawChart(d, my);
  $("legend-my").hidden = my == null;
  renderUpstream(d);
  renderModel(d);
}

async function load(newAt) {
  if (newAt !== undefined) at = newAt;
  const q = new URLSearchParams();
  if (at) q.set("at", at);
  if (my != null) q.set("my", my.toFixed(2));
  clearTimeout(retry);
  try {
    const qs = q.toString(); // URLSearchParams.size ยังไม่มีในเบราว์เซอร์มือถือรุ่นเก่า
    const r = await fetch(`/api/forecast${qs ? `?${qs}` : ""}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
    render(d);
    if (d.mode === "demo" && !isDemo()) setupDemo(d, load);
  } catch (e) {
    $("level-note").textContent = t("err.load", { msg: e.message });
    retry = setTimeout(() => load(), 30000);
  }
}

await loadI18n(new URLSearchParams(location.search).get("lang") || "th");
my = setupMyLevel((v) => { my = v; load(); });
window.addEventListener("resize", () => { if (last) drawChart(last, my); });
load(); // โหมดสาธิต: ?at=2024-10-05 02:00
setInterval(() => { if (!isDemo()) load(); }, 5 * 60 * 1000);
