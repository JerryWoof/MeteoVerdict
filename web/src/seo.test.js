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
