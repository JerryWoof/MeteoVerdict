import { defineConfig } from "vite";

// Relative asset paths: the site is served from https://<user>.github.io/MeteoVerdict/
export default defineConfig({
  base: "./",
  // MapLibre alone is about 1 MB minified (280 kB gzipped)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // one page per tab (Map, Forecast, Radar, Measured, Compare, AI forecast, AI heatmap, Data) and the detailed
    // forecast per okres; the old names (tv, station, api) redirect from public/
    rollupOptions: {
      input: {
        map: "index.html", forecast: "forecast.html", detail: "forecast-detail.html", radar: "radar.html", measured: "measured.html", compare: "compare.html", ai: "ai.html", heatmap: "heatmap.html", data: "data.html", about: "about.html",
      },
    },
  },
});
