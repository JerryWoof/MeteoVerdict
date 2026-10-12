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
import {
  VARIABLES, WINDOWS, availableLeadDays, availableVariables, parseHash, toHash,
} from "./view.js";

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
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const scores = (view, level) =>
  getJson(`data/scores/${view.window}/${level}/${view.variable}.json`).then(records);

/** Fill a <select> with [value, label] pairs and select `current`. */
function fillSelect(id, options, current) {
  const select = document.getElementById(id);
  select.replaceChildren(
    ...options.map(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = String(value) === String(current);
      return option;
    }),
  );
  return select;
}

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

// the data behind the current view, read by the popups
const current = { regions: new Map(), stations: new Map(), names: {} };

function popupOn(layer, key) {
  map.on("click", layer, (event) => {
    const feature = event.features[0];
    const entry = current[key].get(feature.properties.code);
    const title = entry?.name ?? feature.properties.name;
    const text = document.createElement("div");
    const heading = document.createElement("strong");
    heading.textContent = title;
    text.append(heading, document.createElement("br"), describe(entry, current.names));
    new Popup().setLngLat(event.lngLat).setDOMContent(text).addTo(map);
  });
  map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
}

function addLayers(filled, stations) {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addSource("stations", { type: "geojson", data: stations });
  map.addLayer({
    id: "regions-fill",
    type: "fill",
    source: filled,
    paint: { "fill-color": NO_DATA, "fill-opacity": 0.75 },
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
  popupOn("regions-fill", "regions");
  popupOn("stations", "stations");
}

map.on("load", async () => {
  const meta = await getJson("data/scores/meta.json");
  document.getElementById("status").textContent = statusText(meta);
  const names = meta?.models ?? {};
  const colors = modelColors(names);
  const stationTable = await getJson("data/scores/stations.json");
  current.names = names;

  // okres choropleth where the okres level is published, kraj otherwise
  const probe = parseHash(window.location.hash);
  const level = (await scores(probe, "okres")).length ? "okres" : "kraj";
  addLayers(level === "okres" ? "okresy" : "kraje", stationFeatures(null, new Map(), colors));

  async function render(view) {
    const rows = await scores(view, level);
    const leadDays = availableLeadDays(rows);
    if (!leadDays.includes(view.leadDay)) view.leadDay = leadDays[0];
    fillSelect("lead", leadDays.map((d) => [d, `D+${d}`]), view.leadDay);
    current.regions = bestByRegion(rows, view.leadDay);
    current.stations = bestByRegion(await scores(view, "station"), view.leadDay);
    map.setPaintProperty("regions-fill", "fill-color", fillExpression(current.regions, colors));
    map.getSource("stations").setData(stationFeatures(stationTable, current.stations, colors));
    const shown = new Set(
      [...current.regions.values(), ...current.stations.values()].map((e) => e.model),
    );
    legend(colors, names, shown);
    window.history.replaceState(null, "", toHash(view));
  }

  const view = parseHash(window.location.hash);
  const variables = availableVariables(meta).map((v) => [v, VARIABLES[v]]);
  fillSelect("variable", variables, view.variable);
  fillSelect("window", Object.entries(WINDOWS), view.window);
  for (const [id, key, parse] of [
    ["variable", "variable", String],
    ["lead", "leadDay", Number],
    ["window", "window", String],
  ]) {
    document.getElementById(id).addEventListener("change", (event) => {
      view[key] = parse(event.target.value);
      render(view);
    });
  }
  await render(view);
});
