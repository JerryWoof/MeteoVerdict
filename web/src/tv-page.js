import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { iconCanvas } from "./icons.js";
import { setUpLanguage } from "./i18n.js";
import {
  LAYERS, PARTS, RAMPS, colorFor, currentPart, dayLabel, displayName, fillExpression,
  iconName, labelFor, parseOutlook, placeMarkers, pointFeatures, rowFor, sequence, summary,
  today,
} from "./tv.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();
const language = document.documentElement.lang;

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
const MARKER = { width: 64, height: 50 };

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
// registered at once: the map may finish loading while the forecast is still on its way
const mapLoaded = new Promise((resolve) => map.on("load", resolve));

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

const fmt = (v, digits = 0) => (v == null ? "–" : v.toFixed(digits));
const percent = (p) => (p == null ? "–" : `${Math.round(p * 100)} %`);
const symbolText = (symbol) => (symbol ? t(`symbol.${symbol}`) : "");

// --- state, kept in the URL: #day/part/layer/okres ---------------------------------
const state = { day: null, part: null, layer: "temperature", okres: null, playing: null };

function readHash(outlook) {
  const [day, part, layer, okres] = window.location.hash.slice(1).split("/");
  const now = Date.now();
  const first = outlook.days.includes(today(now)) ? today(now) : outlook.days[0];
  state.day = outlook.days.includes(day) ? day : first;
  const nowPart = currentPart(now);
  state.part = PARTS.includes(part) ? part : state.day === today(now) ? nowPart : "afternoon";
  state.layer = LAYERS.includes(layer) ? layer : "temperature";
  state.okres = outlook.okresy.some((o) => o.code === okres) ? okres : null;
}

function writeHash() {
  const parts = [state.day, state.part, state.layer, state.okres ?? ""];
  window.history.replaceState(null, "", `#${parts.join("/").replace(/\/$/, "")}`);
}

// --- ribbon -----------------------------------------------------------------------
function tabs(id, items, current, onPick) {
  const box = document.getElementById(id);
  box.replaceChildren(
    ...items.map(([value, label]) => {
      const button = element("button", label);
      button.type = "button";
      button.setAttribute("aria-pressed", String(value === current));
      button.addEventListener("click", () => onPick(value));
      return button;
    }),
  );
}

function dayText(day) {
  const label = dayLabel(day, today(Date.now()), language);
  return label.key ? t(label.key) : label.text;
}

function renderRibbon(outlook) {
  tabs("days", outlook.days.map((d) => [d, dayText(d)]), state.day, (d) => update({ day: d }));
  tabs("parts", PARTS.map((p) => [p, t(`part.${p}`)]), state.part, (p) => update({ part: p }));
  tabs("layers", LAYERS.map((l) => [l, t(`layer.${l}`)]), state.layer, (l) => update({ layer: l }));
  const play = document.getElementById("play");
  play.textContent = state.playing ? t("tv.pause") : t("tv.play");
  play.setAttribute("aria-pressed", String(Boolean(state.playing)));
}

// --- map --------------------------------------------------------------------------
const markers = new Map(); // okres → {marker, element, lngLat}

function markerElement(feature) {
  const box = element("button", null, "wx-marker");
  box.type = "button";
  box.title = displayName(feature.properties.name);
  box.append(iconCanvas(feature.properties.icon, 30), element("span", feature.properties.label));
  box.addEventListener("click", (event) => {
    event.stopPropagation();
    update({ okres: feature.properties.code });
  });
  return box;
}

function renderMarkers(outlook) {
  for (const { marker } of markers.values()) marker.remove();
  markers.clear();
  for (const feature of pointFeatures(outlook, state.day, state.part, state.layer).features) {
    const el = markerElement(feature);
    const marker = new Marker({ element: el }).setLngLat(feature.geometry.coordinates).addTo(map);
    markers.set(feature.properties.code, { marker, el, lngLat: feature.geometry.coordinates });
  }
  declutter();
}

