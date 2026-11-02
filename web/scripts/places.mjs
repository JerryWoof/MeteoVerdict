// Static pages of the 77 okresy: /predpoved/<okres>/ (English: /en/forecast/<okres>/), built after
// `vite build` (scripts/build-places.mjs) only when the deploy has the forecast (outlook.json):
// a crawler without JavaScript reads the real numbers of the next days, not just a link. No pages
// for the 6 258 obce (decided against: too many near-identical pages).
// Pure functions: the file work is in build-places.mjs.
import { fold } from "../src/places.js";

export const SITE = "https://meteoverdict.cz";

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

/** okresy: [{code, name}], rows: parseCsv() → [{code, name, slug, obce, population}] by name. */
export function buildPlaces(okresy, rows) {
  const byCode = new Map(okresy.map((o) => {
    const name = o.name === "Hlavní město Praha" ? "Praha" : o.name;
    return [o.code, { code: o.code, name, slug: slugify(name), obce: 0, population: 0 }];
  }));
  for (const r of rows) {
    const okres = byCode.get(r.okres);
    if (!okres) continue;
    okres.obce += 1;
    okres.population += Number(r.population) || 0;
  }
  return [...byCode.values()].sort((a, b) => a.name.localeCompare(b.name, "cs"));
}

// --- addresses ---------------------------------------------------------------------------------
export const path = (lang, okres) => `${lang === "en" ? "/en/forecast/" : "/predpoved/"}${okres ? `${okres.slug}/` : ""}`;
const url = (lang, okres) => SITE + path(lang, okres);
const other = (lang) => (lang === "en" ? "cs" : "en");
/** The interactive forecast of the okres. */
export const appLink = (lang, okres) => `${lang === "en" ? "/en/" : "/"}#${okres.code}`;

// --- texts -------------------------------------------------------------------------------------
const fmt = (n, lang) => Number(n).toLocaleString(lang === "en" ? "en-GB" : "cs-CZ").replace(/\u00a0/g, " ");
const people = (n, lang) => (lang === "en" ? `${fmt(n, lang)} inhabitants` : `${fmt(n, lang)} obyvatel`);

