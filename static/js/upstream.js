// สถานะสถานีต้นน้ำ (เฟส 2 จะเปลี่ยนเป็นผังแม่น้ำ P.20 → P.1)
import { t } from "./i18n.js";
import { $, fmt, h } from "./util.js";

function travelText(tr) {
  if (!tr || tr.hours_min == null) return t("up.travel_none");
  return tr.hours_min === tr.hours_max ? t("up.travel_one", { a: tr.hours_min }) : t("up.travel_range", { a: tr.hours_min, b: tr.hours_max });
}

export function renderUpstream(d) {
  const box = $("upstream");
  box.replaceChildren(...d.upstream.map((u) => {
    const div = h("div", "up-item");
    const over = u.vs_bank_m != null && u.vs_bank_m >= 0;
    const bank = u.vs_bank_m == null ? t("up.no_data") : over ? t("up.over", { d: fmt(u.vs_bank_m) }) : t("up.under", { d: fmt(-u.vs_bank_m) });
    const ch = u.change_3h_m == null ? "" : Math.abs(u.change_3h_m) < 0.02 ? t("up.flat")
      : t(u.change_3h_m > 0 ? "up.rise" : "up.fall", { d: fmt(Math.abs(u.change_3h_m)) });
    const h3 = h("h3", null, `${u.river} ${u.name}`);
    h3.append(h("span", "code", u.code));
    div.append(h3, h("p", `bank${over ? " is-over" : ""}`, bank), h("p", null, ch), h("p", "small", travelText(u.travel)));
    return div;
  }));
}
