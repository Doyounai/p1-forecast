// หน้าข้อมูลสำหรับนักวิจัย: ตารางสถานีจาก /api/stations และลิงก์ดาวน์โหลดตามช่วงวันที่ที่เลือก
import { loadI18n, t } from "./i18n.js";
import { $, fmt, h } from "./util.js";

function updateLinks() {
  const q = new URLSearchParams();
  if ($("dl-start").value) q.set("start", $("dl-start").value);
  if ($("dl-end").value) q.set("end", $("dl-end").value);
  const qs = q.toString() ? `?${q}` : "";
  $("dl-csv").href = `/api/data/hourly.csv${qs}`;
  $("dl-json").href = `/api/data/hourly${qs}`;
  $("api-example").textContent = `curl "${location.origin}/api/data/hourly.csv${qs || "?start=2024-10-01&end=2024-10-07"}" -o p1.csv`;
}

async function stations() {
  const r = await fetch("/api/stations");
  const list = await r.json();
  $("st-body").replaceChildren(...list.map((s) => {
    const tr = h("tr");
    const th = h("th", null, s.key);
    th.scope = "row";
    const travel = s.travel_hours ? (s.travel_hours[0] === s.travel_hours[1] ? `${s.travel_hours[0]}` : s.travel_hours.join("–")) : t("data.st_travel_none");
    const tdTravel = h("td", null, travel);
    if (s.travel_source) tdTravel.title = s.travel_source;
    tr.append(th, h("td", null, s.code), h("td", "num", String(s.thaiwater_id)), h("td", "left", `${s.river} ${s.name}`),
      h("td", "num", fmt(s.bank_msl)), h("td", "num", s.gauge_zero_msl != null ? fmt(s.gauge_zero_msl) : t("data.st_zero_none")), tdTravel);
    return tr;
  }));
}

await loadI18n(new URLSearchParams(location.search).get("lang") || "th");
["dl-start", "dl-end"].forEach((id) => $(id).addEventListener("change", updateLinks));
$("dl-form").addEventListener("submit", (ev) => ev.preventDefault());
updateLinks();
stations();
