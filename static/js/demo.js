// แถบโหมดสาธิต: เลื่อนเวลาย้อนดูน้ำท่วมปี 2567
import { t } from "./i18n.js";
import { $, dayLabel, hhmm, parseT } from "./util.js";

let demo = null, playing = null, pending = null;
export const isDemo = () => demo != null;

export function setupDemo(d, load) {
  const [a, b] = d.demo_range.map(parseT);
  demo = { start: a, hours: Math.round((b - a) / 3600e3) };
  const s = $("demo-slider");
  s.max = demo.hours;
  s.value = Math.round((parseT(d.now) - a) / 3600e3);
  $("demo-bar").hidden = false;
  const label = () => {
    const tt = new Date(demo.start.getTime() + s.value * 3600e3);
    $("demo-time").textContent = `${dayLabel(tt)} ${hhmm(tt)} น.`;
    return `${tt.getFullYear()}-${String(tt.getMonth() + 1).padStart(2, "0")}-${String(tt.getDate()).padStart(2, "0")} ${hhmm(tt)}`;
  };
  label();
  s.addEventListener("input", () => {
    const at = label();
    clearTimeout(pending);
    pending = setTimeout(() => load(at), 120);
  });
  const btn = $("demo-play");
  btn.addEventListener("click", () => {
    if (playing) {
      clearInterval(playing); playing = null;
      btn.textContent = t("demo.play"); btn.setAttribute("aria-pressed", "false");
      return;
    }
    btn.textContent = t("demo.stop"); btn.setAttribute("aria-pressed", "true");
    playing = setInterval(() => {
      if (+s.value >= demo.hours) s.value = 13; else s.value = +s.value + 1;
      load(label());
    }, 700);
  });
}
