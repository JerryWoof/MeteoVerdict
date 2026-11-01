// Build-time <head> additions for search engines and link previews: canonical, Open Graph, Twitter
// card, and the Czech title/description in the HTML (the English ones are swapped in by a tiny
// inline script, like the rest of the prerendered text). Crawlers without JavaScript read this.
import { STRINGS } from "../src/i18n.js";
import { blocksHtml, inlineHtml } from "../src/blocks-html.js";
import { PAGES as TEXTS } from "../src/pages-text.js";

export const SITE = "https://meteoverdict.cz/";

// file -> [path on the site, Czech description, English description, Czech title when the page has none]
export const PAGES = {
  "index.html": ["", "Předpověď počasí na další dny pro každý okres a obec v Česku, složená z modelů podle toho, jak se v daném místě osvědčily.", "The weather of the next days for every okres, combined from all models by how well each did there."],
  "compare-models.html": ["compare-models.html", "Předpověď počasí pro každou obec v Česku a denní ověřování, který model se trefuje nejlépe, proti měření stanic ČHMÚ.", "Weather forecast for every municipality in Czechia and a daily check of which model forecasts best, against ČHMÚ station measurements.", "Porovnání modelů: který předpovídá nejlépe"],
  "forecast-detail.html": ["forecast-detail.html", "Předpověď počasí pro okres, složená z modelů podle toho, jak se v okrese osvědčily.", "A forecast per okres that combines the weather models by how well each did there."],
  "radar.html": ["radar.html", "Meteoradar ČHMÚ nad Českem: posledních pár hodin plynule, výhled na další hodinu, déšť u vás, bouřkové buňky, družicové mraky a archiv dní.", "ČHMÚ weather radar over Czechia: the last hours played smoothly, the nowcast for the next hour, rain at your place, storm cells, satellite clouds, hourly precipitation and archived days."],
  "heatmap.html": ["heatmap.html", "Experimentální teplotní mapa ve 100 m z terénu (údolí, svahy, mrazové kotliny), počítaná denně. Klikněte kamkoli v Česku pro předpověď v tom místě.", "Experimental: MeteoVerdict AI's temperature at 100 m from the terrain (valleys, slopes, frost hollows), computed daily. Click anywhere in Czechia for the forecast at that place."],
  "data.html": ["data.html", "Otevřená data zdarma: předpověď a pořadí modelů pro každý okres (JSON), archivy, licence a časy aktualizace.", "Free open data: forecast and ranking of weather models per okres (JSON), release archives, licences and update times."],
  "about.html": ["about.html", "Co je MeteoVerdict, odkud má data a jak nás kontaktovat.", "What MeteoVerdict is, where its data comes from and how to contact us."],
  "methodology.html": ["methodology.html", "Jak MeteoVerdict počítá přesnost modelů, jak skládá předpověď a kde jsou hranice.", "How MeteoVerdict measures model accuracy, how it builds the forecast and where the limits are."],
  "collaboration.html": ["collaboration.html", "Kontakt na MeteoVerdict a informace o spolupráci: web je open-source a zdarma.", "Contact MeteoVerdict and how to collaborate: the site is open source and free."],
  "nejpresnejsi-model.html": ["nejpresnejsi-model.html", "Který model počasí je v Česku nejpřesnější? Žádný nevyhrává všude: ALADIN, ICON a ECMWF se liší podle místa, veličiny a předstihu. Jak to měříme a kde je aktuální pořadí.", "Which weather model is the most accurate in Czechia? None wins everywhere: ALADIN, ICON and ECMWF differ by place, variable and lead time. How we measure it and where the current ranking is.", "Který model počasí je nejpřesnější?"],
  "soukromi.html": ["soukromi.html", "Soukromí na MeteoVerdictu: žádné cookies, anonymní statistiky, poloha jen v prohlížeči.", "Privacy on MeteoVerdict: no cookies, anonymous statistics, your location stays in the browser."],
  "zdroje.html": ["zdroje.html", "Zdroje dat MeteoVerdictu a jejich licence: ČHMÚ, Open-Meteo, modely, ČÚZK, OpenStreetMap a další.", "Data sources of MeteoVerdict and their licences: ČHMÚ, Open-Meteo, the models, ČÚZK, OpenStreetMap and others."],
};

