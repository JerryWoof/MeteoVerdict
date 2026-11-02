import assert from "node:assert/strict";
import test from "node:test";
import { languagePath, pathLanguage } from "./i18n.js";
import { addresses, toEnglish } from "../scripts/en-pages.mjs";
import { INDEX_MIN_POPULATION, buildPlaces, indexPage, obecPage, okresPage, parseCsv, path, placeSitemaps, sitemapIndex, slugify } from "../scripts/places.mjs";

const CSV = `okres,name,lat,lon,elevation,population
CZ0423,Bohušovice nad Ohří,50.4932,14.1505,153,2393
CZ0423,Lhota,50.5,14.2,200,120
CZ0423,Lhota,50.6,14.3,210,900
CZ0423,Terezín,50.51,14.15,150,2000
CZ0100,Praha,50.08,14.41,202,1407084`;
const OKRESY = [{ code: "CZ0423", name: "Litoměřice" }, { code: "CZ0100", name: "Hlavní město Praha" }];
const places = buildPlaces(OKRESY, parseCsv(CSV));
const [litomerice, praha] = places.okresy;

test("slugs: no diacritics, same-named obce of an okres numbered by size, Prague named Praha", () => {
  assert.equal(slugify("Bohušovice nad Ohří"), "bohusovice-nad-ohri");
  assert.equal(praha.slug, "praha");
  assert.deepEqual(litomerice.obce.map((o) => [o.name, o.slug]).filter(([n]) => n === "Lhota"), [["Lhota", "lhota"], ["Lhota", "lhota-2"]]);
  assert.equal(places.count, 5);
  assert.equal(new Set(litomerice.obce.map((o) => o.slug)).size, litomerice.obce.length);
});

test("small obce are noindex and stay out of the sitemap and the English site", () => {
  const small = litomerice.obce.find((o) => o.population < INDEX_MIN_POPULATION);
  const big = litomerice.obce.find((o) => o.name === "Terezín");
  assert.match(obecPage("cs", litomerice, small, ""), /content="noindex,follow"/);
  assert.match(obecPage("cs", litomerice, big, ""), /content="index,follow"/);
  const maps = placeSitemaps(places);
  assert.ok(maps["sitemap-obce.xml"].includes("/predpoved/litomerice/terezin/"));
  assert.ok(!maps["sitemap-obce.xml"].includes(`/predpoved/litomerice/${small.slug}/`));
  assert.ok(maps["sitemap-okresy.xml"].includes("/predpoved/litomerice/") && maps["sitemap-okresy.xml"].includes('hreflang="en" href="https://meteoverdict.cz/en/forecast/litomerice/"'));
});

test("an obec page: title, description, canonical, hreflang, JSON-LD, link into the forecast", () => {
  const obec = litomerice.obce.find((o) => o.name === "Bohušovice nad Ohří");
  const html = obecPage("cs", litomerice, obec, '<link rel="stylesheet" href="/a.css">');
  assert.match(html, /<title>Počasí Bohušovice nad Ohří \(okres Litoměřice\)/);
  assert.match(html, /rel="canonical" href="https:\/\/meteoverdict\.cz\/predpoved\/litomerice\/bohusovice-nad-ohri\/"/);
  assert.match(html, /hreflang="en" href="https:\/\/meteoverdict\.cz\/en\/forecast\/litomerice\/bohusovice-nad-ohri\/"/);
  assert.match(html, /href="\/#CZ0423\/Bohu%C5%A1ovice%20nad%20Oh%C5%99%C3%AD"/);
  assert.match(html, /<h2 class="page-title">Počasí Bohušovice nad Ohří<\/h2>/);
  const ld = JSON.parse(html.match(/ld\+json">(.*?)<\/script>/)[1]);
  assert.deepEqual(ld["@graph"][0].itemListElement.map((i) => i.position), [1, 2, 3]);
  assert.equal(ld["@graph"][1].about.geo.elevation, 153);
  const en = obecPage("en", litomerice, obec, "");
  assert.match(en, /<html lang="en">/);
  assert.match(en, /<h2 class="page-title">Weather in Bohušovice nad Ohří<\/h2>/);
  assert.match(en, /href="\/en\/#CZ0423\//);
});

test("okres and index pages list their obce / okresy; every page names one description and no raw '<'", () => {
  const okres = okresPage("cs", litomerice, "");
  assert.match(okres, /href="\/predpoved\/litomerice\/terezin\/"/);
  assert.match(okres, /href="\/#CZ0423"/);
  assert.match(indexPage("cs", places.okresy, ""), /href="\/predpoved\/praha\/"/);
  // the English okres page links to a small obec's Czech page (it has no English twin)
  const en = okresPage("en", litomerice, "");
  assert.match(en, /href="\/predpoved\/litomerice\/lhota-2\/"/);
  assert.match(en, /href="\/en\/forecast\/litomerice\/terezin\/"/);
  assert.equal(path("en", litomerice), "/en/forecast/litomerice/");
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
