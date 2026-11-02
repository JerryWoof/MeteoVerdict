// English copies of the built pages under /en/ (same files, English texts in the HTML), with
// canonical, hreflang and a <base href="/"> so the pages' relative data and asset paths still
// resolve under /en/. Pure string work on the built HTML; build-places.mjs writes the files.
import { STRINGS } from "../src/i18n.js";
import { PAGES as TEXTS } from "../src/pages-text.js";
import { blocksHtml } from "../src/blocks-html.js";
import { PAGES, SITE } from "./seo.mjs";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const TEXT_ELEMENT = /<(\w+)\b([^>]*?\bdata-i18n="([^"]+)"[^>]*)>([^<]*)<\/\1>/g;

/** Where the English copy of a built file lives: "index.html" → "en/index.html". */
export const enFile = (file) => `en/${file}`;
/** The page's address on the site in each language. */
export const addresses = (file) => {
  const p = PAGES[file][0];
  return { cs: SITE + p, en: `${SITE}en/${p}` };
};

// the one script of the English pages: the language is the path's; <base> must not turn the
// pages' own "#…" history writes into addresses of the Czech root
const HEAD = `<base href="/" /><script>(function(){try{localStorage.setItem("meteoverdict.language","en")}catch(_){}`
  + `var h=history,p=location.pathname;["replaceState","pushState"].forEach(function(k){var f=h[k];h[k]=function(s,t,u){return f.call(h,s,t,typeof u==="string"&&u[0]==="#"?p+location.search+u:u)}})})()</script>`;

export function toEnglish(html, file) {
  const page = PAGES[file];
  if (!page) return null;
  const { cs: csUrl, en: enUrl } = addresses(file);
  const description = esc(page[2]);
  let out = html.replace('<html lang="cs">', '<html lang="en">');
  out = out.replace(/(<title\b[^>]*\bdata-i18n-page="([^"]+)"[^>]*>)[^<]*(<\/title>)/, (m, a, key, z) => `${a}MeteoVerdict: ${esc(STRINGS.en[key] ?? STRINGS.cs[key])}${z}`);
  out = out.replace(TEXT_ELEMENT, (m, tag, attrs, key) => {
    const en = STRINGS.en[key];
    return en === undefined || /[<>&]/.test(en) ? m : `<${tag}${attrs}>${en}</${tag}>`;
  });
  // description and social tags
  out = out.replace(/(<meta\s+name="description"\s+content=")[^"]*"/, `$1${description}"`)
    .replace(/(<meta property="og:description" content=")[^"]*"/, `$1${description}"`)
    .replace(/(<meta name="twitter:description" content=")[^"]*"/, `$1${description}"`)
    .replace('og:locale" content="cs_CZ"', 'og:locale" content="en_GB"')
    .replace(/(<link rel="canonical" href=")[^"]*"/, `$1${enUrl}"`)
    .replace(/(<meta property="og:url" content=")[^"]*"/, `$1${enUrl}"`);
  const og = out.match(/<title\b[^>]*>([^<]*)<\/title>/)?.[1];
  if (og) out = out.replace(/(og:title" content=")[^"]*"/, `$1${og}"`).replace(/(twitter:title" content=")[^"]*"/, `$1${og}"`);
  // the text pages: the English text in place of the Czech one
  const key = out.match(/<main\b[^>]*\bdata-page="([^"]+)"/)?.[1];
  const text = key && TEXTS[key];
  if (text) {
    out = out.replace(blocksHtml(text.cs.blocks), blocksHtml(text.en.blocks))
      .replace(/(<h2 id="info-title"[^>]*>)[^<]*(<\/h2>)/, `$1${esc(text.en.title)}$2`)
      .replace(/\s*<script type="application\/ld\+json">\{"@context":"https:\/\/schema.org","@type":"FAQPage".*?<\/script>/s, "");
  }
  // the page's own menu and footer links stay inside /en/
  const names = new Set(Object.keys(PAGES));
  out = out.replace(/(<a\b[^>]*\bhref=")([^"#]*)(")/g, (m, a, href, z) => {
    if (href === "./") return `${a}/en/${z}`;
    return names.has(href) ? `${a}/en/${href}${z}` : m;
  });
  const alternates = `<link rel="alternate" hreflang="cs" href="${csUrl}" />\n    <link rel="alternate" hreflang="en" href="${enUrl}" />\n    <link rel="alternate" hreflang="x-default" href="${csUrl}" />\n    `;
  out = out.replace("</head>", `    ${alternates}</head>`).replace("<head>", `<head>\n    ${HEAD}`);
  return out;
}

/** The Czech page gets the same alternates. */
export function addAlternates(html, file) {
  const { cs, en } = addresses(file);
  const tags = `    <link rel="alternate" hreflang="cs" href="${cs}" />\n    <link rel="alternate" hreflang="en" href="${en}" />\n    <link rel="alternate" hreflang="x-default" href="${cs}" />\n`;
  return html.replace("</head>", `${tags}  </head>`);
}
