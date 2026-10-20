// The measured-weather map of measured.html's Weather tab: okres and kraj boundaries (zoomed
// in over the radar page's base map), the okresy coloured by the mean of their stations, and
// the forecast map's markers (symbol, temperature, value chips), one per okres that fits
// without overlapping (measured.js pickLabels), as the forecast map did for the past days;
// a click on an okres opens its panel. No single stations are drawn here.
import { Map as MapLibreMap, Marker, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

import { drawIcon, glyph, iconCanvas } from "./icons.js";
import { pickLabels } from "./measured.js";
import { NEUTRAL } from "./palette.js";
import { ALL_LAYERS, iconName, labelFor, valueFor } from "./tv.js";
import { panelRoom } from "./panel-room.js";
import { BASEMAP_ATTRIBUTION, GLYPHS, baseLayers, basemapSources, topLayers } from "./radar-basemap.js";

setWorkerUrl(workerUrl);

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
// zoomed in, the radar page's base map (relief, water, rivers, main roads, town names)
// under the okres colours, which turn see-through, as on the forecast map
const BASE_ZOOM = 7.5;

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
 * @param {(row: object) => void} options.onPick an okres's row (label) was clicked
 * @param {(row: object, part: string) => string} options.describe its values in one line
 */
export function createMeasuredMap({ container, t, onPick, describe }) {
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
  // the compact attribution starts open and covers much of a small map: start it folded
  map.once("load", () => map.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show"));

  let rows = [];
  let byId = new Map();
  // part, shown, colour, fill (okres → colour) and the open okres
  let view = { part: "day", shown: [], colour: "temperature", fill: null, okres: null };
  let loaded = false;
  const ready = new Promise((resolve) => map.on("load", resolve));
  const markers = new Map(); // id → {marker, el, canvas, temp, chips, chipBox, icon, onMap}
  const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "station-map-popup" });

  function popupFor(row) {
    const box = element("div");
    box.append(element("strong", row.name), element("div", describe(row, view.part)));
    popup.setLngLat([row.lon, row.lat]).setDOMContent(box).addTo(map);
  }

  // --- labels: the forecast map's markers (.wx-marker), for the okresy ---------------
  function markerFor(row) {
    let entry = markers.get(row.id);
    if (entry) return entry;
    const el = element("button", null, "wx-marker station-label");
    el.type = "button";
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
    el.append(top, chipBox);
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
    entry = { marker, el, canvas, temp, chips, chipBox, icon: null, onMap: false };
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
    entry.el.setAttribute("aria-label", `${row.name}: ${describe(row, part)}`);
  }

  function declutter() {
    if (!loaded) return;
    const { clientWidth: width, clientHeight: height } = container;
    const ids = pickLabels(rows, {
      shown: view.shown,
      part: view.part,
      selected: view.okres,
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

  ready.then(() => {
    map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
    map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
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
    loaded = true;
    paint();
    const canvas = map.getCanvas();
    map.on("mousemove", (event) => {
      const okres = map.queryRenderedFeatures(event.point, { layers: ["okresy-fill"] }).length;
      canvas.style.cursor = okres ? "pointer" : "";
    });
    map.on("click", (event) => {
      const [okres] = map.queryRenderedFeatures(event.point, { layers: ["okresy-fill"] });
      if (okres) onPick({ okresCode: okres.properties.code });
    });
    map.on("moveend", declutter);
  });

  function paint() {
    const pairs = view.fill ? [...view.fill].flat() : [];
    map.setPaintProperty("okresy-fill", "fill-color", pairs.length ? ["match", ["get", "code"], ...pairs, NEUTRAL] : "#ececec");
    map.setFilter("okres-selected", ["==", ["get", "code"], view.okres ?? ""]);
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
    /** The okresy's rows of a day and part, and what to show: {part, shown, colour, fill, okres}. */
    set(nextRows, nextView) {
      rows = nextRows;
      byId = new Map(rows.map((r) => [r.id, r]));
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
