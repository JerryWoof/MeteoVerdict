import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

import { CC_BY, CC_BY_SA, ECCC_LICENCE, JMA_TERMS, OSM_COPYRIGHT, SITE_LINKS, TERRAIN_ATTRIBUTION, footerParts, footerText } from "./footer.js";
import { LANGUAGES, translator } from "./i18n.js";

const links = (parts) => parts.filter((p) => p.href).map((p) => p.href);

// docs/licensing.md, rule 2: credit, link the licences, say the values were processed
for (const language of LANGUAGES) {
  const t = translator(language);

  for (const kind of ["models", "tv", "ai"]) {
    test(`${kind} footer credits every provider and links the licences (${language})`, () => {
      const parts = footerParts(kind, t, { method: "https://example.org/method" });
      const text = footerText(parts);
      for (const name of ["ČHMÚ", "Open-Meteo.com", "DWD", "ECMWF", "NOAA", "Météo-France", "KNMI", "DMI", "UK Met Office", "ČÚZK"]) {
        assert.ok(text.includes(name), name);
      }
      assert.ok(text.includes("Data Source: Environment and Climate Change Canada"));
      assert.ok(text.includes(`Source: Japan Meteorological Agency (${t("footer.edited")})`));
      assert.ok(text.includes("China Meteorological Administration"));
      assert.ok(text.includes(t("footer.processed")));
      for (const href of [CC_BY, CC_BY_SA, ECCC_LICENCE, JMA_TERMS, "https://open-meteo.com/", "https://example.org/method"]) {
        assert.ok(links(parts).includes(href), href);
      }
      assert.ok(!text.includes("footer."), "untranslated key");
    });
  }

  test(`radar footer credits EUMETSAT with the year (${language})`, () => {
    const parts = footerParts("radar", t, { year: 2026 });
    const text = footerText(parts);
    assert.ok(text.includes("contains modified EUMETSAT Meteosat data 2026"));
    assert.ok(text.includes(t("footer.radarProcessed")));
    assert.ok(links(parts).includes(CC_BY));
    assert.equal(parts.find((p) => p.id === "sat-year").text, "2026");
  });

  test(`radar footer credits the base map and the municipalities (${language})`, () => {
    const parts = footerParts("radar", t, { year: 2026 });
    const text = footerText(parts);
    for (const name of ["OpenFreeMap", "© OpenMapTiles", "© OpenStreetMap contributors", "ODbL", "Terrain Tiles", "EU-DEM", "ČÚZK"]) {
      assert.ok(text.includes(name), name);
    }
    assert.ok(text.includes(t("footer.places")));
    assert.ok(links(parts).includes(OSM_COPYRIGHT));
    assert.ok(links(parts).includes(TERRAIN_ATTRIBUTION));
    assert.ok(!text.includes("footer."), "untranslated key");
  });

  test(`station footer links CC BY 4.0 and says what changed (${language})`, () => {
    const parts = footerParts("station", t);
    assert.ok(links(parts).includes(CC_BY));
    assert.ok(footerText(parts).includes(t("station.changes")));
  });
}

test("the footer links Půdoměr in every language", () => {
  assert.ok(SITE_LINKS.some(([key, href]) => key === "site.pudomer" && href === "https://pudomer.cz/"));
  for (const language of LANGUAGES) {
    assert.notEqual(translator(language)("site.pudomer"), "site.pudomer", language);
  }
});

test("every page has a footer the shared helper fills", () => {
  const pages = readdirSync(new URL("..", import.meta.url)).filter((name) => name.endsWith(".html"));
  assert.ok(pages.length >= 7);
  for (const page of pages) {
    const html = readFileSync(new URL(`../${page}`, import.meta.url), "utf8");
    assert.match(html, /<footer data-footer="(models|tv|ai|radar|station)" data-method="https:\/\//, page);
  }
});
