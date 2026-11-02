// Static pages for every okres and obec: /predpoved/<okres>/ and /predpoved/<okres>/<obec>/
// (English: /en/forecast/...). Built after `vite build` (scripts/build-places.mjs) from the
// ČÚZK/ČSÚ places list in the repository, so a crawler without JavaScript reads a headline, a few
// sentences about the place, links to its neighbours and a link into the interactive forecast.
// Pure functions: the file work is in build-places.mjs.
import { fold } from "../src/places.js";

export const SITE = "https://meteoverdict.cz";
// obce under this many people get the page (reachable by links) but `noindex,follow` and no
// sitemap entry, so ~3 400 near-identical village pages cannot read as thin content; widen it
// when Search Console shows the bigger ones are indexed and wanted
export const INDEX_MIN_POPULATION = 500;
export const NEIGHBOURS = 6;

export const slugify = (name) => fold(name).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "x";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const json = (o) => JSON.stringify(o).replace(/</g, "\\u003c");

/** Rows of obce-elevations.csv: okres,name,lat,lon,elevation,population. */
export function parseCsv(text) {
  const [head, ...lines] = text.trim().split(/\r?\n/);
  const cols = head.split(",");
  return lines.map((line) => {
    const cells = line.split(",");
    return Object.fromEntries(cols.map((c, i) => [c, cells[i]]));
  });
}

/**
 * okresy: [{code, name}], rows: parseCsv() → {okresy: [{code, name, slug, obce}], count}.
 * An obec's slug is its folded name; a second obec of the same name in an okres gets -2, -3 …
 * in order of size (then position), so the slugs do not move when other places are added.
 */
export function buildPlaces(okresy, rows) {
  const byCode = new Map(okresy.map((o) => [o.code, { code: o.code, name: o.name === "Hlavní město Praha" ? "Praha" : o.name, slug: slugify(o.name === "Hlavní město Praha" ? "Praha" : o.name), obce: [] }]));
  for (const r of rows) {
    const okres = byCode.get(r.okres);
    if (!okres) continue;
    okres.obce.push({ name: r.name, lat: Number(r.lat), lon: Number(r.lon), elevation: Number(r.elevation), population: Number(r.population) || 0 });
  }
  for (const okres of byCode.values()) {
    okres.obce.sort((a, b) => a.name.localeCompare(b.name, "cs") || b.population - a.population || a.lat - b.lat || a.lon - b.lon);
    const seen = new Map();
    for (const o of okres.obce) {
      const base = slugify(o.name);
      const n = (seen.get(base) ?? 0) + 1;
      seen.set(base, n);
      o.slug = n === 1 ? base : `${base}-${n}`;
      o.indexable = o.population >= INDEX_MIN_POPULATION;
    }
  }
  const list = [...byCode.values()].filter((o) => o.obce.length).sort((a, b) => a.name.localeCompare(b.name, "cs"));
  return { okresy: list, count: list.reduce((n, o) => n + o.obce.length, 0) };
}

const near = (a, b) => (a.lat - b.lat) ** 2 + ((a.lon - b.lon) * Math.cos((a.lat * Math.PI) / 180)) ** 2;
export const nearest = (obec, okres) =>
  okres.obce.filter((o) => o !== obec).sort((a, b) => near(a, obec) - near(b, obec)).slice(0, NEIGHBOURS);

// --- addresses ---------------------------------------------------------------------------------
export const path = (lang, okres, obec) =>
  `${lang === "en" ? "/en/forecast/" : "/predpoved/"}${okres ? `${okres.slug}/` : ""}${obec ? `${obec.slug}/` : ""}`;
const url = (lang, okres, obec) => SITE + path(lang, okres, obec);
const other = (lang) => (lang === "en" ? "cs" : "en");
/** Whether the English twin exists: every okres, and the obce that are indexed. */
export const hasEnglish = (obec) => !obec || obec.indexable;
/** The interactive forecast of the place (obec.name in the hash opens its obec panel). */
export const appLink = (lang, okres, obec) =>
  `${lang === "en" ? "/en/" : "/"}#${okres.code}${obec ? `/${encodeURIComponent(obec.name)}` : ""}`;

