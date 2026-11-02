import assert from "node:assert/strict";
import test from "node:test";
import { languagePath, pathLanguage } from "./i18n.js";
import { addresses, toEnglish } from "../scripts/en-pages.mjs";
import { buildPlaces, forecastDays, indexPage, okresPage, parseCsv, path, placeSitemaps, sitemapIndex, slugify } from "../scripts/places.mjs";

const CSV = `okres,name,lat,lon,elevation,population
CZ0423,Bohušovice nad Ohří,50.4932,14.1505,153,2393
CZ0423,Terezín,50.51,14.15,150,2000
CZ0100,Praha,50.08,14.41,202,1407084`;
const OKRESY = [{ code: "CZ0423", name: "Litoměřice" }, { code: "CZ0100", name: "Hlavní město Praha" }];
const places = buildPlaces(OKRESY, parseCsv(CSV));
const [litomerice, praha] = places;
const ROWS = { "2026-11-03|day": { tmax: 9.4, precipitation: 1.2, wind: 3 }, "2026-11-03|night": { tmin: 2.1 }, "2026-11-04|day": { tmax: 7, precipitation: 0, wind: 4.5 }, "2026-11-04|night": { tmin: null }, "2026-11-05|night": { tmin: 1 } };
const days = forecastDays(["2026-11-03", "2026-11-04", "2026-11-05"], (d, p) => ROWS[`${d}|${p}`]);

test("okres slugs have no diacritics; Prague is Praha; obce are only counted", () => {
  assert.equal(slugify("Bohušovice nad Ohří"), "bohusovice-nad-ohri");
  assert.equal(praha.slug, "praha");
  assert.deepEqual([litomerice.obce, litomerice.population], [2, 4393]);
});

test("forecastDays keeps the days that have a day row", () => {
  assert.equal(days.length, 2);
  assert.deepEqual(days[1], { day: "2026-11-04", tmax: 7, tmin: null, rain: 0, wind: 4.5 });
});

test("an okres page has the numbers of the days, canonical, hreflang, JSON-LD and the link into the forecast", () => {
  const html = okresPage("cs", litomerice, days, "3. 11. 2026", '<link rel="stylesheet" href="/a.css">');
  assert.match(html, /<title>Počasí v okrese Litoměřice/);
  assert.match(html, /rel="canonical" href="https:\/\/meteoverdict\.cz\/predpoved\/litomerice\/"/);
  assert.match(html, /hreflang="en" href="https:\/\/meteoverdict\.cz\/en\/forecast\/litomerice\/"/);
  assert.match(html, /<td>9,4<\/td><td>2,1<\/td><td>1,2<\/td><td>3,0<\/td>/);
  assert.match(html, /<td>–<\/td>/);
  assert.match(html, /href="\/#CZ0423"/);
  assert.match(html, /name="description" content="Předpověď počasí v okrese Litoměřice na další dny: /);
  const ld = JSON.parse(html.match(/ld\+json">(.*?)<\/script>/)[1]);
  assert.deepEqual(ld["@graph"][0].itemListElement.map((i) => i.position), [1, 2]);
  const en = okresPage("en", litomerice, days, "2026-11-03", "");
  assert.match(en, /<html lang="en">/);
  assert.match(en, /<td>9\.4<\/td>/);
  assert.match(en, /href="\/en\/#CZ0423"/);
  assert.equal(path("en", litomerice), "/en/forecast/litomerice/");
});

test("index page and sitemap list the okresy that have a page", () => {
  assert.match(indexPage("cs", places, ""), /href="\/predpoved\/praha\/"/);
  const map = placeSitemaps([litomerice])["sitemap-okresy.xml"];
  assert.ok(map.includes("/predpoved/litomerice/") && map.includes("/predpoved/</loc>"));
  assert.ok(map.includes('hreflang="en" href="https://meteoverdict.cz/en/forecast/litomerice/"'));
});

test("sitemap index names the files; the English copy of a page has canonical, hreflang, base and English text", () => {
  assert.match(sitemapIndex(["a.xml"]), /<loc>https:\/\/meteoverdict\.cz\/a\.xml<\/loc>/);
  const page = `<html lang="cs"><head><title data-i18n-page="page.radarTitle">MeteoVerdict: Meteoradar</title>
<meta name="description" content="cs" /><link rel="canonical" href="https://meteoverdict.cz/radar.html" /><meta property="og:locale" content="cs_CZ" /></head>
<body><a href="radar.html" data-i18n="page.radar">Radar</a><a href="./">x</a><a href="api/v1/index.json">api</a></body></html>`;
  const en = toEnglish(page, "radar.html");
  assert.match(en, /<html lang="en">/);
  assert.match(en, /<base href="\/" \/>/);
  assert.match(en, /rel="canonical" href="https:\/\/meteoverdict\.cz\/en\/radar\.html"/);
  assert.match(en, /hreflang="cs" href="https:\/\/meteoverdict\.cz\/radar\.html"/);
  assert.match(en, /<title [^>]*>MeteoVerdict: Weather radar<\/title>/);
  assert.match(en, /href="\/en\/radar\.html"/);
  assert.match(en, /href="\/en\/"/);
  assert.match(en, /href="api\/v1\/index\.json"/);
  assert.equal(addresses("index.html").en, "https://meteoverdict.cz/en/");
  assert.equal(toEnglish(page, "unknown.html"), null);
});

test("the language follows the /en/ path, and the switch maps between the twins", () => {
  assert.equal(pathLanguage("/en/radar.html"), "en");
  assert.equal(pathLanguage("/en/"), "en");
  assert.equal(pathLanguage("/enigma.html"), null);
  assert.equal(pathLanguage("/radar.html"), null);
  assert.equal(languagePath("/radar.html", "en"), "/en/radar.html");
  assert.equal(languagePath("/", "en"), "/en/");
  assert.equal(languagePath("/en/radar.html", "cs"), "/radar.html");
  assert.equal(languagePath("/en/", "cs"), "/");
  assert.equal(languagePath("/en/radar.html", "en"), "/en/radar.html");
});

test("the pages have the same footer links as the app pages, under /en/ in English", () => {
  const cs = okresPage("cs", litomerice, days, "3. 11. 2026", "");
  assert.match(cs, /<footer><nav class="site-links"[^>]*><a href="\/about\.html">O projektu<\/a>/);
  assert.match(cs, /href="\/collaboration\.html">Kontakt<\/a>/);
  assert.match(cs, /href="https:\/\/verify\.meteoverdict\.cz\/" target="_blank" rel="noopener"/);
  const en = okresPage("en", litomerice, days, "2026-11-03", "");
  assert.match(en, /href="\/en\/about\.html">About<\/a>/);
  assert.match(en, /href="\/en\/data\.html">Data<\/a>/);
});
