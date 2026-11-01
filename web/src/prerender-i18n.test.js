import assert from "node:assert/strict";
import test from "node:test";
import { prerenderI18n } from "../scripts/prerender-i18n.mjs";

const PAGE = `<body><header><nav class="site-nav"><a href="./" data-i18n="page.tv">Forecast</a>
<a href="radar.html" data-i18n="page.radar" aria-current="page">Radar</a></nav>
<div id="language" class="langsw"><button data-lang="cs" aria-pressed="true">CS</button><button data-lang="en" aria-pressed="false">EN</button></div></header></body>`;

test("menu and language button are Czech in the HTML, the active item follows the file", () => {
  const out = prerenderI18n(PAGE, "heatmap.html");
  assert.match(out, /data-i18n="page.tv">Předpověď</);
  assert.match(out, /data-i18n="page.radar">Radar</);
  assert.match(out, /href="heatmap.html"[^>]*aria-current="page"/);
  assert.equal(out.match(/aria-current/g).length, 1);
  assert.match(prerenderI18n(PAGE, "radar.html"), /href="radar.html"[^>]*aria-current="page"/);
  assert.match(prerenderI18n(PAGE, "index.html"), /href="\.\/"[^>]*aria-current="page"/);
});

test("an inline script switches to English before first paint", () => {
  const out = prerenderI18n(PAGE, "radar.html");
  assert.match(out, /<script>.*"page.tv":"Forecast".*<\/script>/s);
  assert.match(out, /<script>.*#language \[data-lang\].*<\/script>/s);
});

test("every page gets the theme before first paint and the theme button after the language switch", () => {
  const out = prerenderI18n(`<head><meta charset="UTF-8" /></head>${PAGE}`, "radar.html");
  assert.match(out, /<meta charset="UTF-8" \/>\s*<script>try\{document\.documentElement\.dataset\.theme=.*meteoverdict\.theme.*<\/script>/);
  assert.match(out, /<div class="hdr-tools"><div id="language".*EN<\/button><\/div><button id="theme" class="iconbtn".*<\/button><\/div>/);
});