// --- texts -------------------------------------------------------------------------------------
const fmt = (n, lang) => Number(n).toLocaleString(lang === "en" ? "en-GB" : "cs-CZ").replace(/ /g, " ");
const people = (n, lang) => (lang === "en" ? `${fmt(n, lang)} inhabitants` : `${fmt(n, lang)} obyvatel`);

const T = {
  cs: {
    home: "Předpověď", forecast: "Předpověď počasí", radar: "Radar", heatmap: "Heatmapa", compare: "Porovnání modelů",
    nav: [["/", "Předpověď"], ["/radar.html", "Radar"], ["/heatmap.html", "Heatmapa"], ["/compare-models.html", "Porovnání modelů"]],
    obecTitle: (o, k) => `Počasí ${o.name} (okres ${k.name}): předpověď | MeteoVerdict`,
    obecH1: (o) => `Počasí ${o.name}`,
    obecDescription: (o, k) => `Předpověď počasí pro obec ${o.name} v okrese ${k.name} na další dny, složená z modelů podle toho, který se v okrese osvědčil nejlépe. Měřeno proti stanicím ČHMÚ.`,
    obecLead: (o, k) => `Obec ${o.name} leží v okrese ${k.name}, v nadmořské výšce ${Math.round(o.elevation)} m, a žije v ní ${people(o.population, "cs")}.`,
    obecBody: (o, k) => `MeteoVerdict skládá předpověď pro ${o.name} z více meteorologických modelů (ALADIN, ICON, ECMWF a dalších) tak, aby každý měl váhu podle toho, jak přesně v okrese ${k.name} v poslední době předpovídal proti měření stanic ČHMÚ. Pro obec ukazuje teplotu, srážky, vítr a další veličiny na příští dny, v interaktivní předpovědi i s tím, který model v okrese právě vede.`,
    open: (o) => `Otevřít předpověď pro ${o.name}`,
    nearby: "Obce poblíž",
    okresLink: (k) => `Všechny obce okresu ${k.name}`,
    okresTitle: (k) => `Počasí v okrese ${k.name}: předpověď pro obce | MeteoVerdict`,
    okresH1: (k) => `Počasí v okrese ${k.name}`,
    okresDescription: (k, n) => `Předpověď počasí v okrese ${k.name} na další dny a odkazy na ${n} obcí okresu; předpověď je složená z modelů podle toho, který se v okrese osvědčil nejlépe.`,
    okresLead: (k, n, pop) => `Okres ${k.name} má ${n} obcí a ${people(pop, "cs")}. Předpověď pro okres i pro každou jeho obec skládáme z modelů podle toho, jak přesně se v okrese osvědčily proti měření stanic ČHMÚ.`,
    openOkres: (k) => `Otevřít předpověď pro okres ${k.name}`,
    obceOf: (k) => `Obce okresu ${k.name}`,
    allOkresy: "Všechny okresy",
    indexTitle: "Počasí podle okresů a obcí: předpověď pro celé Česko | MeteoVerdict",
    indexH1: "Počasí podle okresů a obcí",
    indexDescription: "Předpověď počasí pro 77 okresů a 6 258 obcí v Česku. Skládáme ji z modelů podle toho, který se v kterém okrese osvědčil, a měříme ji proti stanicím ČHMÚ.",
    indexLead: "Vyberte okres a v něm obec. Předpověď je složená z meteorologických modelů podle toho, jak přesně se v okrese osvědčily proti měření stanic ČHMÚ.",
    note: "Nejde o oficiální předpověď; oficiální výstrahy vydává ČHMÚ.",
    locale: "cs_CZ", ogLocale: "cs_CZ", switchLabel: "English", home2: "MeteoVerdict",
  },
  en: {
    home: "Forecast", forecast: "Weather forecast", radar: "Radar", heatmap: "Heatmap", compare: "Model comparison",
    nav: [["/en/", "Forecast"], ["/en/radar.html", "Radar"], ["/en/heatmap.html", "Heatmap"], ["/en/compare-models.html", "Model comparison"]],
    obecTitle: (o, k) => `Weather ${o.name} (${k.name} district): forecast | MeteoVerdict`,
    obecH1: (o) => `Weather in ${o.name}`,
    obecDescription: (o, k) => `Weather forecast for ${o.name} in the ${k.name} district (Czechia) for the next days, combined from the models by which did best in the district. Checked against ČHMÚ stations.`,
    obecLead: (o, k) => `${o.name} is a municipality in the ${k.name} district, ${Math.round(o.elevation)} m above sea level, with ${people(o.population, "en")}.`,
    obecBody: (o, k) => `MeteoVerdict builds the forecast for ${o.name} from several weather models (ALADIN, ICON, ECMWF and others), weighting each by how accurately it forecast in the ${k.name} district lately, measured against ČHMÚ station readings. It shows temperature, precipitation, wind and more for the next days, and in the interactive forecast also which model currently leads in the district.`,
    open: (o) => `Open the forecast for ${o.name}`,
    nearby: "Nearby municipalities",
    okresLink: (k) => `All municipalities of ${k.name} district`,
    okresTitle: (k) => `Weather in ${k.name} district: forecast for its municipalities | MeteoVerdict`,
    okresH1: (k) => `Weather in ${k.name} district`,
    okresDescription: (k, n) => `Weather forecast for the ${k.name} district for the next days and links to its ${n} municipalities; combined from the models by which did best in the district.`,
    okresLead: (k, n, pop) => `The ${k.name} district has ${n} municipalities and ${people(pop, "en")}. The forecast for the district and for each municipality is combined from the models by how accurately they did in the district against ČHMÚ station measurements.`,
    openOkres: (k) => `Open the forecast for ${k.name} district`,
    obceOf: (k) => `Municipalities of ${k.name} district`,
    allOkresy: "All districts",
    indexTitle: "Weather by district and municipality: forecast for all of Czechia | MeteoVerdict",
    indexH1: "Weather by district and municipality",
    indexDescription: "Weather forecast for 77 districts and 6 258 municipalities in Czechia, combined from the models by which did best where, and checked against ČHMÚ stations.",
    indexLead: "Pick a district and a municipality in it. The forecast is combined from weather models by how accurately they did in the district against ČHMÚ station measurements.",
    note: "Not an official forecast; official warnings are issued by ČHMÚ.",
    locale: "en", ogLocale: "en_GB", switchLabel: "Čeština", home2: "MeteoVerdict",
  },
};