function declutter() {
  const boxes = [...markers].map(([code, m]) => {
    const p = map.project(m.lngLat);
    return { code, x: p.x, y: p.y };
  });
  const shown = placeMarkers(boxes, MARKER.width, MARKER.height);
  for (const [code, m] of markers) {
    m.el.hidden = !shown.has(code) && code !== state.okres;
    m.el.classList.toggle("selected", code === state.okres);
  }
}

function renderScale() {
  const ramp = RAMPS[state.layer];
  const [low, high] = [ramp[0][0], ramp.at(-1)[0]];
  const stops = ramp.map(([v]) => `${colorFor(v, state.layer)} ${((v - low) / (high - low)) * 100}%`);
  const bar = element("div", null, "bar");
  bar.style.background = `linear-gradient(to right, ${stops.join(", ")})`;
  const show = (v) =>
    state.layer === "temperature" ? `${v}°` : state.layer === "precipitation" ? `${v * 100} %` : state.layer === "wind" ? `${v} m/s` : `${v} %`;
  document.getElementById("scale").replaceChildren(
    element("div", t(`scale.${state.layer}`), "scale-title"),
    bar,
    element("div", `${show(low)} … ${show(high)}`, "scale-ends"),
  );
}

function renderHeadline(outlook) {
  const s = summary(outlook, state.day, state.part);
  const box = document.getElementById("headline");
  if (!s) {
    box.replaceChildren(element("p", t("tv.noPart")));
    return;
  }
  const warm = element("p", t("tv.warmest", { okres: displayName(s.warmest.name), value: fmt(s.warmest.value) }));
  const cold = element("p", t("tv.coldest", { okres: displayName(s.coldest.name), value: fmt(s.coldest.value) }));
  box.replaceChildren(
    element("h2", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`),
    // at night the coldest place comes first
    ...(state.part === "night" ? [cold, warm] : [warm, cold]),
    element("p", t("tv.rainy", { n: s.rainy, of: s.okresy })),
  );
}

// --- okres panel ------------------------------------------------------------------
function partCell(row, part) {
  const cell = element("div", null, "part");
  cell.append(
    element("span", t(`part.${part}`), "part-name"),
    iconCanvas(row ? iconName(row.symbol, part) : "", 34, symbolText(row?.symbol)),
    element("strong", row ? labelFor(row, "temperature", part) : "–"),
    element("span", row ? percent(row.rain_probability) : "", "rain"),
  );
  return cell;
}

function renderPanel(outlook) {
  const panel = document.getElementById("okres-panel");
  if (!state.okres) {
    panel.replaceChildren();
    return;
  }
  const info = outlook.okresy.find((o) => o.code === state.okres);
  const now = rowFor(outlook, state.okres, state.day, state.part);
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("chart.close"));
  close.addEventListener("click", () => update({ okres: null }));
  const big = element("div", null, "now");
  big.append(
    iconCanvas(now ? iconName(now.symbol, state.part) : "", 64, symbolText(now?.symbol)),
    element("div", now ? labelFor(now, "temperature", state.part) : "–", "big-temp"),
  );
  const facts = element("ul", null, "facts");
  if (now) {
    for (const text of [
      symbolText(now.symbol),
      t("tv.range", { low: fmt(now.tmin), high: fmt(now.tmax) }),
      t("tv.rain", { chance: percent(now.rain_probability), amount: fmt(now.precipitation, 1) }),
      t("tv.wind", { value: fmt(now.wind) }),
      t("tv.cloud", { value: fmt(now.cloud) }),
    ]) {
      facts.append(element("li", text));
    }
  }
  const strip = element("div", null, "strip");
  strip.append(...PARTS.slice(0, 4).map((p) => partCell(rowFor(outlook, state.okres, state.day, p), p)));
  const week = element("table", null, "week");
  for (const day of outlook.days) {
    const row = rowFor(outlook, state.okres, day, "day");
    const tr = element("tr");
    if (day === state.day) tr.className = "current";
    tr.addEventListener("click", () => update({ day }));
    const iconCell = element("td");
    iconCell.append(iconCanvas(row ? iconName(row.symbol, "day") : "", 26, symbolText(row?.symbol)));
    tr.append(
      element("td", dayText(day)),
      iconCell,
      element("td", row ? `${fmt(row.tmax)}° / ${fmt(row.tmin)}°` : "–", "num"),
      element("td", row ? percent(row.rain_probability) : "", "num rain"),
      element("td", row ? `${fmt(row.wind)} m/s` : "", "num"),
    );
    week.append(tr);
  }
  const detail = element("a", t("tv.detail"));
  detail.href = `forecast.html#${state.okres}`;
  panel.replaceChildren(
    close,
    element("h2", displayName(info?.name ?? state.okres)),
    element("p", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`, "when"),
    big,
    facts,
    strip,
    week,
    detail,
  );
}

// --- update loop ------------------------------------------------------------------
let outlook = null;

let panelOpen = false;

/** Fit Czechia beside the okres panel on wide screens, and back when it closes. */
function fitBesidePanel() {
  const open = Boolean(state.okres) && window.innerWidth > 700;
  if (open === panelOpen) return;
  panelOpen = open;
  const right = open ? document.getElementById("okres-panel").offsetWidth + 70 : 20;
  map.fitBounds(BOUNDS, { padding: { top: 20, bottom: 20, left: 20, right }, duration: 400 });
}

function update(change = {}) {
  if (change.day || change.part || change.layer || "okres" in change) stopIfManual(change);
  Object.assign(state, change);
  writeHash();
  renderRibbon(outlook);
  if (map.getLayer("okresy-fill")) {
    map.setPaintProperty("okresy-fill", "fill-color", fillExpression(outlook, state.day, state.part, state.layer));
    map.setFilter("okres-selected", ["==", ["get", "code"], state.okres ?? ""]);
  }
  renderMarkers(outlook);
  renderScale();
  renderHeadline(outlook);
  renderPanel(outlook);
  fitBesidePanel();
}

function stopIfManual(change) {
  if (state.playing && !change.fromPlay) {
    clearInterval(state.playing);
    state.playing = null;
  }
  delete change.fromPlay;
}

function togglePlay() {
  if (state.playing) {
    clearInterval(state.playing);
    state.playing = null;
    renderRibbon(outlook);
    return;
  }
  const steps = sequence(outlook, state.day, state.part);
  let i = 0;
  state.playing = setInterval(() => {
    i = (i + 1) % steps.length;
    update({ ...steps[i], fromPlay: true });
  }, 1600);
  renderRibbon(outlook);
}

async function main() {
  outlook = parseOutlook(await getJson("data/scores/outlook.json"));
  const status = document.getElementById("status");
  if (outlook.okresy.length === 0) {
    status.textContent = t("tv.none");
    return;
  }
  const generated = new Date(outlook.generated);
  status.textContent = t("tv.updated", {
    time: new Intl.DateTimeFormat(language, { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague" }).format(generated),
  });
  readHash(outlook);
  document.getElementById("play").addEventListener("click", togglePlay);
  await mapLoaded;
  addLayers();
  update();
}

function addLayers() {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({ id: "okresy-fill", type: "fill", source: "okresy", paint: { "fill-color": "#ececec", "fill-opacity": 0.85 } });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.2 } });
  map.addLayer({
    id: "okres-selected",
    type: "line",
    source: "okresy",
    filter: ["==", ["get", "code"], ""],
    paint: { "line-color": "#1d2329", "line-width": 2.5 },
  });
  map.on("click", "okresy-fill", (event) => update({ okres: event.features[0].properties.code }));
  map.on("mouseenter", "okresy-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "okresy-fill", () => (map.getCanvas().style.cursor = ""));
  map.on("moveend", declutter);
}

main();
