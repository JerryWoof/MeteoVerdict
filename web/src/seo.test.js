import assert from "node:assert/strict";
import test from "node:test";
import { PAGES, injectSeo } from "../scripts/seo.mjs";

const PAGE = `<html lang="cs"><head><title data-i18n-page="page.radarTitle">MeteoVerdict: weather radar</title>
<meta name="description" content="English text" /></head><body></body></html>`;

test("Czech title and description, canonical and social tags are in the HTML", () => {
  const out = injectSeo(PAGE, "radar.html");
  assert.match(out, /<title [^>]*>MeteoVerdict: Meteoradar<\/title>/);
  assert.match(out, /name="description" content="Meteoradar ČHMÚ/);
  assert.match(out, /<link rel="canonical" href="https:\/\/meteoverdict\.cz\/radar\.html" \/>/);
  assert.match(out, /og:image" content="https:\/\/meteoverdict\.cz\/og-image\.png"/);
  assert.match(out, /twitter:card" content="summary_large_image"/);
  assert.match(out, /<script>.*Weather radar|<script>.*ČHMÚ weather radar/s);
});

test("the home page canonical is the bare domain; unknown files and fragments are untouched", () => {
  assert.match(injectSeo(PAGE, "index.html"), /rel="canonical" href="https:\/\/meteoverdict\.cz\/" \/>/);
  assert.equal(injectSeo(PAGE, "tv.html"), PAGE);
  assert.equal(injectSeo("<body></body>", "radar.html"), "<body></body>");
});

test("every page entry has both descriptions", () => {
  for (const [file, [path, cs, en]] of Object.entries(PAGES)) {
    assert.ok(file.endsWith(".html") && cs && en, file);
    assert.ok(path === "" || path === file, file);
  }
});

import { injectInfoText } from "../scripts/seo.mjs";

test("a text page carries its Czech text in the HTML, the About page also FAQPage data", () => {
  const page = `<head></head><main id="info" data-page="about"><h2 id="info-title" class="page-title">O projektu</h2></main>`;
  const out = injectInfoText(page);
  assert.match(out, /<div data-prerender>[\s\S]*MeteoVerdict je český web[\s\S]*<h3>Který model/);
  const ld = JSON.parse(out.match(/ld\+json">(.*?)<\/script>/)[1]);
  assert.equal(ld["@type"], "FAQPage");
  assert.ok(ld.mainEntity.length >= 5 && ld.mainEntity.every((q) => q.name && q.acceptedAnswer.text && !q.acceptedAnswer.text.includes("<")));
  assert.ok(!injectInfoText(page.replace("about", "methodology")).includes("FAQPage"));
  assert.equal(injectInfoText("<main data-page=\"nope\"></main>"), "<main data-page=\"nope\"></main>");
});

test("the cookieless analytics beacon is on the known pages only", () => {
  assert.match(injectSeo(PAGE, "radar.html"), /static\.cloudflareinsights\.com\/beacon\.min\.js/);
  assert.ok(!injectSeo(PAGE, "tv.html").includes("cloudflareinsights"));
});
