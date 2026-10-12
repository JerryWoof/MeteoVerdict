import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { glyph, iconCanvas } from "./icons.js";
import { setUpLanguage } from "./i18n.js";
import {
  COLOURS, LAYERS, PARTS, RAMPS, colorFor, currentPart, dayLabel, displayName, fillExpression,
  iconName, labelFor, parseOutlook, parseView, placeMarkers, pointFeatures, rowFor, sequence,
  summary, today, viewHash,
} from "./tv.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();
const language = document.documentElement.lang;

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
// hours of each part of the day, shown under its name
const HOURS = { night: "0–6", morning: "6–12", afternoon: "12–18", evening: "18–24", day: "0–24" };

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

// --- state, kept in the URL (tv.js parseView / viewHash) ----------------------------
let state = { day: null, part: null, colour: "temperature", shown: [], okres: null };
let playing = null;

function dayText(day) {
  const label = dayLabel(day, today(Date.now()), language);
  return label.key ? t(label.key) : label.text;
}

function dateText(day) {
  return new Intl.DateTimeFormat(language, { weekday: "short", day: "numeric", month: "numeric", timeZone: "UTC" }).format(
    Date.parse(`${day}T12:00Z`),
  );
}

// --- when: days and parts of the day (above the map) --------------------------------
function renderWhen(outlook) {
  const days = document.getElementById("days");
  days.setAttribute("aria-label", t("tv.day"));
  days.replaceChildren(
    ...outlook.days.map((day) => {
      const button = element("button", null, "daytab");
      button.type = "button";
      button.setAttribute("aria-pressed", String(day === state.day));
      const label = dayLabel(day, today(Date.now()), language);
      button.append(element("strong", label.key ? t(label.key) : label.text));
      if (label.key) button.append(element("small", dateText(day)));
      button.addEventListener("click", () => update({ day }));
      return button;
    }),
  );
  const parts = document.getElementById("parts");
  parts.setAttribute("aria-label", t("tv.part"));
  parts.replaceChildren(
    ...PARTS.map((part) => {
      const button = element("button", null);
      button.type = "button";
      button.setAttribute("aria-pressed", String(part === state.part));
      button.append(element("span", t(`part.${part}`)), element("small", HOURS[part]));
      button.addEventListener("click", () => update({ part }));
      return button;
    }),
  );
  const play = document.getElementById("play");
  play.textContent = playing ? t("tv.pause") : t("tv.play");
  play.setAttribute("aria-pressed", String(Boolean(playing)));
}

// --- what: values at the markers and the map colour (box on the map) ------------------
function renderShow() {
  const values = document.getElementById("values");
  values.replaceChildren(
    ...LAYERS.map((layer) => {
      const label = element("label", null, "check");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = state.shown.includes(layer);
      box.addEventListener("change", () => {
        const shown = box.checked ? [...state.shown, layer] : state.shown.filter((l) => l !== layer);
        update({ shown: LAYERS.filter((l) => shown.includes(l)) });
      });
      label.append(box, glyph(layer), element("span", t(`layer.${layer}`)));
      return label;
    }),
  );
  const colours = document.getElementById("colours");
  colours.replaceChildren(
    ...COLOURS.map((colour) => {
      const label = element("label", null, "check");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "colour";
      radio.checked = colour === state.colour;
      radio.addEventListener("change", () => update({ colour }));
      label.append(radio, element("span", t(colour === "none" ? "tv.noColour" : `layer.${colour}`)));
      return label;
    }),
  );
  renderScale();
}

function renderScale() {
  const box = document.getElementById("scale");
  const ramp = RAMPS[state.colour];
  if (!ramp) {
    box.replaceChildren();
    return;
  }
  const [low, high] = [ramp[0][0], ramp.at(-1)[0]];
  const stops = ramp.map(([v]) => `${colorFor(v, state.colour)} ${((v - low) / (high - low)) * 100}%`);
  const bar = element("div", null, "bar");
  bar.style.background = `linear-gradient(to right, ${stops.join(", ")})`;
  const show = (v) =>
    ({ temperature: `${v}°`, precipitation: `${v * 100} %`, wind: `${v} m/s`, cloud: `${v} %` })[state.colour];
  box.replaceChildren(
    element("div", t(`scale.${state.colour}`), "scale-title"),
    bar,
    element("div", `${show(low)} … ${show(high)}`, "scale-ends"),
  );
}

// --- markers ----------------------------------------------------------------------
const markers = new Map(); // okres → {marker, el, lngLat}

function markerElement(feature) {
  const box = element("button", null, "wx-marker");
  box.type = "button";
  box.title = displayName(feature.properties.name);
  const top = element("span", null, "wx-top");
  top.append(iconCanvas(feature.properties.icon, 30));
  const chips = element("span", null, "wx-chips");
  for (const { layer, text } of feature.properties.values) {
    if (layer === "temperature") {
      top.append(element("span", text, "wx-temp"));
    } else {
      const chip = element("span", null, `wx-chip ${layer}`);
      chip.append(glyph(layer, 11), element("span", text));
      chips.append(chip);
    }
  }
  box.append(top);
  if (chips.childElementCount) box.append(chips);
  box.addEventListener("click", (event) => {
    event.stopPropagation();
    update({ okres: feature.properties.code });
  });
  return box;
}

