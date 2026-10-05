// หน้าสถานะระบบ: อ่าน /api/health แล้วแสดงปัญหาที่ควรดู การดึงข้อมูล 429 backfill การเทรน และ log พยากรณ์
import { loadI18n, t } from "./i18n.js";
import { $, dayLabel, fmt, h, hhmm, parseT } from "./util.js";

// เวลาจาก meta เป็น "YYYY-MM-DD HH:MM:SS.ffffff" หรือ ISO
const ts = (s) => {
  if (!s) return "–";
  const d = parseT(String(s).replace(" ", "T").slice(0, 16));
  return `${dayLabel(d)} ${hhmm(d)} น.`;
};

function kv(dl, pairs) {
  dl.replaceChildren(...pairs.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
}

function issueText(i) {
  if (i.code === "station_stale") {
    return t("adm.issue.station_stale", { station: i.station, age: i.age_hours == null ? t("adm.issue.station_none") : t("adm.issue.station_age", { h: fmt(i.age_hours, 1) }) });
  }
  return t(`adm.issue.${i.code}`, { error: i.error || "", kind: i.kind || "", count: i.count });
}

function render(d) {
  const now = parseT(d.now);
  $("adm-updated").textContent = t("adm.updated", { time: `${dayLabel(now)} ${hhmm(now)}`, mode: t(d.mode === "live" ? "adm.mode_live" : "adm.mode_demo") });

  const iss = $("adm-issues");
  iss.className = d.issues.length ? "has-issues" : "no-issues";
  iss.replaceChildren(...(d.issues.length ? d.issues.map((i) => h("li", null, issueText(i))) : [h("li", null, t("adm.issues_none"))]));

  const f = d.last_fetch;
  $("poll-last").textContent = f ? ts(f.at) : "–";
  $("poll-result").textContent = f ? `${t(`adm.kind.${f.kind || (f.ok ? "ok" : "error")}`)}${f.error ? ` · ${f.error}` : ""}${f.rows != null ? ` · ${f.rows}` : ""}` : "–";
  const wait = d.poll.wait_minutes;
  $("poll-wait").textContent = wait > d.config.poll_minutes ? t("adm.poll_backoff", { n: wait }) : t("adm.poll_wait", { n: wait });
  const c = d.poll.counts_24h;
  $("poll-counts").textContent = t("adm.poll_counts", { ok: c.ok, empty: c.empty, r429: c["429"], error: c.error });
  const r = d.http_429;
  $("r429").textContent = r && r.count ? t("adm.r429_total", { count: r.count, at: ts(r.last_at), where: r.last_where || "" }) : t("adm.r429_none");

  // แถบผลการดึงรอบล่าสุด: ใช้สีน้ำ/หมึก/ตะกอน ไม่ใช้แดง-เหลือง (สงวนไว้ให้สถานะระดับน้ำ)
  const recent = d.poll.recent || [];
  $("strip-label").textContent = t("adm.poll_strip", { n: recent.length });
  const strip = $("poll-strip");
  strip.setAttribute("aria-label", t("adm.poll_counts", { ok: c.ok, empty: c.empty, r429: c["429"], error: c.error }));
  strip.replaceChildren(...recent.map((p) => {
    const s = h("span", `strip-${p.kind || (p.ok ? "ok" : "error")}`);
    s.title = `${ts(p.at)} ${t(`adm.kind.${p.kind || (p.ok ? "ok" : "error")}`)}`;
    return s;
  }));

  const m = d.model_info;
  $("train-at").textContent = m ? `${ts(m.trained_at)} · ${t("adm.train_every", { n: d.config.retrain_hours })}` : "–";
  $("train-hours").textContent = m ? t("adm.train_hours_v", { n: m.train_hours.toLocaleString("th-TH") }) : "–";
  $("train-range").textContent = m ? `${ts(m.train_range[0])} – ${ts(m.train_range[1])}` : "–";
  $("train-error").textContent = d.last_train_error ? `${ts(d.last_train_error.at)} · ${d.last_train_error.error}` : "–";
  $("cv-body").replaceChildren(...(m ? m.cv : []).map((x) => {
    const tr = h("tr");
    const th = h("th", null, t("acc.row_h", { h: x.h }));
    th.scope = "row";
    tr.append(th, ...[x.rmse_cm_ensemble, x.rmse_cm_ridge, x.rmse_cm_gbm, x.rmse_cm_persistence]
      .map((v, i) => h("td", i === 0 ? "is-main" : null, v == null ? "–" : fmt(v, 1))));
    return tr;
  }));

  const bf = d.backfill;
  kv($("bf"), bf ? [[t("adm.bf_at"), ts(bf.at)], ...Object.entries(bf.result).map(([k, v]) =>
    [k, typeof v === "number" ? t("adm.bf_rows", { n: v.toLocaleString("th-TH") }) : String(v)])] : [[t("adm.bf_at"), t("adm.bf_none")]]);

  const lg = d.forecast_log;
  $("log-counts").textContent = t("adm.log_counts", { issued: lg.issued, scored: lg.scored_pairs, pending: lg.pending, last: ts(lg.last_issued_for) });

  $("st-body").replaceChildren(...Object.values(d.stations).map((s) => {
    const tr = h("tr");
    const th = h("th", null, s.code);
    th.scope = "row";
    tr.append(th, h("td", null, ts(s.last_t)), h("td", "num", s.age_hours == null ? "–" : fmt(s.age_hours, 1)),
      h("td", "num", s.hours_24h == null ? "–" : String(s.hours_24h)), h("td", "num", s.hours_total == null ? "–" : s.hours_total.toLocaleString("th-TH")));
    return tr;
  }));
}

async function load() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
    render(d);
  } catch (e) {
    $("adm-updated").textContent = t("adm.err", { msg: e.message });
  }
}

await loadI18n(new URLSearchParams(location.search).get("lang") || "th");
load();
setInterval(load, 60000);
