import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

import { CREDITS } from "./credits-text.js";
import { SITE_LINKS } from "./footer.js";
import { LANGUAGES, translator } from "./i18n.js";

test("the footer links Půdoměr and the credits page in every language", () => {
  assert.ok(SITE_LINKS.some(([key, href]) => key === "site.pudomer" && href === "https://pudomer.cz/"));
  assert.ok(SITE_LINKS.some(([key, href]) => key === "site.credits" && href === "zdroje.html"));
  for (const language of LANGUAGES) {
    for (const key of ["site.pudomer", "site.credits", "footer.data"]) {
      assert.notEqual(translator(language)(key), key, `${key} ${language}`);
    }
  }
});

test("every page has a slim footer the shared helper fills, with the link to the credits", () => {
  const pages = readdirSync(new URL("..", import.meta.url)).filter((name) => name.endsWith(".html"));
  assert.ok(pages.length >= 7);
  for (const page of pages) {
    const html = readFileSync(new URL(`../${page}`, import.meta.url), "utf8");
    assert.match(html, /<footer data-footer>/, page);
    assert.match(html, /<footer[^>]*>[\s\S]*href="zdroje.html"/, page);
  }
});

// docs/licensing.md, rule 2: credit every source and link the licences, now on one page
for (const language of LANGUAGES) {
  test(`the credits page names every source and links the licences (${language})`, () => {
    const { blocks } = CREDITS[language];
    const text = JSON.stringify(blocks);
    for (const name of ["ČHMÚ", "Open-Meteo.com", "DWD", "ECMWF", "NOAA", "Météo-France", "GeoSphere Austria", "KNMI", "DMI", "CMA", "UK Met Office", "ČÚZK", "ČSÚ", "EUMETSAT", "OpenFreeMap", "OpenMapTiles", "OpenStreetMap contributors", "ODbL", "Terrain Tiles", "EU-DEM"]) {
      assert.ok(text.includes(name), name);
    }
    assert.ok(text.includes("Data Source: Environment and Climate Change Canada"));
    assert.ok(text.includes("Source: Japan Meteorological Agency"));
    for (const href of ["licenses/by/4.0/", "licenses/by-sa/4.0/", "eccc-msc.github.io/open-data/licence", "jma.go.jp/jma/en/copyright", "methodology.html"]) {
      assert.ok(text.includes(href), href);
    }
  });
}
