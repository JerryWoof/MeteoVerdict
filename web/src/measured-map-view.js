// The measured-weather map of measured.html's landing: okres and kraj boundaries (zoomed
// in over the radar page's base map), every ČHMÚ station with a value as a dot coloured by the chosen
// value, and the forecast map's markers (symbol, temperature, value chips) on the
// stations that fit without overlapping (measured.js pickLabels: the main stations at
// the country's zoom, more as you zoom in). A click on a dot or a label opens the station.
// The okres layer instead colours the okresy by the mean of their stations, with one
// label per okres, as the forecast map did for the past days; a click opens its panel.
import { Map as MapLibreMap, Marker, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

import { drawIcon, glyph, iconCanvas } from "./icons.js";
import { pickLabels } from "./measured.js";
import { NEUTRAL, RAMPS, colorFor, rampKey } from "./palette.js";
import { ALL_LAYERS, iconName, labelFor, valueFor } from "./tv.js";
import { panelRoom } from "./panel-room.js";
import { BASEMAP_ATTRIBUTION, GLYPHS, baseLayers, basemapSources, topLayers } from "./radar-basemap.js";

setWorkerUrl(workerUrl);

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
const EMPTY = { type: "FeatureCollection", features: [] };
const HIT_PX = 8;
const GREY = "#9aa3ab";
// zoomed in, the radar page's base map (relief, water, rivers, main roads, town names)
// under the okres colours, which turn see-through, as on the forecast map
const BASE_ZOOM = 7.5;
// from this zoom the okres layer shows the stations instead of the okres means, with names
const STATION_ZOOM = 8.5;

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

/**
 * @param {object} options
 * @param {HTMLElement} options.container
 * @param {(key: string, params?: object) => string} options.t
 * @param {(row: object) => void} options.onPick a station's (or an okres's) row was clicked
 * @param {(code: string) => void} options.onOkres an okres was clicked (okres layer)
 * @param {(row: object, part: string) => string} options.describe its values in one line
 */
export function createMeasuredMap({ container, t, onPick, onOkres, describe }) {
  const map = new MapLibreMap({
    container,
    style: {
      version: 8,
      glyphs: GLYPHS,
      sources: basemapSources(),
      layers: [
        { id: "background", type: "background", paint: { "background-color": "#f4f1ea" } },
        ...baseLayers()
          .filter((layer) => layer.type !== "background")
          .map((layer) => ({ ...layer, minzoom: Math.max(layer.minzoom ?? 0, BASE_ZOOM) })),
      ],
    },
    bounds: BOUNDS,
    fitBoundsOptions: { padding: 10 },
    attributionControl: { customAttribution: `Boundaries: ČÚZK (CC BY 4.0) · ${BASEMAP_ATTRIBUTION}`, compact: true },
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.addControl(new NavigationControl({ showCompass: false }));
  map.getCanvas().setAttribute("aria-label", t("measured.mapAria"));

  let rows = [];
  let stations = []; // the okres layer's stations, shown from STATION_ZOOM
  let byId = new Map();
  const zoomedIn = () => view.layer === "okresy" && stations.length > 0 && map.getZoom() >= STATION_ZOOM;
  // the rows on the map now: the okresy's, or zoomed in their stations
  const active = () => (zoomedIn() ? stations : rows);
  // part, shown, colour; layer "stations" or "okresy" with fill (okres → colour) and okres;
  // `err` ({byId: Map(station → model error | null), ramp}) colours the dots by a model's error
  let view = { part: "day", shown: [], colour: "temperature", layer: "stations", fill: null, okres: null };
  let loaded = false;
  const ready = new Promise((resolve) => map.on("load", resolve));
  const markers = new Map(); // id → {marker, el, canvas, temp, chips, chipBox, icon, onMap}
  const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "station-map-popup" });

  function popupFor(row) {
    const box = element("div");
    box.append(element("strong", row.name), element("div", describe(row, view.part)));
    popup.setLngLat([row.lon, row.lat]).setDOMContent(box).addTo(map);
  }

  // --- labels: the forecast map's markers (.wx-marker), for the stations --------------
  function markerFor(row) {
    let entry = markers.get(row.id);
    if (entry) return entry;
    const el = element("button", null, "wx-marker station-label");
    el.type = "button";
    // the station's name, shown when zoomed in (CSS: .measured-map.named)
    if (!row.okresCode) el.append(element("span", row.name, "wx-name"));
    const top = element("span", null, "wx-top");
    const canvas = iconCanvas("", 30);
    const temp = element("span", "", "wx-temp");
    top.append(canvas, temp);
    const chipBox = element("span", null, "wx-chips");
    const chips = {};
    for (const layer of ALL_LAYERS.filter((l) => l !== "temperature")) {
      const chip = element("span", null, `wx-chip ${layer}`);
      const text = element("span", "");
      chip.append(glyph(layer, 11), text);
      chipBox.append(chip);
      chips[layer] = { chip, text };
    }
    // the model's error at the station (error colouring): the dot's colour, readable under the label
    const errChip = element("span", null, "wx-err");
    errChip.hidden = true;
    el.append(top, chipBox, errChip);
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      const current = byId.get(row.id);
      if (current) onPick(current);
    });
    el.addEventListener("mouseenter", () => {
      const current = byId.get(row.id);
      if (current) popupFor(current);
    });
    el.addEventListener("mouseleave", () => popup.remove());
    const marker = new Marker({ element: el }).setLngLat([row.lon, row.lat]);
    entry = { marker, el, canvas, temp, chips, chipBox, errChip, icon: null, onMap: false };
    markers.set(row.id, entry);
    return entry;
  }

  function fill(entry, row) {
    const { part, shown } = view;
    const icon = iconName(row.symbol, part, row);
    if (icon !== entry.icon) {
      entry.icon = icon;
      const ctx = entry.canvas.getContext("2d");
      ctx.clearRect(0, 0, entry.canvas.width, entry.canvas.height);
      if (icon) drawIcon(ctx, icon, entry.canvas.width);
    }
    entry.canvas.hidden = !icon;
    const temperature = shown.includes("temperature") && valueFor(row, "temperature", part) != null;
    entry.temp.hidden = !temperature;
    entry.temp.textContent = temperature ? labelFor(row, "temperature", part) : "";
    let any = false;
    for (const [layer, { chip, text }] of Object.entries(entry.chips)) {
      chip.hidden = !shown.includes(layer) || valueFor(row, layer, part) == null;
      any ||= !chip.hidden;
      text.textContent = labelFor(row, layer, part);
    }
    entry.chipBox.hidden = !any;
    const e = view.err ? view.err.byId.get(row.id) ?? null : null;
    entry.errChip.hidden = e == null;
    if (e != null) {
      const fill = colorFor(e, view.err.ramp);
      entry.errChip.textContent = view.err.label(e);
      entry.errChip.style.background = fill;
      // dark text on the pale middle of the scale, white on the saturated ends
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(fill.slice(i, i + 2), 16));
      entry.errChip.style.color = 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#1d2329" : "#fff";
    }
    entry.el.setAttribute("aria-label", `${row.name}: ${describe(row, part)}`);
  }

  function declutter() {
    if (!loaded) return;
    const { clientWidth: width, clientHeight: height } = container;
    container.classList.toggle("named", map.getZoom() >= STATION_ZOOM);
    const ids = pickLabels(active(), {
      shown: view.shown,
      part: view.part,
      selected: view.okres,
      errors: view.err?.byId ?? null,
      project: (r) => map.project([r.lon, r.lat]),
      width,
      height,
    });
    for (const [id, entry] of markers) {
      if (!ids.has(id) && entry.onMap) {
        entry.marker.remove();
        entry.onMap = false;
      }
    }
    for (const id of ids) {
      const row = byId.get(id);
      const entry = markerFor(row);
      fill(entry, row);
      entry.el.classList.toggle("selected", id === view.okres);
      if (!entry.onMap) {
        entry.marker.addTo(map);
        entry.onMap = true;
      }
    }
  }

  // --- dots ---------------------------------------------------------------------------
  function features() {
    if (view.layer === "okresy" && !zoomedIn()) return EMPTY;
    const key = rampKey(view.colour, true);
    return {
      type: "FeatureCollection",
      features: active().map((r) => {
        // a station without an error (outside the stations with stored forecasts, or the model has no value) stays grey
        const value = view.err ? view.err.byId.get(r.id) ?? null : valueFor(r, view.colour, view.part);
        const ramp = view.err ? view.err.ramp : key;
        return {
          type: "Feature",
          geometry: { type: "Point", coordinates: [r.lon, r.lat] },
          properties: {
            id: r.id,
            color: value != null && RAMPS[ramp] ? colorFor(value, ramp) : GREY,
            has: value != null ? 1 : 0,
            main: r.kind === "main" ? 1 : 0,
          },
        };
      }),
    };
  }

  function stationAt(point) {
    const found = map.queryRenderedFeatures(
      [
        [point.x - HIT_PX, point.y - HIT_PX],
        [point.x + HIT_PX, point.y + HIT_PX],
      ],
      { layers: ["obs-dots"] },
    );
    let hit = null;
    let bestD = Infinity;
    for (const f of found) {
      const p = map.project(f.geometry.coordinates);
      const d = (p.x - point.x) ** 2 + (p.y - point.y) ** 2;
      if (d < bestD) {
        bestD = d;
        hit = byId.get(f.properties.id);
      }
    }
    return hit;
  }

  ready.then(() => {
    map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
    map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
    map.addSource("obs-dots", { type: "geojson", data: EMPTY });
    map.addLayer({
      id: "okresy-fill",
      type: "fill",
      source: "okresy",
      paint: { "fill-color": "#ececec", "fill-opacity": ["step", ["zoom"], 0.85, BASE_ZOOM, 0.45] },
    });
    map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
    map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.1 } });
    for (const layer of topLayers(document.documentElement.lang).filter((l) => l.id === "place-town" || l.id === "place-city")) {
      map.addLayer({ ...layer, minzoom: Math.max(layer.minzoom ?? 0, BASE_ZOOM) });
    }
    map.addLayer({
      id: "okres-selected",
      type: "line",
      source: "okresy",
      filter: ["==", ["get", "code"], ""],
      paint: { "line-color": "#1d2329", "line-width": 2.5 },
    });
    map.addLayer({
      id: "obs-dots",
      type: "circle",
      source: "obs-dots",
      layout: { "circle-sort-key": ["+", ["get", "has"], ["get", "main"]] },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["case", ["==", ["get", "has"], 1], 3.4, 2], 9, ["case", ["==", ["get", "has"], 1], 7, 4]],
        "circle-color": ["get", "color"],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 0.8,
      },
    });
    loaded = true;
    paint();
    const canvas = map.getCanvas();
    map.on("mousemove", (event) => {
      const row = stationAt(event.point);
      const okres = !row && view.layer === "okresy" && map.queryRenderedFeatures(event.point, { layers: ["okresy-fill"] }).length;
      canvas.style.cursor = row || okres ? "pointer" : "";
      if (row) popupFor(row);
      else popup.remove();
    });
    map.on("mouseout", () => popup.remove());
    map.on("click", (event) => {
      const row = stationAt(event.point);
      if (row) {
        onPick(row);
        return;
      }
      if (view.layer !== "okresy") return;
      const [okres] = map.queryRenderedFeatures(event.point, { layers: ["okresy-fill"] });
      if (okres) onOkres(okres.properties.code);
    });
    map.on("moveend", declutter);
    // crossing STATION_ZOOM on the okres layer swaps the okresy for their stations
    let wasIn = zoomedIn();
    map.on("zoomend", () => {
      if (zoomedIn() !== wasIn) {
        wasIn = zoomedIn();
        paint();
      }
    });
  });

  function paint() {
    map.getSource("obs-dots").setData(features());
    const pairs = view.layer === "okresy" && view.fill ? [...view.fill].flat() : [];
    map.setPaintProperty("okresy-fill", "fill-color", pairs.length ? ["match", ["get", "code"], ...pairs, NEUTRAL] : "#ececec");
    map.setFilter("okres-selected", ["==", ["get", "code"], view.layer === "okresy" ? view.okres ?? "" : ""]);
    declutter();
  }

  // the whole country stays in view while the map changes size, until someone moves it
  let keepFit = true;
  let lastRight = null;
  map.on("movestart", (event) => {
    if (event.originalEvent) keepFit = false;
  });
  new ResizeObserver(() => {
    map.resize();
    // not while the map is gliding beside a panel that just opened (that would cut it short)
    if (keepFit && !map.isMoving()) map.fitBounds(BOUNDS, { padding: { top: 10, bottom: 10, left: 10, right: lastRight ?? 10 }, duration: 0 });
    declutter();
  }).observe(container);

  return {
    /** The rows of a day and part (stations or okresy), and what to show: {part, shown,
     * colour, layer, fill, okres}; on the okres layer also its stations (zoomed in). */
    set(nextRows, nextView, nextStations = []) {
      rows = nextRows;
      stations = nextStations;
      byId = new Map([...stations, ...rows].map((r) => [r.id, r]));
      view = nextView;
      popup.remove();
      if (loaded) paint();
    },
    /** Fit Czechia beside an open okres panel on wide screens, and back when it closes
     * (as the forecast map does). */
    fitBeside(panel) {
      const right = window.innerWidth > 900 && panel && !panel.hidden ? panelRoom() : 10;
      if (right === lastRight) return;
      // someone moved the map themselves: leave it where they put it
      if (lastRight !== null && !keepFit) return;
      const first = lastRight === null;
      lastRight = right;
      keepFit = true;
      // after the layout settles (the panel may make the map taller), then glide as on the forecast map
      requestAnimationFrame(() => {
        map.resize();
        map.fitBounds(BOUNDS, { padding: { top: 10, bottom: 10, left: 10, right }, duration: first ? 0 : 400 });
      });
    },
    /** Make it fit its box again (after being hidden). */
    resize() {
      map.resize();
      if (keepFit) map.fitBounds(BOUNDS, { padding: { top: 10, bottom: 10, left: 10, right: lastRight ?? 10 }, duration: 0 });
      declutter();
    },
    ready,
    map,
  };
}