const T = {
  cs: {
    forecast: "Předpověď počasí",
    nav: [["/", "Předpověď"], ["/radar.html", "Radar"], ["/heatmap.html", "Heatmapa"], ["/compare-models.html", "Porovnání modelů"]],
    okresTitle: (k) => `Počasí v okrese ${k.name}: předpověď na týden | MeteoVerdict`,
    okresH1: (k) => `Počasí v okrese ${k.name}`,
    okresDescription: (k, first) => `Předpověď počasí v okrese ${k.name} na další dny${first ? `: ${first}` : ""}. Složená z modelů podle toho, který se v okrese osvědčil nejlépe.`,
    okresLead: (k, pop, updated) => `Okres ${k.name} má ${k.obce} obcí a ${people(pop, "cs")}. Předpověď je složená z meteorologických modelů podle toho, jak přesně se v okrese osvědčily proti měření stanic ČHMÚ${updated ? `; stav z ${updated}` : ""}.`,
    cols: ["Den", "Nejvyšší", "Nejnižší", "Srážky", "Vítr"],
    units: ["°C", "°C", "mm", "m/s"],
    first: (d, max, min) => `${d} ${max} °C ve dne, ${min} °C v noci`,
    openOkres: (k) => `Otevřít podrobnou předpověď pro okres ${k.name}`,
    allOkresy: "Všechny okresy",
    indexTitle: "Počasí podle okresů: předpověď pro celé Česko | MeteoVerdict",
    indexH1: "Počasí podle okresů",
    indexDescription: "Předpověď počasí pro okresy v Česku. Skládáme ji z modelů podle toho, který se v kterém okrese osvědčil, a měříme ji proti stanicím ČHMÚ.",
    indexLead: "Vyberte okres. Předpověď je složená z meteorologických modelů podle toho, jak přesně se v okrese osvědčily proti měření stanic ČHMÚ.",
    note: "Nejde o oficiální předpověď; oficiální výstrahy vydává ČHMÚ.",
    ogLocale: "cs_CZ", switchLabel: "English",
  },
  en: {
    forecast: "Weather forecast",
    nav: [["/en/", "Forecast"], ["/en/radar.html", "Radar"], ["/en/heatmap.html", "Heatmap"], ["/en/compare-models.html", "Model comparison"]],
    okresTitle: (k) => `Weather in ${k.name} district: week forecast | MeteoVerdict`,
    okresH1: (k) => `Weather in ${k.name} district`,
    okresDescription: (k, first) => `Weather forecast for the ${k.name} district for the next days${first ? `: ${first}` : ""}. Combined from the models by which did best in the district.`,
    okresLead: (k, pop, updated) => `The ${k.name} district has ${k.obce} municipalities and ${people(pop, "en")}. The forecast is combined from weather models by how accurately they did in the district against ČHMÚ station measurements${updated ? `; as of ${updated}` : ""}.`,
    cols: ["Day", "High", "Low", "Rain", "Wind"],
    units: ["°C", "°C", "mm", "m/s"],
    first: (d, max, min) => `${d} high ${max} °C, low ${min} °C`,
    openOkres: (k) => `Open the detailed forecast for ${k.name} district`,
    allOkresy: "All districts",
    indexTitle: "Weather by district: forecast for all of Czechia | MeteoVerdict",
    indexH1: "Weather by district",
    indexDescription: "Weather forecast for the districts of Czechia, combined from the models by which did best where, and checked against ČHMÚ stations.",
    indexLead: "Pick a district. The forecast is combined from weather models by how accurately they did in the district against ČHMÚ station measurements.",
    note: "Not an official forecast; official warnings are issued by ČHMÚ.",
    ogLocale: "en_GB", switchLabel: "Čeština",
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
const oneDecimal = (v, lang) => Number(v).toLocaleString(lang === "en" ? "en-GB" : "cs-CZ", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const dayLabel = (iso, lang) => new Intl.DateTimeFormat(lang === "en" ? "en-GB" : "cs-CZ", { weekday: "short", day: "numeric", month: "numeric", timeZone: "UTC" }).format(new Date(`${iso}T12:00:00Z`));

/**
 * The days of an okres from outlook.json's rows: rows(day, part) → row | undefined. A day without
 * a "day" row is left out. → [{day, tmax, tmin, rain, wind}]
 */
export function forecastDays(days, rowFor) {
  return days.map((day) => {
    const d = rowFor(day, "day");
    const n = rowFor(day, "night");
    return d && Number.isFinite(d.tmax) ? { day, tmax: d.tmax, tmin: Number.isFinite(n?.tmin) ? n.tmin : null, rain: d.precipitation ?? null, wind: d.wind ?? null } : null;
  }).filter(Boolean);
}

const cell = (v, lang) => (v == null || !Number.isFinite(v) ? "–" : oneDecimal(v, lang));

export function okresPage(lang, okres, days, updated, assets) {
  const t = T[lang];
  const crumbs = [[t.forecast, path(lang)], [okres.name, path(lang, okres)]];
  const first = days[0] ? t.first(dayLabel(days[0].day, lang), Math.round(days[0].tmax), Math.round(days[0].tmin ?? days[0].tmax)) : "";
  const description = t.okresDescription(okres, days[0]?.tmin == null ? "" : first);
  const head = t.cols.map((c, i) => `<th>${c}${i ? ` (${t.units[i - 1]})` : ""}</th>`).join("");
  const rows = days.map((d) => `<tr><td>${dayLabel(d.day, lang)}</td><td>${cell(d.tmax, lang)}</td><td>${cell(d.tmin, lang)}</td><td>${cell(d.rain, lang)}</td><td>${cell(d.wind, lang)}</td></tr>`).join("");
  const body = `      <p class="lead">${esc(t.okresLead(okres, okres.population, updated))}</p>
      <div class="scroll"><table class="doc-table data-table"><tr>${head}</tr>${rows}</table></div>
      <p><a class="cta" href="${appLink(lang, okres)}">${esc(t.openOkres(okres))}</a></p>
      <p><a href="${path(lang)}">${t.allOkresy}</a></p>`;
  const ld = { "@context": "https://schema.org", "@graph": [breadcrumbLd(crumbs), { "@type": "WebPage", name: t.okresH1(okres), description, url: url(lang, okres), inLanguage: lang, isPartOf: { "@id": `${SITE}/#website` } }] };
  return shell({
    lang, title: t.okresTitle(okres), description, canonical: url(lang, okres), robots: "index,follow",
    alternates: { cs: url("cs", okres), en: url("en", okres) }, crumbs, h1: t.okresH1(okres), ld, bodyHtml: body,
  }, assets);
}

export function indexPage(lang, okresy, assets) {
  const t = T[lang];
  const crumbs = [[t.forecast, path(lang)]];
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

/** The sitemap of the okres pages (with the index page), English twins as alternates. */
export function placeSitemaps(okresy) {
  const pair = (okres) => ({ loc: url("cs", okres), alternates: { cs: url("cs", okres), en: url("en", okres) } });
  return { "sitemap-okresy.xml": urlset([pair(), ...okresy.map(pair)]) };
}