const ANALYTICS = `<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": "bfd729fcbbdf4e3094786a0ff9e359c8"}'></script>`;

const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

export function injectSeo(html, file) {
  const page = PAGES[file];
  if (!page || !html.includes("</head>")) return html;
  const [path, cs, en, csTitle] = page;
  const url = SITE + path;
  let out = html;
  const titleKey = out.match(/<title\b[^>]*\bdata-i18n-page="([^"]+)"/)?.[1];
  if (titleKey && STRINGS.cs[titleKey]) {
    out = out.replace(/(<title\b[^>]*>)[^<]*(<\/title>)/, `$1MeteoVerdict: ${esc(STRINGS.cs[titleKey])}$2`);
  } else if (csTitle) {
    out = out.replace(/(<title\b[^>]*>)[^<]*(<\/title>)/, `$1MeteoVerdict: ${esc(csTitle)}$2`);
  }
  const title = out.match(/<title\b[^>]*>([^<]*)<\/title>/)?.[1] ?? "MeteoVerdict";
  out = out.replace(/<meta\s+name="description"[\s\S]*?\/>/, `<meta name="description" content="${esc(cs)}" />`);
  const tags = [
    `<link rel="canonical" href="${url}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="MeteoVerdict" />`,
    `<meta property="og:locale" content="cs_CZ" />`,
    `<meta property="og:title" content="${title}" />`,
    `<meta property="og:description" content="${esc(cs)}" />`,
    `<meta property="og:url" content="${url}" />`,
    `<meta property="og:image" content="${SITE}og-image.png" />`,
    `<meta property="og:image:width" content="1200" />`,
    `<meta property="og:image:height" content="630" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${title}" />`,
    `<meta name="twitter:description" content="${esc(cs)}" />`,
    `<meta name="twitter:image" content="${SITE}og-image.png" />`,
    `<meta name="theme-color" content="#1d2329" />`,
    `<link rel="apple-touch-icon" href="/apple-touch-icon.png" />`,
  ].map((t) => `    ${t}\n`).join("");
  out = out.replace("</head>", `${tags}  </head>`);
  // English readers: the description (the title is swapped by src/i18n.js, the Czech one stays in the HTML)
  const script = `<script>(function(){try{if(localStorage.getItem("meteoverdict.language")!=="en")return;`
    + `var d=document,t=${JSON.stringify(en).replace(/</g, "\\u003c")};`
    + `["meta[name=description]","meta[property='og:description']","meta[name='twitter:description']"].forEach(function(s){var m=d.querySelector(s);if(m)m.setAttribute("content",t)})}catch(_){}})()</script>`;
  out = out.includes("</body>") ? out.replace("</body>", `    ${script}\n  </body>`) : out;
  // Cloudflare Web Analytics: cookieless page views and Web Vitals, no personal data (the site token is public)
  return out.includes("</body>") ? out.replace("</body>", `    ${ANALYTICS}\n  </body>`) : out;
}

// The text pages (About, Methodology, Collaboration): their Czech text in the HTML, replaced by
// src/info-page.js at load; the About page also gets FAQPage structured data from its Q&A blocks.
export function injectInfoText(html) {
  const key = html.match(/<main\b[^>]*\bdata-page="([^"]+)"/)?.[1];
  const text = key && TEXTS[key]?.cs;
  if (!text) return html;
  let out = html.replace(/(<h2 id="info-title"[^>]*>)[^<]*(<\/h2>)/, `$1${esc(text.title)}$2\n        <div data-prerender>\n${blocksHtml(text.blocks)}        </div>`);
  const faq = [];
  text.blocks.forEach(([kind, body], i) => {
    if (kind === "h3" && text.blocks[i + 1]?.[0] === "p") {
      faq.push({ "@type": "Question", name: body, acceptedAnswer: { "@type": "Answer", text: inlineHtml(text.blocks[i + 1][1]).replace(/<[^>]+>/g, "") } });
    }
  });
  if (faq.length) {
    const ld = JSON.stringify({ "@context": "https://schema.org", "@type": "FAQPage", mainEntity: faq }).replace(/</g, "\\u003c");
    out = out.replace("</head>", `    <script type="application/ld+json">${ld}</script>\n  </head>`);
  }
  return out;
}
