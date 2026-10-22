// Light or dark colours, the same as on pudomer.cz: an icon button next to the CS | EN
// switch flips between the two, light is the default, and the choice is remembered. The
// tiny script in every page's <head> (scripts/prerender-i18n.mjs) sets <html data-theme>
// before the first paint, so no page flashes in the other colours.

export const THEME_KEY = "meteoverdict.theme";

/** The inline <head> script: data-theme from the stored choice, light otherwise. */
export const THEME_HEAD_SCRIPT = `<script>try{document.documentElement.dataset.theme=localStorage.getItem("${THEME_KEY}")==="dark"?"dark":"light"}catch(e){document.documentElement.dataset.theme="light"}</script>`;

// sun (light) and moon (dark), both in the button; CSS shows the one of the current theme
const SUN = '<svg class="theme-light" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/></g></svg>';
const MOON = '<svg class="theme-dark" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" fill="currentColor"/></svg>';

/** The button, prerendered after the language switch on every page. */
export const THEME_BUTTON = `<button id="theme" class="iconbtn" type="button" title="Barevný režim" aria-label="Barevný režim">${SUN}${MOON}</button>`;

const listeners = [];

/** Whether the page shows dark colours now. */
export function isDark() {
  return globalThis.document?.documentElement.dataset.theme === "dark";
}

/** cb(dark) after every switch (maps and charts redraw in the new colours). */
export function onThemeChange(cb) {
  listeners.push(cb);
}

/** A CSS custom property's current value, e.g. cssVar("--ink"). */
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Wires the button: its label in the page language, the click flips and stores the theme. */
export function setUpTheme(t) {
  const button = document.getElementById("theme");
  const label = () => {
    if (!button) return;
    button.title = t("theme.mode", { mode: t(isDark() ? "theme.dark" : "theme.light") });
    button.setAttribute("aria-label", button.title);
  };
  label();
  button?.addEventListener("click", () => {
    const theme = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // private mode: the choice lasts for this page only
    }
    label();
    for (const cb of listeners) cb(theme === "dark");
  });
}
