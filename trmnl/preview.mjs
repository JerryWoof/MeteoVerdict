// Renders full.liquid the way TRMNL does, with live data, into an 800x480 HTML page.
//   npm i liquidjs@10 && node preview.mjs full.liquid preview.html [okres] [lat] [lon] [mode]
// mode "open-meteo" (default): the open data as it is now, with the Open-Meteo second URL.
// mode "sun": the open data with sunrise, sunset and sunshine, as after the outlook change.
// mode "test": like "sun", and cycles through every weather symbol, adds rain and drops
// today's whole-day row, to check the fallbacks.
import { Liquid } from "liquidjs";
import fs from "node:fs";

const [, , tpl, out, code = "CZ0423", lat = "50.08", lon = "14.44", mode = "open-meteo"] = process.argv;
const get = async (url) => (await fetch(url)).json();
const IDX_0 = await get(`https://jerrywoof.github.io/MeteoVerdict/api/v1/okresy/${code}.json`);
let IDX_1 = await get(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&daily=sunrise,sunset,sunshine_duration&timezone=Europe%2FPrague&forecast_days=3`);
if (mode !== "open-meteo") {
  const shares = { night: 0, morning: 0.35, afternoon: 0.55, evening: 0.1, day: 1 };
  for (const p of IDX_0.forecast.parts) {
    const i = IDX_1.daily.time.indexOf(p.day);
    if (i < 0) continue;
    p.sunrise = IDX_1.daily.sunrise[i].slice(11, 16);
    p.sunset = IDX_1.daily.sunset[i].slice(11, 16);
    p.sunshine = Math.round((IDX_1.daily.sunshine_duration[i] / 3600) * shares[p.part] * 10) / 10;
  }
  IDX_1 = undefined;
}
if (mode === "test") {
  const syms = ["clear", "partly", "cloudy", "showers", "rain", "sleet", "snow", "clear"];
  const parts = IDX_0.forecast.parts;
  IDX_0.forecast.parts = parts.filter((p) => !(p.day === parts[0].day && p.part === "day"));
  IDX_0.forecast.parts.forEach((p, i) => { p.symbol = syms[i % syms.length]; });
  IDX_0.forecast.hourly.precipitation = IDX_0.forecast.hourly.precipitation.map((_, i) => (i % 7 < 3 ? (i % 7) + 0.5 : 0));
}
const engine = new Liquid({ timezoneOffset: 0 });
const html = await engine.parseAndRender(fs.readFileSync(tpl, "utf8"), { IDX_0, IDX_1, trmnl: { user: { utc_offset: 7200 } } });
fs.writeFileSync(out, `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://usetrmnl.com/css/latest/plugins.css">
<script src="https://usetrmnl.com/js/latest/plugins.js"></script>
<style>body{margin:0;background:#888}.screen{width:800px;height:480px;background:#fff;overflow:hidden;filter:grayscale(1) contrast(4)}</style>
</head><body class="environment trmnl"><div class="screen">${html}</div></body></html>`);
