import { defineConfig } from "vite";

// Relative asset paths: the site is served from https://<user>.github.io/meteoverdict/
export default defineConfig({
  base: "./",
  // MapLibre alone is about 1 MB minified (280 kB gzipped)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // four pages: the score map, the model comparison, the detailed forecast per okres
    // and the TV-style forecast map
    rollupOptions: {
      input: { map: "index.html", compare: "compare.html", forecast: "forecast.html", tv: "tv.html" },
    },
  },
});
