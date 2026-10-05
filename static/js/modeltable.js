// ตารางท้ายหน้า: พยากรณ์ 1–6 ชม. รายชั่วโมงของ M4, M6, M7 พร้อมช่วงและ RMSE ของแต่ละช่อง
import { t } from "./i18n.js";
import { $, fmt, h, hhmm, parseT } from "./util.js";

const MODELS = ["ridge", "gbm", "ensemble"];

export function renderModelTable(d) {
  const tab = d.model_table, body = $("mt-body");
  if (!tab || !tab.rows.length) {
    $("mt-intro").textContent = t("mt.none");
    body.replaceChildren();
    return;
  }
  $("mt-intro").textContent = t("mt.intro", { time: hhmm(parseT(tab.issued_for)), now: fmt(tab.now_m) });
  body.replaceChildren(...tab.rows.map((r) => {
    const tr = h("tr");
    const th = h("th", null, t("mt.row_h", { h: r.h }));
    th.scope = "row";
    th.append(h("span", "mt-time", t("fc.row_time", { time: hhmm(parseT(r.t)) })));
    tr.append(th);
    MODELS.forEach((k) => {
      const c = r.models[k];
      const td = h("td", k === "ensemble" ? "is-main" : null);
      td.append(h("span", `mt-val is-${c.status}`, fmt(c.value_m)),
        h("span", "mt-range", `${fmt(c.lo_m)}–${fmt(c.hi_m)}`),
        h("span", "mt-rmse", c.rmse_cm != null ? t("mt.rmse", { v: fmt(c.rmse_cm, 1) }) : ""));
      tr.append(td);
    });
    return tr;
  }));
}
