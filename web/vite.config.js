import { defineConfig } from "vite";

// Relative asset paths: the site is served from https://<user>.github.io/MeteoVerdict/
export default defineConfig({
  base: "./",
  // MapLibre alone is about 1 MB minified (280 kB gzipped)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // the score map, the model comparison, the detailed forecast per okres, the
    // TV-style forecast map, the open data page, the radar and the station page
    rollupOptions: {
      input: {
        map: "index.html", compare: "compare.html", forecast: "forecast.html", tv: "tv.html", api: "api.html", station: "station.html", radar: "radar.html",
      },
    },
  },
});
