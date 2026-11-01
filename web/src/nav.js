// The main menu, the one list every page's menu is built from (scripts/prerender-i18n.mjs
// writes it into each page at build time; nav.test.js checks the HTML sources agree with it).
export const NAV = [
  { href: "./", key: "page.tv", label: "Předpověď" },
  { href: "radar.html", key: "page.radar", label: "Radar" },
  { href: "heatmap.html", key: "page.heatmap", label: "Heatmapa" },
  { href: "compare-models.html", key: "page.compareModels", label: "Porovnání modelů" },
];

// pages that belong under a menu item without being one (the detail opens from the forecast)
const BELONGS_TO = { "forecast-detail.html": "./" };

export function navHtml(file) {
  const active = file === "index.html" ? "./" : BELONGS_TO[file] ?? file;
  const links = NAV.map((n) =>
    `        <a href="${n.href}" data-i18n="${n.key}"${n.href === active ? ' aria-current="page"' : ""}>${n.label}</a>`);
  return `<nav class="site-nav" aria-label="MeteoVerdict">\n${links.join("\n")}\n      </nav>`;
}
