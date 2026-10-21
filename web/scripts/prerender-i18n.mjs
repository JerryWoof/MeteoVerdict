// Build-time prerender of the page chrome: every plain-text [data-i18n] element (the menu, the
// language button, headings) gets its Czech text in the HTML, and the menu item of the page
// gets aria-current, so the first paint is already final. English readers get the same
// swap from a tiny inline script before first paint (keys of that page only), so nothing
// blinks when the page script (src/i18n.js, loaded later) applies the language again.
import { STRINGS } from "../src/i18n.js";

const NAV_LINK = /<a\b[^>]*\bhref="([^"]*)"[^>]*>/g;
const TEXT_ELEMENT = /<(\w+)\b([^>]*?\bdata-i18n="([^"]+)"[^>]*)>([^<]*)<\/\1>/g;

export function prerenderI18n(html, file) {
  const keys = new Set();
  // the language button is translated like everything else
  let out = html.replace(/<button\b([^>]*\bid="language"[^>]*)>/, (m, attrs) =>
    attrs.includes("data-i18n") ? m : `<button${attrs} data-i18n="language.switch">`);
  out = out.replace(TEXT_ELEMENT, (m, tag, attrs, key) => {
    const cs = STRINGS.cs[key];
    if (cs === undefined || /[<>&]/.test(cs)) return m;
    keys.add(key);
    return `<${tag}${attrs}>${cs}</${tag}>`;
  });
  // the active menu item, the same on every page
  const page = file === "index.html" ? "./" : file === "compare-models.html" ? "compare.html" : file;
  out = out.replace(/<nav class="site-nav"[\s\S]*?<\/nav>/, (nav) =>
    nav.replace(/ aria-current="page"/g, "").replace(NAV_LINK, (a, href) =>
      href === page ? a.replace(/>$/, ' aria-current="page">') : a));
  if (keys.size === 0) return out;
  const en = Object.fromEntries([...keys].map((key) => [key, STRINGS.en[key] ?? STRINGS.cs[key]]));
  const script = `<script>(function(){try{if(localStorage.getItem("meteoverdict.language")!=="en")return;`
    + `var d=document,e=${JSON.stringify(en).replace(/</g, "\\u003c")};d.documentElement.lang="en";`
    + `d.querySelectorAll("[data-i18n]").forEach(function(n){var t=e[n.dataset.i18n];if(t!==undefined&&!n.children.length)n.textContent=t})}catch(_){}})()</script>`;
  return out.replace("</body>", `    ${script}\n  </body>`);
}

export function prerenderI18nPlugin() {
  return {
    name: "prerender-i18n",
    transformIndexHtml: {
      order: "pre",
      handler(html, ctx) {
        const file = ctx.filename.split(/[\\/]/).pop();
        return prerenderI18n(html, file);
      },
    },
  };
}