// --- page shell --------------------------------------------------------------------------------
const STYLE = `<style>
    .place-page main{max-width:44rem;margin:0 auto;padding:1rem}
    .place-page nav.crumbs{font-size:.85rem;margin:0 0 .75rem}
    .place-page .cta{display:inline-block;margin:.75rem 0;padding:.4rem .8rem;border:1px solid currentColor;border-radius:6px;font-weight:600}
    .place-page ul.cols{columns:12rem;padding-left:1.1rem;margin:.5rem 0}
    .place-page .lang a{margin-left:.5rem}
  </style>`;

/**
 * @param spec {lang, title, description, canonical, robots, alternates: {cs, en} | null,
 *   crumbs: [[label, href]], h1, ld, bodyHtml}
 * @param assets `<link>` tags of the stylesheets of the built site
 */
export function shell(spec, assets) {
  const t = T[spec.lang];
  const alt = spec.alternates;
  const links = [`<link rel="canonical" href="${spec.canonical}" />`];
  if (alt) {
    links.push(`<link rel="alternate" hreflang="cs" href="${alt.cs}" />`, `<link rel="alternate" hreflang="en" href="${alt.en}" />`,
      `<link rel="alternate" hreflang="x-default" href="${alt.cs}" />`);
  }
  const otherUrl = alt ? alt[other(spec.lang)].replace(SITE, "") : null;
  const sw = otherUrl ? `<span class="lang"><a href="${otherUrl}" hreflang="${other(spec.lang)}" lang="${other(spec.lang)}">${t.switchLabel}</a></span>` : "";
  const nav = t.nav.map(([href, label]) => `<a href="${href}">${label}</a>`).join("\n        ");
  const crumbs = spec.crumbs.map(([label, href], i) => (i < spec.crumbs.length - 1 ? `<a href="${href}">${esc(label)}</a>` : esc(label))).join(" › ");
  return `<!doctype html>
<html lang="${spec.lang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${esc(spec.title)}</title>
    <meta name="description" content="${esc(spec.description)}" />
    <meta name="robots" content="${spec.robots}" />
    ${links.join("\n    ")}
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="icon" href="/favicon.ico" sizes="48x48" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
    <meta name="theme-color" content="#1d2329" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="MeteoVerdict" />
    <meta property="og:locale" content="${t.ogLocale}" />
    <meta property="og:title" content="${esc(spec.title)}" />
    <meta property="og:description" content="${esc(spec.description)}" />
    <meta property="og:url" content="${spec.canonical}" />
    <meta property="og:image" content="${SITE}/og-image.png" />
    <meta name="twitter:card" content="summary_large_image" />
    <script type="application/ld+json">${json(spec.ld)}</script>
    ${assets}
    ${STYLE}
  </head>
  <body class="page place-page">
    <header>
      <h1 class="logo"><a href="${spec.lang === "en" ? "/en/" : "/"}">MeteoVerdict</a></h1>
      <nav class="site-nav" aria-label="MeteoVerdict">
        ${nav}
      </nav>
      ${sw}
    </header>
    <main class="content">
      <nav class="crumbs" aria-label="breadcrumb">${crumbs}</nav>
      <h2 class="page-title">${esc(spec.h1)}</h2>
${spec.bodyHtml}
      <p class="note">${t.note}</p>
    </main>
  </body>
</html>
`;
}

