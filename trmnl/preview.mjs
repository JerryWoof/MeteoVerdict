// Renders full.liquid the way TRMNL does, with live data, into an 800x480 HTML page.
//   npm i liquidjs@10 && node preview.mjs full.liquid preview.html [okres code] [test]
// "test" cycles through every weather symbol, adds rain and drops today's whole-day row,
// to check the fallbacks.
import { Liquid } from "liquidjs";
import fs from "node:fs";

const [, , tpl, out, code = "CZ0100", mode] = process.argv;
const data = await (await fetch(`https://jerrywoof.github.io/MeteoVerdict/api/v1/okresy/${code}.json`)).json();
if (mode === "test") {
  const syms = ["clear", "partly", "cloudy", "showers", "rain", "sleet", "snow", "clear"];
  const parts = data.forecast.parts;
  data.forecast.parts = parts.filter((p) => !(p.day === parts[0].day && p.part === "day"));
  data.forecast.parts.forEach((p, i) => { p.symbol = syms[i % syms.length]; });
  data.forecast.hourly.precipitation = data.forecast.hourly.precipitation.map((_, i) => (i % 7 < 3 ? (i % 7) + 0.5 : 0));
}
const engine = new Liquid({ timezoneOffset: 0 });
const html = await engine.parseAndRender(fs.readFileSync(tpl, "utf8"), { ...data, trmnl: { user: { utc_offset: 7200 } } });
fs.writeFileSync(out, `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://usetrmnl.com/css/latest/plugins.css">
<script src="https://usetrmnl.com/js/latest/plugins.js"></script>
<style>body{margin:0;background:#888}.screen{width:800px;height:480px;background:#fff;overflow:hidden;filter:grayscale(1) contrast(4)}</style>
</head><body class="environment trmnl"><div class="screen">${html}</div></body></html>`);
