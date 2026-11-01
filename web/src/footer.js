// The footer of all pages, in one place: one compact line of links to the project pages and
// the licence of our own data. The credits of every source (docs/licensing.md, rule 2) are on
// the page Zdroje a licence (zdroje.html, text in credits-text.js), linked from here, and the
// map's own credits (OpenFreeMap, OpenMapTiles, OpenStreetMap, relief) stay in its attribution
// control. Each page has <footer data-footer>; setUpLanguage() fills it.

export const CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/";
export const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
export const TERRAIN_ATTRIBUTION = "https://github.com/tilezen/joerd/blob/master/docs/attribution.md";

/** Fill a <footer data-footer> in the page's language. */
export function renderFooter(footer, t) {
  const licence = document.createElement("a");
  licence.href = CC_BY_SA;
  licence.textContent = "CC BY-SA 4.0";
  footer.replaceChildren(siteLinks(t), ` · © MeteoVerdict, ${t("footer.data")} `, licence);
}

/** The links on every page: About, Methodology, Data, the independent verification of the
 * measurements (verify.meteoverdict.cz, opens in a new tab), Contact (with the collaboration), Privacy,
 * Sources and licences, and the sister site Půdoměr (soil temperature and moisture). */
export const SITE_LINKS = [
  ["site.about", "about.html"],
  ["site.method", "methodology.html"],
  ["page.api", "data.html"],
  ["site.verify", "https://verify.meteoverdict.cz/"],
  ["site.contact", "collaboration.html"],
  ["site.privacy", "soukromi.html"],
  ["site.credits", "zdroje.html"],
  ["site.pudomer", "https://pudomer.cz/"],
];

function siteLinks(t) {
  const nav = document.createElement("nav");
  nav.className = "site-links";
  nav.setAttribute("aria-label", t("site.about"));
  SITE_LINKS.forEach(([key, href], k) => {
    if (k) nav.append(" · ");
    const a = document.createElement("a");
    a.href = href;
    if (/^https:\/\/verify\./.test(href)) {
      a.target = "_blank";
      a.rel = "noopener";
    }
    a.textContent = t(key);
    nav.append(a);
  });
  return nav;
}