const breadcrumbLd = (crumbs) => ({
  "@type": "BreadcrumbList",
  itemListElement: crumbs.map(([name, href], i) => ({ "@type": "ListItem", position: i + 1, name, item: SITE + href })),
});

const list = (items) => `<ul class="cols">${items.map(([label, href]) => `<li><a href="${href}">${esc(label)}</a></li>`).join("")}</ul>`;

// --- pages -------------------------------------------------------------------------------------
export function obecPage(lang, okres, obec, assets) {
  const t = T[lang];
  const homeCrumb = [t.forecast, lang === "en" ? "/en/forecast/" : "/predpoved/"];
  const crumbs = [homeCrumb, [okres.name, path(lang, okres)], [obec.name, path(lang, okres, obec)]];
  const english = hasEnglish(obec);
  const alternates = english ? { cs: url("cs", okres, obec), en: url("en", okres, obec) } : null;
  const description = t.obecDescription(obec, okres);
  const near6 = nearest(obec, okres).map((o) => [o.name, path(lang, okres, o)]);
  const body = `      <p class="lead">${esc(t.obecLead(obec, okres))}</p>
      <p>${esc(t.obecBody(obec, okres))}</p>
      <p><a class="cta" href="${appLink(lang, okres, obec)}">${esc(t.open(obec))}</a></p>
      <h3>${t.nearby}</h3>
      ${list(near6)}
      <p><a href="${path(lang, okres)}">${esc(t.okresLink(okres))}</a></p>`;
  const ld = {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbLd(crumbs),
      {
        "@type": "WebPage", name: t.obecH1(obec), description, url: url(lang, okres, obec), inLanguage: lang,
        isPartOf: { "@id": `${SITE}/#website` },
        about: { "@type": "Place", name: obec.name, geo: { "@type": "GeoCoordinates", latitude: obec.lat, longitude: obec.lon, elevation: Math.round(obec.elevation) }, containedInPlace: { "@type": "AdministrativeArea", name: `okres ${okres.name}`, containedInPlace: { "@type": "Country", name: lang === "en" ? "Czechia" : "Česko" } } },
      },
    ],
  };
  return shell({
    lang, title: t.obecTitle(obec, okres), description, canonical: url(lang, okres, obec),
    robots: obec.indexable ? "index,follow" : "noindex,follow", alternates, crumbs, h1: t.obecH1(obec), ld, bodyHtml: body,
  }, assets);
}

