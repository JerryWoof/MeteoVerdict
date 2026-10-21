import { defineConfig } from "vite";

// Relative asset paths, so the site works at any root (https://meteoverdict.cz/, or a subpath)
export default defineConfig({
  base: "./",
  // MapLibre alone is about 1 MB minified (280 kB gzipped)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // one page per tab (Map, Forecast, Radar, Measured, Compare, Heatmap, Data) and the detailed
    // forecast per okres; the old names (tv, station, api) redirect from public/
    rollupOptions: {
      input: {
        map: "index.html", forecast: "forecast.html", detail: "forecast-detail.html", radar: "radar.html", measured: "measured.html", compare: "compare.html", compareModels: "compare-models.html", heatmap: "heatmap.html", data: "data.html", about: "about.html", methodology: "methodology.html", collaboration: "collaboration.html", report: "report.html",
      },
    },
  },
});
