import { translator } from "../src/i18n.js";
import { SITE_LINKS } from "../src/footer.js";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

/** The inside of the footer without JavaScript: the same links (src/footer.js), under /en/ in English. */
export function footerInner(lang) {
  const t = translator(lang);
  const prefix = lang === "en" ? "/en/" : "/";
  const links = SITE_LINKS.map(([key, cs, en]) => {
    const href = (lang === "en" && en) || cs;
    const external = /^https:/.test(href);
    return `<a href="${external || href.startsWith("/") ? href : prefix + href}"${/^https:\/\/verify\./.test(href) ? ' target="_blank" rel="noopener"' : ""}>${esc(t(key))}</a>`;
  }).join(" · ");
  return `<nav class="site-links" aria-label="${esc(t("site.about"))}">${links}</nav> · © MeteoVerdict, ${esc(t("footer.data"))} <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>`;
}
