// The footers of all pages, in one place (docs/licensing.md, rule 2: credit every source
// where its data is shown, link the licences, say that the values were processed).
// Each page has <footer data-footer="KIND" data-method="URL">; setUpLanguage() fills it.
//
// Kinds: "models" (scores, comparison, forecast, open data), "tv" (the combined
// forecast), "radar" (radar and satellite), "station" (ČHMÚ observations only).

export const CC_BY = "https://creativecommons.org/licenses/by/4.0/";
export const CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/";
export const ECCC_LICENCE = "https://eccc-msc.github.io/open-data/licence/readme_en/";
export const JMA_TERMS = "https://www.jma.go.jp/jma/en/copyright.html";
export const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
export const TERRAIN_ATTRIBUTION = "https://github.com/tilezen/joerd/blob/master/docs/attribution.md";

/** Model providers behind Open-Meteo's data that we show (models.yaml), credited by
 * name; ECCC and JMA follow with the wording their terms ask for. */
export const PROVIDERS = [
  "DWD",
  "ECMWF",
  "NOAA",
  "Météo-France",
  "GeoSphere Austria",
  "ČHMÚ",
  "KNMI",
  "DMI",
  "China Meteorological Administration (CMA)",
];

const SEP = " · ";
const link = (text, href) => ({ text, href });

function licence(href = CC_BY) {
  return ["(", link(href === CC_BY_SA ? "CC BY-SA 4.0" : "CC BY 4.0", href), ")"];
}

function modelCredits(t) {
  return [
    `${t("footer.forecasts")}: `,
    link("Open-Meteo.com", "https://open-meteo.com/"),
    " ",
    ...licence(),
    ` ${t("footer.withModels")} ${PROVIDERS.join(", ")} ${t("footer.and")} UK Met Office `,
    ...licence(CC_BY_SA),
    "; Data Source: Environment and Climate Change Canada ",
    "(",
    link(t("footer.licence"), ECCC_LICENCE),
    "); ",
    link("Source: Japan Meteorological Agency", JMA_TERMS),
    ` (${t("footer.edited")})`,
  ];
}

function observations(t, href = "https://opendata.chmi.cz/") {
  return [`${t("footer.observations")}: `, link("ČHMÚ", href), " ", ...licence()];
}

function boundaries(t) {
  return [`${t("footer.boundaries")}: ČÚZK `, ...licence()];
}

/**
 * The footer as a list of parts: strings, links {text, href} and {text, id} (a span the
 * page may update). ``method`` is the "Source and method" link, ``year`` the year of the
 * satellite data.
 */
export function footerParts(kind, t, { method, year = new Date().getUTCFullYear() } = {}) {
  const methodLink = method ? [SEP, link(t("footer.method"), method)] : [];
  if (kind === "station") {
    return [
      `${t("footer.observations")}: `,
      link("ČHMÚ", "https://opendata.chmi.cz/meteorology/climate/"),
      " (Czech Hydrometeorological Institute, ",
      link("CC BY 4.0", CC_BY),
      `; ${t("station.changes")})`,
      SEP,
      // the measured map's base map when zoomed in
      ...basemapCredits(t),
      ...(method ? [SEP, link(t("station.archive"), method)] : []),
    ];
  }
  if (kind === "radar") {
    return [
      `${t("footer.radar")}: `,
      link("ČHMÚ", "https://opendata.chmi.cz/meteorology/weather/radar/"),
      " ",
      ...licence(),
      SEP,
      `${t("footer.satellite")}: contains modified EUMETSAT Meteosat data `,
      { text: String(year), id: "sat-year" },
      " ",
      ...licence(),
      ", processed by ",
      link("ČHMÚ", "https://opendata.chmi.cz/meteorology/weather/satellite/"),
      " ",
      ...licence(),
      SEP,
      `${t("footer.boundaries")}, ${t("footer.places")}: ČÚZK `,
      ...licence(),
      SEP,
      ...basemapCredits(t),
      SEP,
      `${t("footer.radarProcessed")}; ${t("footer.ours")}: `,
      link("CC BY 4.0", CC_BY),
      ...methodLink,
    ];
  }
  // the AI forecast tab ("ai"): the forecast map's credits, with MeteoVerdict AI's own line
  const map = kind === "tv" || kind === "ai";
  const processed =
    map
      ? `${t("footer.processed")}; ${t(kind === "ai" ? "ai.footer" : "tv.combined")}. ${t("footer.ours")}: `
      : `${t("footer.processed")}. ${t("footer.scores")}: `;
  // the forecast map: the base map when zoomed in, the obce's population (test)
  const tvOnly = map
    ? [
      ...basemapCredits(t),
      SEP,
      `${t("footer.population")}: `,
      link("ČSÚ", "https://data.csu.gov.cz/datastat/data/SADA/OBY02A"),
      SEP,
    ]
    : [];
  return [
    ...observations(t),
    SEP,
    ...modelCredits(t),
    SEP,
    ...boundaries(t),
    SEP,
    ...tvOnly,
    processed,
    link("CC BY-SA 4.0", CC_BY_SA),
    ...methodLink,
  ];
}

/** The base map of the radar page and of the zoomed-in forecast map (radar-basemap.js). */
function basemapCredits(t) {
  return [
    `${t("footer.basemap")}: `,
    link("OpenFreeMap", "https://openfreemap.org/"),
    ", ",
    link("© OpenMapTiles", "https://www.openmaptiles.org/"),
    ", ",
    link("© OpenStreetMap contributors", OSM_COPYRIGHT),
    " (ODbL); ",
    `${t("footer.relief")}: `,
    link("Terrain Tiles", TERRAIN_ATTRIBUTION),
    " (EU-DEM © Copernicus, SRTM/GMTED2010 USGS, DGM Österreich, ETOPO1 NOAA)",
  ];
}

/** Plain text of the parts (for tests and checks). */
export function footerText(parts) {
  return parts.map((part) => (typeof part === "string" ? part : part.text)).join("");
}

/** Fill a <footer data-footer="kind" data-method="url"> in the page's language. */
export function renderFooter(footer, t) {
  const parts = footerParts(footer.dataset.footer, t, { method: footer.dataset.method });
  footer.replaceChildren(
    siteLinks(t),
    ...parts.map((part) => {
      if (typeof part === "string") return document.createTextNode(part);
      const element = document.createElement(part.href ? "a" : "span");
      element.textContent = part.text;
      if (part.href) element.href = part.href;
      if (part.id) element.id = part.id;
      return element;
    }),
  );
}

/** The pages about the project, on every page: About, Methodology, Collaboration, Contact. */
export const SITE_LINKS = [
  ["site.about", "about.html"],
  ["site.method", "methodology.html"],
  ["site.report", "report.html"],
  ["site.business", "collaboration.html"],
  ["site.contact", "about.html#contact"],
];

function siteLinks(t) {
  const nav = document.createElement("nav");
  nav.className = "site-links";
  nav.setAttribute("aria-label", t("site.about"));
  SITE_LINKS.forEach(([key, href], k) => {
    if (k) nav.append(" · ");
    const a = document.createElement("a");
    a.href = href;
    a.textContent = t(key);
    nav.append(a);
  });
  return nav;
}