function renderMarkers(outlook) {
  for (const { marker } of markers.values()) marker.remove();
  markers.clear();
  for (const feature of pointFeatures(outlook, state.day, state.part, state.shown).features) {
    const el = markerElement(feature);
    const marker = new Marker({ element: el }).setLngLat(feature.geometry.coordinates).addTo(map);
    markers.set(feature.properties.code, { marker, el, lngLat: feature.geometry.coordinates });
  }
  declutter();
}

function declutter() {
  const boxes = [...markers].map(([code, m]) => {
    m.el.hidden = false;
    const p = map.project(m.lngLat);
    return { code, x: p.x, y: p.y, w: m.el.offsetWidth, h: m.el.offsetHeight };
  });
  const shown = placeMarkers(boxes, 4, state.okres);
  for (const [code, m] of markers) {
    m.el.hidden = !shown.has(code);
    m.el.classList.toggle("selected", code === state.okres);
  }
}

// --- headline: follows the values shown --------------------------------------------
function renderHeadline(outlook) {
  const s = summary(outlook, state.day, state.part);
  const box = document.getElementById("headline");
  if (!s) {
    box.replaceChildren(element("p", t("tv.noPart")));
    return;
  }
  const line = (layer, text) => {
    const p = element("p", null, "line");
    p.append(glyph(layer), element("span", text));
    return p;
  };
  const lines = [];
  const shown = (l) => state.shown.includes(l) || state.colour === l;
  // temperature also when nothing else is chosen
  if (shown("temperature") || !LAYERS.some(shown)) {
    const warm = line("temperature", t("tv.warmest", { okres: displayName(s.warmest.name), value: fmt(s.warmest.value) }));
    const cold = line("temperature", t("tv.coldest", { okres: displayName(s.coldest.name), value: fmt(s.coldest.value) }));
    // at night the coldest place comes first
    lines.push(...(state.part === "night" ? [cold, warm] : [warm, cold]));
  }
  if (shown("precipitation")) lines.push(line("precipitation", t("tv.rainy", { n: s.rainy, of: s.okresy })));
  if (shown("wind")) lines.push(line("wind", t("tv.windiest", { okres: displayName(s.windiest.name), value: fmt(s.windiest.value) })));
  if (shown("cloud")) lines.push(line("cloud", t("tv.clearIn", { n: s.clear, of: s.okresy })));
  box.replaceChildren(element("h2", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`), ...lines);
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
let padding = null;

/** Fit Czechia beside the okres panel on wide screens, and back when it closes. */
function fitView() {
  const right = window.innerWidth > 900 && state.okres ? document.getElementById("okres-panel").offsetWidth + 70 : 20;
  if (padding && padding.right === right) return;
  const first = padding === null;
  padding = { top: 20, bottom: 20, left: 20, right };
  map.fitBounds(BOUNDS, { padding, duration: first ? 0 : 400 });
}

function update(change = {}, fromPlay = false) {
  if (playing && !fromPlay) {
    clearInterval(playing);
    playing = null;
  }
  state = { ...state, ...change };
  window.history.replaceState(null, "", viewHash(state));
  renderWhen(outlook);
  renderShow();
  map.setPaintProperty("okresy-fill", "fill-color", fillExpression(outlook, state.day, state.part, state.colour));
  map.setFilter("okres-selected", ["==", ["get", "code"], state.okres ?? ""]);
  renderMarkers(outlook);
  renderHeadline(outlook);
  renderPanel(outlook);
  fitView();
}

function togglePlay() {
  if (playing) {
    clearInterval(playing);
    playing = null;
    renderWhen(outlook);
    return;
  }
  const steps = sequence(outlook, state.day, state.part);
  let i = 0;
  playing = setInterval(() => {
    i = (i + 1) % steps.length;
    update(steps[i], true);
  }, 1600);
  renderWhen(outlook);
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

async function main() {
  outlook = parseOutlook(await getJson("data/scores/outlook.json"));
  const status = document.getElementById("status");
  if (outlook.okresy.length === 0) {
    status.textContent = t("tv.none");
    return;
  }
  status.textContent = t("tv.updated", {
    time: new Intl.DateTimeFormat(language, { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague" }).format(
      new Date(outlook.generated),
    ),
  });
  const now = Date.now();
  const first = outlook.days.includes(today(now)) ? today(now) : outlook.days[0];
  state = parseView(window.location.hash, outlook, {
    day: first,
    part: first === today(now) ? currentPart(now) : "afternoon",
  });
  // phones: the box starts folded so the map stays visible
  const show = document.getElementById("show");
  if (window.innerWidth <= 700) show.open = false;
  document.getElementById("play").addEventListener("click", togglePlay);
  await mapLoaded;
  addLayers();
  update();
}

main();
