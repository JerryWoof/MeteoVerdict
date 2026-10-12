import { Map as MapLibreMap, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre's ES module build loads its worker from a separate file
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import {
  NO_DATA, TOO_FEW, bestByRegion, describe, fillExpression, modelColors, records,
  stationFeatures,
} from "./data.js";
import { statusText } from "./status.js";

setWorkerUrl(workerUrl);

// What the map shows until the controls exist (roadmap 4.3)
const VIEW = { window: "90d", variable: "temperature_2m", leadDay: 1 };

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
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const scores = (level) =>
  getJson(`data/scores/${VIEW.window}/${level}/${VIEW.variable}.json`).then(records);

function legend(colors, names, shown) {
  const items = Object.entries(colors)
    .filter(([id]) => shown.has(id))
    .map(([id, color]) => [names[id] ?? id, color]);
  items.push(["too few stations", TOO_FEW], ["no data", NO_DATA]);
  const element = document.getElementById("legend");
  element.replaceChildren(
    ...items.map(([label, color]) => {
      const row = document.createElement("div");
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = color;
      row.append(swatch, label);
      return row;
    }),
  );
}

function popupOn(layer, best, names) {
  map.on("click", layer, (event) => {
    const feature = event.features[0];
    const entry = best.get(feature.properties.code);
    const title = entry?.name ?? feature.properties.name;
    const text = document.createElement("div");
    const heading = document.createElement("strong");
    heading.textContent = title;
    text.append(heading, document.createElement("br"), describe(entry, names));
    new Popup().setLngLat(event.lngLat).setDOMContent(text).addTo(map);
  });
  map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
}

map.on("load", async () => {
  const meta = await getJson("data/scores/meta.json");
  document.getElementById("status").textContent = statusText(meta);
  const names = meta?.models ?? {};
  const colors = modelColors(names);

  // okres choropleth where the okres level is published, kraj otherwise
  let level = "okres";
  let rows = await scores("okres");
  if (rows.length === 0) {
    level = "kraj";
    rows = await scores("kraj");
  }
  const regions = bestByRegion(rows, VIEW.leadDay);
  const stationBest = bestByRegion(await scores("station"), VIEW.leadDay);
  const stations = await getJson("data/scores/stations.json");

  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addSource("stations", {
    type: "geojson",
    data: stationFeatures(stations, stationBest, colors),
  });
  const filled = level === "okres" ? "okresy" : "kraje";
  map.addLayer({
    id: "regions-fill",
    type: "fill",
    source: filled,
    paint: { "fill-color": fillExpression(regions, colors), "fill-opacity": 0.75 },
  });
  map.addLayer({
    id: "okresy-line",
    type: "line",
    source: "okresy",
    paint: { "line-color": "#ffffff", "line-width": 0.6 },
  });
  map.addLayer({
    id: "kraje-line",
    type: "line",
    source: "kraje",
    paint: { "line-color": "#4b5863", "line-width": 1.2 },
  });
  map.addLayer({
    id: "stations",
    type: "circle",
    source: "stations",
    paint: {
      "circle-radius": 3.5,
      "circle-color": ["get", "color"],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1,
    },
  });
  popupOn("regions-fill", regions, names);
  popupOn("stations", stationBest, names);
  const shown = new Set([...regions.values(), ...stationBest.values()].map((e) => e.model));
  legend(colors, names, shown);
});
