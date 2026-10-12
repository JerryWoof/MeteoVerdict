import { defineConfig } from "vite";

// Relative asset paths: the site is served from https://<user>.github.io/meteoverdict/
export default defineConfig({
  base: "./",
  // MapLibre alone is about 1 MB minified (280 kB gzipped)
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // three pages: the map, the model comparison and the forecast per okres
    rollupOptions: {
      input: { map: "index.html", compare: "compare.html", forecast: "forecast.html" },
    },
  },
});
