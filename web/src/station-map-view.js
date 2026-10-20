// The station map of measured.html: okres and kraj boundaries (no third-party tiles)
// with every ČHMÚ station as a dot. Hover names it, a click (or Enter on the station in
// the middle, from the keyboard) picks it.
import { Map as MapLibreMap, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre's ES module build loads its worker from a separate file
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

import { panelRoom } from "./panel-room.js";
import { colorExpression, nearestStation, stationFeatures } from "./station-map.js";

setWorkerUrl(workerUrl);

// Czechia, with a little margin
const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
const EMPTY = { type: "FeatureCollection", features: [] };
const HIT_PX = 8; // a click this close to a dot picks it (small dots, fingers)
const KEY_PX = 40; // from the keyboard: the station this close to the middle

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * @param {object} options
 * @param {HTMLElement} options.container
 * @param {(key: string, params?: object) => string} options.t
 * @param {(station: object) => void} options.onPick
 * @param {(station: object) => string} options.describe one line under the name
 */
export function createStationMap({ container, t, onPick, describe, extraFor = null }) {
  const map = new MapLibreMap({
    container,
    style: {
      version: 8,
      sources: {},
      layers: [{ id: "background", type: "background", paint: { "background-color": "#f4f1ea" } }],
    },
    bounds: BOUNDS,
    fitBoundsOptions: { padding: 10 },
    attributionControl: { customAttribution: "Boundaries: ČÚZK (CC BY 4.0)", compact: true },
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.addControl(new NavigationControl({ showCompass: false }));
  // the compact attribution starts open and covers much of a small map: start it folded
  map.once("load", () => map.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show"));
  const canvas = map.getCanvas();
  canvas.setAttribute("aria-label", t("map.aria"));

  let all = []; // stations with coordinates
  let shown = []; // after the filter
  let byId = new Map();
  let selected = null;
  let colourBy = "kind";
  let errors = null; // station → a model's error, for colouring by error
  let errorRamp = "errTemp";
  let loaded = false;
  const ready = new Promise((resolve) => map.on("load", resolve));

  const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 8, className: "station-map-popup" });

  function popupFor(station, extra) {
    const box = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = station.name ?? station.id;
    box.append(name);
    for (const line of [describe(station), extra].filter(Boolean)) {
      const small = document.createElement("div");
      small.textContent = line;
      box.append(small);
    }
    popup.setLngLat([station.lon, station.lat]).setDOMContent(box).addTo(map);
  }

  /** The shown station nearest to a screen point, if within `px`. */
  function stationAt(point, px) {
    const features = map.queryRenderedFeatures(
      [
        [point.x - px, point.y - px],
        [point.x + px, point.y + px],
      ],
      { layers: ["stations"] },
    );
    let best = null;
    let bestD = Infinity;
    for (const f of features) {
      const p = map.project(f.geometry.coordinates);
      const d = (p.x - point.x) ** 2 + (p.y - point.y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = byId.get(f.properties.id);
      }
    }
    return best;
  }

  function paint() {
    const color = colorExpression(colourBy, errorRamp);
    const automatic = ["==", ["get", "automatic"], 1];
    map.setPaintProperty("stations", "circle-color", ["case", automatic, color, "#ffffff"]);
    map.setPaintProperty("stations", "circle-stroke-color", ["case", automatic, "#ffffff", color]);
  }

  function setSelectedData() {
    const s = selected && byId.get(selected);
    map.getSource("selected")?.setData(s ? stationFeatures([s]) : EMPTY);
  }

  ready.then(() => {
    map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
    map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
    map.addSource("stations", { type: "geojson", data: stationFeatures(shown, errors) });
    map.addSource("selected", { type: "geojson", data: EMPTY });
    map.addLayer({ id: "okresy-fill", type: "fill", source: "okresy", paint: { "fill-color": "#ececec", "fill-opacity": 0.85 } });
    map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
    map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.1 } });
    map.addLayer({
      id: "stations",
      type: "circle",
      source: "stations",
      layout: {
        // main stations on top, then automatic ones
        "circle-sort-key": ["+", ["get", "automatic"], ["case", ["==", ["get", "kind"], "main"], 2, 0]],
      },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2.6, 7, 4, 10, 6.5],
        "circle-stroke-width": ["case", ["==", ["get", "automatic"], 1], 0.7, 1.5],
      },
    });
    map.addLayer({
      id: "selected",
      type: "circle",
      source: "selected",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 7, 10, 11],
        "circle-color": "rgba(0, 0, 0, 0)",
        "circle-stroke-color": "#1d2329",
        "circle-stroke-width": 2.5,
      },
    });
    loaded = true;
    paint();
    setSelectedData();

    map.on("mousemove", (event) => {
      const station = stationAt(event.point, HIT_PX);
      canvas.style.cursor = station ? "pointer" : "";
      if (station) popupFor(station, extraFor?.(station));
      else popup.remove();
    });
    map.on("mouseout", () => popup.remove());
    map.on("click", (event) => {
      const station = stationAt(event.point, HIT_PX);
      if (station) onPick(station);
    });
    map.on("moveend", keyboardCandidate);
  });

  // keyboard: while the map has keyboard focus, a cross marks the middle and the
  // station nearest to it is named; Enter opens it
  let candidate = null;
  function keyboardCandidate() {
    if (!loaded || !canvas.matches(":focus-visible")) return;
    const centre = map.getCenter();
    const station = nearestStation(shown, [centre.lng, centre.lat]);
    const middle = map.project(centre);
    const p = station && map.project([station.lon, station.lat]);
    candidate = p && (p.x - middle.x) ** 2 + (p.y - middle.y) ** 2 <= KEY_PX ** 2 ? station : null;
    if (candidate) popupFor(candidate, t("map.enter"));
    else popup.remove();
  }
  canvas.addEventListener("focus", () => {
    if (canvas.matches(":focus-visible")) container.classList.add("keyboard");
    keyboardCandidate();
  });
  canvas.addEventListener("blur", () => {
    container.classList.remove("keyboard");
    candidate = null;
    popup.remove();
  });
  canvas.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && candidate) {
      event.preventDefault();
      onPick(candidate);
    }
  });

  // the whole country stays in view while the map changes size, until someone moves it
  let keepFit = false;
  let right = 10; // room kept on the right for an open panel
  const fit = (duration = 0) => map.fitBounds(BOUNDS, { padding: { top: 10, bottom: 10, left: 10, right }, duration });
  map.on("movestart", (event) => {
    if (event.originalEvent) keepFit = false;
  });
  new ResizeObserver(() => {
    map.resize();
    if (keepFit) fit();
  }).observe(container);

  return {
    /** All stations (for the selection) and the ones shown (after a filter). */
    setStations(stations, visible = stations) {
      all = stations;
      shown = visible;
      byId = new Map(all.map((s) => [s.id, s]));
      if (loaded) {
        map.getSource("stations").setData(stationFeatures(shown, errors));
        setSelectedData();
      }
    },
    /** "kind", "elevation" or "error" (with `errors`, station → error, on the palette ramp `ramp`). */
    setColour(by, { errors: next = null, ramp = "errTemp" } = {}) {
      colourBy = by;
      errors = next;
      errorRamp = ramp;
      if (loaded) {
        map.getSource("stations").setData(stationFeatures(shown, errors));
        paint();
      }
    },
    /** Highlight a station (null: none) and bring it into view (`move: false`: only highlight). */
    select(id, { animate = true, move = true } = {}) {
      selected = id;
      if (id && move) keepFit = false;
      if (loaded) setSelectedData();
      const s = id && byId.get(id);
      if (!s || !move) return;
      map.resize(); // the map's size in the new layout, so the station ends up in the middle
      const zoom = Math.max(map.getZoom(), 7.5);
      const visible = container.offsetParent !== null;
      map.easeTo({ center: [s.lon, s.lat], zoom, duration: animate && visible && !reducedMotion() ? 900 : 0 });
    },
    /** The whole country, kept in view on resizes until someone moves the map. */
    fitAll() {
      map.resize();
      fit();
      keepFit = true;
    },
    /** Room for an open panel on wide screens: the whole country glides beside it (only while
     * it is in view; a map someone has moved or zoomed stays where it is). */
    fitBeside(open) {
      const next = open && window.innerWidth > 900 ? panelRoom() : 10;
      if (next === right) return;
      right = next;
      if (!keepFit) return;
      requestAnimationFrame(() => {
        map.resize();
        fit(400);
      });
    },
    ready,
    map,
  };
}
