import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre's ES module build loads its worker from a separate file
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { statusText } from "./status.js";

setWorkerUrl(workerUrl);

// Czechia, with a little margin
const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];

// No third-party tiles: the map is the region boundaries on a plain background.
const map = new MapLibreMap({
  container: "map",
  style: {
    version: 8,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": "#f4f1ea" } }],
  },
  bounds: BOUNDS,
  fitBoundsOptions: { padding: 20 },
  attributionControl: { customAttribution: "Boundaries: ČÚZK (CC BY 4.0)" },
});
map.addControl(new NavigationControl({ showCompass: false }));

async function getJson(path) {
  const response = await fetch(path);
  return response.ok ? response.json() : null;
}

map.on("load", async () => {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({
    id: "okresy-fill",
    type: "fill",
    source: "okresy",
    paint: { "fill-color": "#dfe7ec", "fill-opacity": 0.8 },
  });
  map.addLayer({
    id: "okresy-line",
    type: "line",
    source: "okresy",
    paint: { "line-color": "#9aa7b1", "line-width": 0.5 },
  });
  map.addLayer({
    id: "kraje-line",
    type: "line",
    source: "kraje",
    paint: { "line-color": "#4b5863", "line-width": 1.2 },
  });
  document.getElementById("status").textContent = statusText(
    await getJson("data/scores/meta.json"),
  );
});
