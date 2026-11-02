// After `vite build`: the static pages of the okresy (places.mjs), the English copies of
// the site's pages (en-pages.mjs), the sitemaps (an index and one file per kind) and favicon.ico
// is a plain file in public/. Everything is written into dist/; nothing here reads private data.
import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PAGES } from "./seo.mjs";
import { addAlternates, addresses, enFile, toEnglish } from "./en-pages.mjs";
import { parseOutlook, rowFor } from "../src/tv.js";
import { buildPlaces, forecastDays, indexPage, okresPage, parseCsv, path, placeSitemaps, sitemapIndex, urlset } from "./places.mjs";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(web, "dist");
const data = join(web, "..", "src", "meteoverdict", "data");

const write = (rel, text) => {
  const file = join(dist, rel);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, text);
};

// 1. the site's stylesheets, for the place pages
const home = readFileSync(join(dist, "index.html"), "utf8");
const assets = [...home.matchAll(/<link rel="stylesheet"[^>]*>/g)]
  .map((m) => m[0].replace('href="./', 'href="/')).join("\n    ");

// 2. the okres pages, only with the forecast of this deploy (outlook.json): real numbers or no page
const okresy = JSON.parse(readFileSync(join(data, "okresy.geojson"), "utf8")).features.map((f) => f.properties);
const places = buildPlaces(okresy, parseCsv(readFileSync(join(data, "obce-elevations.csv"), "utf8")));
const outlookFile = join(dist, "data", "scores", "outlook.json");
const outlook = existsSync(outlookFile) ? parseOutlook(JSON.parse(readFileSync(outlookFile, "utf8"))) : null;
const dir = (lang, okres) => path(lang, okres).slice(1) + "index.html";
const withPage = [];
for (const okres of places) {
  const days = outlook ? forecastDays(outlook.days, (day, part) => rowFor(outlook, okres.code, day, part)) : [];
  if (days.length < 3) continue;
  withPage.push(okres);
  const updated = outlook.generated?.slice(0, 10).split("-").reverse().map(Number).join(". ");
  for (const lang of ["cs", "en"]) write(dir(lang, okres), okresPage(lang, okres, days, lang === "cs" ? updated : outlook.generated?.slice(0, 10), assets));
}
if (withPage.length) for (const lang of ["cs", "en"]) write(dir(lang), indexPage(lang, withPage, assets));
const pages = withPage.length * 2 + (withPage.length ? 2 : 0);

// 3. the English copies of the site's pages; the Czech ones learn their twin
const statics = [];
for (const file of Object.keys(PAGES)) {
  const html = readFileSync(join(dist, file), "utf8");
  write(file, addAlternates(html, file));
  write(enFile(file), toEnglish(html, file));
  if (file !== "forecast-detail.html") statics.push({ loc: addresses(file).cs, alternates: addresses(file) });
}

// 4. sitemaps: index → static pages, okresy, obce (the 50 000-URL limit is far away; the split
// makes Search Console report each kind separately)
const maps = { "sitemap-pages.xml": urlset(statics), ...(withPage.length ? placeSitemaps(withPage) : {}) };
for (const [name, xml] of Object.entries(maps)) write(name, xml);
write("sitemap.xml", sitemapIndex(Object.keys(maps)));

console.log(`okres pages: ${withPage.length} of ${places.length}${outlook ? "" : " (no outlook.json: none built)"}, ${pages} files; ${Object.keys(maps).length} sitemaps; ${readdirSync(join(dist, "en")).length} English site files`);
