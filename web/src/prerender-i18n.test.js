import assert from "node:assert/strict";
import test from "node:test";
import { prerenderI18n } from "../scripts/prerender-i18n.mjs";

const PAGE = `<body><header><nav class="site-nav"><a href="./" data-i18n="page.map">Map</a>
<a href="forecast.html" data-i18n="page.tv" aria-current="page">Forecast</a></nav>
<button type="button" id="language">Česky</button></header></body>`;

test("menu and language button are Czech in the HTML, the active item follows the file", () => {
  const out = prerenderI18n(PAGE, "radar.html");
  assert.match(out, /data-i18n="page.map">Mapa</);
  assert.match(out, /data-i18n="page.tv">Předpověď</);
  assert.match(out, /id="language" data-i18n="language.switch">English</);
  assert.ok(!out.includes("aria-current"));
  assert.match(prerenderI18n(PAGE, "forecast.html"), /href="forecast.html"[^>]*aria-current="page"/);
  assert.match(prerenderI18n(PAGE.replace("forecast.html", "compare.html"), "compare-models.html"), /href="compare.html"[^>]*aria-current="page"/);
  assert.match(prerenderI18n(PAGE, "index.html"), /href="\.\/"[^>]*aria-current="page"/);
});

test("an inline script switches to English before first paint", () => {
  const out = prerenderI18n(PAGE, "radar.html");
  assert.match(out, /<script>.*"page.tv":"Forecast".*<\/script>/s);
});
