// After `vite build`: the static pages of the okresy and obce (places.mjs), the English copies of
// the site's pages (en-pages.mjs), the sitemaps (an index and one file per kind) and favicon.ico
// is a plain file in public/. Everything is written into dist/; nothing here reads private data.
import { mkdirSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PAGES } from "./seo.mjs";
import { addAlternates, addresses, enFile, toEnglish } from "./en-pages.mjs";
import { buildPlaces, indexPage, obecPage, okresPage, parseCsv, path, placeSitemaps, sitemapIndex, urlset } from "./places.mjs";

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

// 2. the place pages
const okresy = JSON.parse(readFileSync(join(data, "okresy.geojson"), "utf8")).features.map((f) => f.properties);
const places = buildPlaces(okresy, parseCsv(readFileSync(join(data, "obce-elevations.csv"), "utf8")));
const dir = (lang, okres, obec) => path(lang, okres, obec).slice(1) + "index.html";
let pages = 0;
for (const lang of ["cs", "en"]) {
  write(dir(lang), indexPage(lang, places.okresy, assets));
  pages++;
  for (const okres of places.okresy) {
    write(dir(lang, okres), okresPage(lang, okres, assets));
    pages++;
    for (const obec of okres.obce) {
      if (lang === "en" && !obec.indexable) continue;
      write(dir(lang, okres, obec), obecPage(lang, okres, obec, assets));
      pages++;
    }
  }
}

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
const maps = { "sitemap-pages.xml": urlset(statics), ...placeSitemaps(places) };
for (const [name, xml] of Object.entries(maps)) write(name, xml);
write("sitemap.xml", sitemapIndex(Object.keys(maps)));

const indexable = places.okresy.reduce((n, k) => n + k.obce.filter((o) => o.indexable).length, 0);
console.log(`places: ${places.count} obce in ${places.okresy.length} okresy, ${pages} place pages, ${indexable} obce in the sitemap, ${readdirSync(join(dist, "en")).length} English site files`);