export function okresPage(lang, okres, assets) {
  const t = T[lang];
  const crumbs = [[t.forecast, lang === "en" ? "/en/forecast/" : "/predpoved/"], [okres.name, path(lang, okres)]];
  const pop = okres.obce.reduce((n, o) => n + o.population, 0);
  const description = t.okresDescription(okres, okres.obce.length);
  const body = `      <p class="lead">${esc(t.okresLead(okres, okres.obce.length, pop))}</p>
      <p><a class="cta" href="${appLink(lang, okres)}">${esc(t.openOkres(okres))}</a></p>
      <h3>${esc(t.obceOf(okres))}</h3>
      ${list(okres.obce.map((o) => [o.name, path(hasEnglish(o) ? lang : "cs", okres, o)]))}
      <p><a href="${lang === "en" ? "/en/forecast/" : "/predpoved/"}">${t.allOkresy}</a></p>`;
  const ld = { "@context": "https://schema.org", "@graph": [breadcrumbLd(crumbs), { "@type": "WebPage", name: t.okresH1(okres), description, url: url(lang, okres), inLanguage: lang, isPartOf: { "@id": `${SITE}/#website` } }] };
  return shell({
    lang, title: t.okresTitle(okres), description, canonical: url(lang, okres), robots: "index,follow",
    alternates: { cs: url("cs", okres), en: url("en", okres) }, crumbs, h1: t.okresH1(okres), ld, bodyHtml: body,
  }, assets);
}

export function indexPage(lang, okresy, assets) {
  const t = T[lang];
  const crumbs = [[t.forecast, lang === "en" ? "/en/forecast/" : "/predpoved/"]];
  const body = `      <p class="lead">${esc(t.indexLead)}</p>
      ${list(okresy.map((k) => [k.name, path(lang, k)]))}`;
  const ld = { "@context": "https://schema.org", "@graph": [breadcrumbLd(crumbs), { "@type": "CollectionPage", name: t.indexH1, description: t.indexDescription, url: url(lang), inLanguage: lang }] };
  return shell({
    lang, title: t.indexTitle, description: t.indexDescription, canonical: url(lang), robots: "index,follow",
    alternates: { cs: url("cs"), en: url("en") }, crumbs, h1: t.indexH1, ld, bodyHtml: body,
  }, assets);
}

// --- sitemaps ----------------------------------------------------------------------------------
const XMLNS = `xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml"`;

/** entries: [{loc, alternates?: {cs, en}}] → one <urlset> with hreflang alternates where given. */
export function urlset(entries) {
  const rows = entries.map(({ loc, alternates }) => {
    const alt = alternates
      ? `<xhtml:link rel="alternate" hreflang="cs" href="${alternates.cs}"/><xhtml:link rel="alternate" hreflang="en" href="${alternates.en}"/><xhtml:link rel="alternate" hreflang="x-default" href="${alternates.cs}"/>`
      : "";
    return `  <url><loc>${loc}</loc>${alt}</url>`;
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset ${XMLNS}>\n${rows.join("\n")}\n</urlset>\n`;
}

export function sitemapIndex(names) {
  const rows = names.map((n) => `  <sitemap><loc>${SITE}/${n}</loc></sitemap>`);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows.join("\n")}\n</sitemapindex>\n`;
}

/** The sitemaps of the places: okresy (with the index page) and the indexable obce, each in
 * their own file, with the English twin as alternate. */
export function placeSitemaps({ okresy }) {
  const pair = (okres, obec) => ({ loc: url("cs", okres, obec), alternates: { cs: url("cs", okres, obec), en: url("en", okres, obec) } });
  const okresEntries = [{ loc: url("cs"), alternates: { cs: url("cs"), en: url("en") } }, ...okresy.map((k) => pair(k))];
  const obceEntries = okresy.flatMap((k) => k.obce.filter((o) => o.indexable).map((o) => pair(k, o)));
  return { "sitemap-okresy.xml": urlset(okresEntries), "sitemap-obce.xml": urlset(obceEntries) };
}
