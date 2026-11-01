import { defineConfig } from "vite";
import { prerenderI18nPlugin } from "./scripts/prerender-i18n.mjs";

// Relative asset paths, so the site works at any root (https://meteoverdict.cz/, or a subpath)
export default defineConfig({
  base: "./",
  plugins: [prerenderI18nPlugin()],
  // MapLibre alone is about 1 MB minified (280 kB gzipped)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // one page per tab (Map, Forecast with Measured, Radar, Heatmap, Data) and the detailed
    // forecast per okres; the old names (tv, station, measured, api) redirect from public/
    rollupOptions: {
      input: {
        map: "index.html", forecast: "forecast.html", detail: "forecast-detail.html", radar: "radar.html", heatmap: "heatmap.html", data: "data.html", about: "about.html", methodology: "methodology.html", collaboration: "collaboration.html", models: "nejpresnejsi-model.html", privacy: "soukromi.html", credits: "zdroje.html",
      },
    },
  },
});
