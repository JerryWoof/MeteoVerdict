import { Map as MapLibreMap, Marker, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { setUpLanguage } from "./i18n.js";
import { placeSearch } from "./place-search.js";
import { placeLabel, placesLoader } from "./places.js";
import placesUrl from "./data/obce.json?url";
import { colorFor, renderScale } from "./palette.js";
import { keepRoomForPanels, userMoved } from "./panel-room.js";
import { BASEMAP_ATTRIBUTION, GLYPHS, baseLayers, basemapSources, topLayers } from "./radar-basemap.js";
import {
  TEMP100M_INDEX, TEMP100M_JSON, nearestPlaceOf, parseTemp100m, parseTemp100mIndex, temp100mDefaultIndex,
  temp100mFormat, temp100mGradient, temp100mLoader, temp100mSlot, temp100mSlotText,
} from "./ai-temp100m.js";
import {
  HEAT_INDEX, heatBlend, heatColourLut, heatCompose, heatDayMarks, heatNearestHour, heatSeriesAt, heatTimeAt, heatTimeText,
  heatValueAt, loadHeatModel, parseHeatIndex,
} from "./ai-heat.js";

// The AI heatmap tab: MeteoVerdict AI's 100 m temperature over the radar page's base map,
// a time control above it, and a click's panel with the temperature at that place at every time.
// With the hourly map (data/scores/ai/fc/heat/) the time control is a slider in half hours and
// the panel has an hourly chart; without it the page shows the day-part maps (or the one old image).

setWorkerUrl(workerUrl);
const t = setUpLanguage();
const language = document.documentElement.lang === "cs" ? "cs" : "en";
const $ = (id) => document.getElementById(id);

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
// a place within this distance of an obec's centre is called by its name, farther: "near ..."
const AT_KM = 2.5;

/** 1: the hourly picture has every pixel of the published image; 2: every second one in each direction, when the graphics card's textures are too small for the whole image. */
function pictureShrink(width) {
  try {
    const gl = document.createElement("canvas").getContext("webgl");
    return gl && gl.getParameter(gl.MAX_TEXTURE_SIZE) >= width ? 1 : 2;
  } catch {
    return 2;
  }
}

const element = (tag, text, className) => {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
};

async function fetchJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

let slots = []; // [{ day, part, time }] in time order
let selected = 0;
let loader = null;
let source = null; // { index } or { single }
let heat = null; // the hourly map: { index, model, lut, shrink } once its images are loaded
let heatIndex = null; // its index.json, parsed
let step = 0; // the hourly slider's position, in half hours
let unit = "°C";
let map = null;
let point = null; // { lng, lat, name }
let marker = null;
let tip = null;
let current = null; // the loaded map of the selected time
let shownToken = 0;
const loadPlaces = placesLoader(placesUrl);

const partName = (part) => t(`part.${part}`).toLowerCase();
const slotLabel = (slot) => temp100mSlotText(slot.time, language, partName(slot.part));

function makeMap() {
  const m = new MapLibreMap({
    container: "map",
    style: { version: 8, glyphs: GLYPHS, sources: basemapSources(), layers: baseLayers() },
    bounds: BOUNDS,
    fitBoundsOptions: { padding: 20 },
    attributionControl: { compact: true, customAttribution: `Boundaries: ČÚZK (CC BY 4.0) · ${BASEMAP_ATTRIBUTION}` },
  });
  // the credits start folded (their open box would cover a phone's small map)
  m.once("load", () => m.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show"));
  m.addControl(new NavigationControl({ showCompass: false }));
  // the country fills the map until someone moves it (the frame's size settles after the first draw)
  const moved = userMoved(m);
  new ResizeObserver(() => {
    m.resize();
    if (!moved()) m.fitBounds(BOUNDS, { padding: 20, animate: false });
  }).observe(m.getContainer());
  keepRoomForPanels($("heat-wrap"), m.getContainer(), [$("heat-panel")]);
  return m;
}

function addLayers() {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-opacity": 0.7, "line-width": 0.5 } });
  for (const layer of topLayers(language)) map.addLayer(layer);
  map.on("click", (event) => setPoint(event.lngLat.lng, event.lngLat.lat));
  map.on("mousemove", showTip);
  map.getCanvas().addEventListener("mouseleave", () => tip?.remove());
}

/** The hourly map's picture at the slider's time (the latest request wins). */
let composeFrame = 0;
function showHeat() {
  cancelAnimationFrame(composeFrame);
  composeFrame = requestAnimationFrame(() => {
    if (!heat || !map) return;
    const { data, width, height } = heatCompose(heat.model, step / 2, heat.lut, heat.shrink);
    const image = new ImageData(data, width, height);
    if (!map.getSource("heat")) map.addSource("heat", { type: "image", coordinates: heat.index.coordinates });
    map.getSource("heat").updateImage({ image });
    if (!map.getLayer("heat")) {
      map.addLayer({ id: "heat", type: "raster", source: "heat", paint: { "raster-opacity": 0.8, "raster-fade-duration": 0 } }, "okresy-line");
    }
  });
}

/** The selected time's image over the base map (below the borders and labels). */
async function showImage() {
  if (heatIndex) return showHeat();
  const token = ++shownToken;
  const slot = slots[selected];
  const loaded = await loader.load(slot.day, slot.part);
  if (token !== shownToken) return;
  const image = loaded ? await loaded.image() : null;
  if (token !== shownToken) return;
  current = loaded;
  if (image) {
    if (!map.getSource("heat")) map.addSource("heat", { type: "image", ...image });
    else map.getSource("heat").updateImage(image);
    if (!map.getLayer("heat")) {
      map.addLayer({ id: "heat", type: "raster", source: "heat", paint: { "raster-opacity": 0.8, "raster-fade-duration": 0 } }, "okresy-line");
    }
  }
  if (map.getLayer("heat")) map.setLayoutProperty("heat", "visibility", image ? "visible" : "none");
  if (!loaded) tip?.remove();
  renderPanel();
}

function showTip(event) {
  const value = heat ? heatValueAt(heat.model, event.lngLat.lng, event.lngLat.lat, step / 2) : current?.at(event.lngLat.lng, event.lngLat.lat);
  if (value == null) return tip?.remove();
  tip ??= new Popup({ closeButton: false, closeOnClick: false, className: "temp-tip", offset: 12, anchor: "top-left", maxWidth: "none" });
  tip.setLngLat(event.lngLat).setText(temp100mFormat(value, language, unit)).addTo(map);
}

function renderLegend() {
  const box = $("scale");
  if (!source?.single) return renderScale(box, "temperature", t("heat.legend"));
  // the old single image has its own colours: its own legend
  const { min, max } = source.single;
  const bar = element("div", null, "bar");
  bar.style.background = temp100mGradient(source.single);
  box.replaceChildren(element("div", t("heat.legend"), "scale-title"), bar, element("div", `${min}° … ${max}°`, "scale-ends"));
}

// --- the time control ----------------------------------------------------------------------
function renderTimes() {
  if (heatIndex) return renderHourly();
  const select = $("heat-time");
  select.replaceChildren(
    ...slots.map((slot, k) => {
      const option = element("option", slotLabel(slot));
      option.value = String(k);
      return option;
    }),
  );
  select.value = String(selected);
  select.disabled = slots.length < 2;
  $("heat-prev").disabled = selected <= 0;
  $("heat-next").disabled = selected >= slots.length - 1;
  const single = $("heat-single");
  single.hidden = slots.length > 1 || !source?.single;
  if (!single.hidden) single.textContent = t("heat.single", { time: slotLabel(slots[0]) });
}

/** The slider, its buttons and the label at the selected half hour. */
function renderHourly() {
  const hours = heatIndex.hours;
  $("heat-range").max = String((hours.length - 1) * 2);
  $("heat-range").value = String(step);
  $("heat-label").textContent = heatTimeText(heatTimeAt(hours, step / 2), language);
  $("heat-prev").disabled = step <= 0;
  $("heat-next").disabled = step >= (hours.length - 1) * 2;
}

/** Moves the hourly slider to `k` half hours (a click on a chart, the buttons move by whole hours). */
function chooseStep(k) {
  step = Math.max(0, Math.min((heatIndex.hours.length - 1) * 2, Math.round(k)));
  renderHourly();
  showHeat();
  renderPanel();
}

function choose(k) {
  if (heatIndex) return chooseStep(k);
  if (k < 0 || k >= slots.length) return;
  selected = k;
  renderTimes();
  showImage();
}

// --- the point: where someone clicked or searched -----------------------------------------
function setPoint(lng, lat, name = null) {
  point = { lng, lat, name };
  marker ??= new Marker({ color: "#6a4fb3" });
  marker.setLngLat([lng, lat]).addTo(map);
  if (heatIndex && !heat) return;
  if (heat) {
    point.series = heatSeriesAt(heat.model, lng, lat);
    return renderPanel();
  }
  // every time's map is loaded in the background; the panel fills in as they arrive
  renderPanel();
  for (const slot of slots) loader.load(slot.day, slot.part).then(() => renderPanel());
}

function closePoint() {
  point = null;
  marker?.remove();
  $("heat-panel").hidden = true;
}

async function placeName(at) {
  const found = nearestPlaceOf(await loadPlaces(), at.lat, at.lng);
  if (!found) return null;
  const label = placeLabel(found.place);
  return found.km <= AT_KM ? label : t("heat.near", { name: label });
}

const SVG = "http://www.w3.org/2000/svg";
const svgElement = (tag, attributes = {}, text = null) => {
  const e = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) e.setAttribute(name, value);
  if (text != null) e.textContent = text;
  return e;
};

/** The hourly values as a small line chart, the selected time marked; a click on it chooses that time. */
function seriesChart(series) {
  const W = 300;
  const H = 104;
  const left = 26;
  const right = 6;
  const top = 6;
  const bottom = 16;
  const finiteValues = Array.from(series).filter(Number.isFinite);
  const lo = Math.floor(Math.min(...finiteValues));
  const hi = Math.max(Math.ceil(Math.max(...finiteValues)), lo + 1);
  const last = series.length - 1;
  const x = (pos) => left + (pos / last) * (W - left - right);
  const y = (v) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const svg = svgElement("svg", { viewBox: `0 0 ${W} ${H}`, class: "heat-chart", role: "img", "aria-label": t("heat.chart") });
  for (const mark of heatDayMarks(heatIndex.hours, language)) {
    svg.append(svgElement("line", { x1: x(mark.pos), x2: x(mark.pos), y1: top, y2: H - bottom, class: "grid" }));
    svg.append(svgElement("text", { x: x(mark.pos) + 2, y: H - 4, class: "tick" }, mark.label));
  }
  if (lo < 0 && hi > 0) svg.append(svgElement("line", { x1: left, x2: W - right, y1: y(0), y2: y(0), class: "zero" }));
  svg.append(svgElement("text", { x: left - 3, y: y(hi) + 3, class: "tick end" }, `${hi}°`));
  svg.append(svgElement("text", { x: left - 3, y: y(lo) + 3, class: "tick end" }, `${lo}°`));
  const points = Array.from(series, (v, i) => (Number.isFinite(v) ? `${x(i).toFixed(1)},${y(v).toFixed(1)}` : null)).filter(Boolean);
  svg.append(svgElement("polyline", { points: points.join(" "), class: "line" }));
  const now = step / 2;
  const v = heatBlend(series, now);
  svg.append(svgElement("line", { x1: x(now), x2: x(now), y1: top, y2: H - bottom, class: "now" }));
  if (Number.isFinite(v)) svg.append(svgElement("circle", { cx: x(now), cy: y(v), r: 3, class: "dot" }));
  svg.addEventListener("click", (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    chooseStep(((px - left) / (W - left - right)) * last * 2);
  });
  return svg;
}

async function renderHourlyPanel() {
  const panel = $("heat-panel");
  const at = point;
  panel.hidden = false;
  at.label ??= at.name ?? (await placeName(at));
  if (at !== point) return;
  const title = element("div", null, "heat-title");
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("heat.close"));
  close.addEventListener("click", closePoint);
  title.append(element("strong", at.label ?? t("heat.coords", { lat: at.lat.toFixed(2), lon: at.lng.toFixed(2) })), close);
  const value = heatBlend(at.series, step / 2);
  const lines = [
    title,
    element("div", Number.isFinite(value) ? temp100mFormat(value, language, unit) : "–", "heat-big"),
    element("div", heatTimeText(heatTimeAt(heatIndex.hours, step / 2), language), "heat-when-label"),
  ];
  if (!at.series.some(Number.isFinite)) lines.push(element("p", t("heat.outside"), "muted"));
  else lines.push(element("div", t("heat.series"), "box-label"), seriesChart(at.series));
  panel.replaceChildren(...lines);
}

async function renderPanel() {
  const panel = $("heat-panel");
  const at = point;
  if (!at) {
    panel.hidden = true;
    return;
  }
  if (heatIndex) return heat ? renderHourlyPanel() : undefined; // before the images arrive the panel waits
  panel.hidden = false;
  // a time whose map has not arrived yet is `undefined`, one without data there `null`
  const values = slots.map((s) => {
    const m = loader.peek(s.day, s.part);
    return m === undefined ? undefined : m ? m.at(at.lng, at.lat) : null;
  });
  const name = at.name ?? (await placeName(at));
  if (at !== point) return;
  const title = element("div", null, "heat-title");
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("heat.close"));
  close.addEventListener("click", closePoint);
  title.append(element("strong", name ?? t("heat.coords", { lat: at.lat.toFixed(2), lon: at.lng.toFixed(2) })), close);
  const value = values[selected];
  const lines = [
    title,
    element("div", typeof value === "number" ? temp100mFormat(value, language, unit) : "–", "heat-big"),
    element("div", slotLabel(slots[selected]), "heat-when-label"),
  ];
  if (values.every((v) => v === null)) lines.push(element("p", t("heat.outside"), "muted"));
  else {
    lines.push(element("div", t("heat.all"), "box-label"));
    const list = element("ul", null, "heat-list");
    slots.forEach((slot, k) => {
      const li = element("li", null, k === selected ? "current" : "");
      const button = element("button");
      button.type = "button";
      const text = values[k] === undefined ? t("heat.loading") : values[k] === null ? t("heat.noData") : temp100mFormat(values[k], language, unit);
      button.append(element("span", slotLabel(slot)), element("strong", text));
      button.addEventListener("click", () => choose(k));
      li.append(button);
      list.append(li);
    });
    lines.push(list);
  }
  panel.replaceChildren(...lines);
}

// --- find a place -------------------------------------------------------------------------
function choosePlace(place) {
  setPoint(place.lon, place.lat, placeLabel(place));
  if (!map.getBounds().contains([place.lon, place.lat])) map.easeTo({ center: [place.lon, place.lat] });
}

/** The hourly map: the slider's range, the images' download (with its progress), the first picture. */
async function startHourly() {
  const hours = heatIndex.hours;
  heat = null;
  step = heatNearestHour(hours, Date.now()) * 2;
  for (const id of ["ribbon", "heat-wrap", "heat-note"]) $(id).hidden = false;
  $("heat-time").hidden = true;
  $("heat-range").hidden = false;
  $("heat-label").hidden = false;
  renderLegend();
  renderHourly();
  map = makeMap();
  await new Promise((resolve) => map.once("style.load", resolve));
  addLayers();
  $("heat-range").addEventListener("input", (e) => chooseStep(Number(e.target.value)));
  $("heat-prev").addEventListener("click", () => chooseStep(step - 2));
  $("heat-next").addEventListener("click", () => chooseStep(step + 2));
  $("obce-search").replaceChildren(placeSearch({ t, load: loadPlaces, choose: choosePlace }));
  // the label above the map shows the download's progress, then the time again
  const label = $("heat-label");
  label.textContent = t("heat.loadingMap", { pct: 0 });
  try {
    const model = await loadHeatModel(heatIndex, (done, total) => {
      label.textContent = t("heat.loadingMap", { pct: total ? Math.min(100, Math.floor((done / total) * 100)) : 0 });
    });
    heat = { index: heatIndex, model, shrink: pictureShrink(heatIndex.width), lut: heatColourLut((v) => colorFor(v, "temperature")) };
  } catch {
    label.textContent = t("heat.loadFailed");
    return;
  }
  renderHourly();
  showHeat();
  if (point) setPoint(point.lng, point.lat, point.name);
}

async function main() {
  heatIndex = parseHeatIndex(await fetchJson(HEAT_INDEX));
  if (heatIndex) return startHourly();
  const index = parseTemp100mIndex(await fetchJson(TEMP100M_INDEX));
  const single = index ? null : parseTemp100m(await fetchJson(TEMP100M_JSON));
  source = index ? { index } : single ? { single } : null;
  if (!source) {
    $("heat-empty").hidden = false;
    return;
  }
  loader = temp100mLoader(source, (v) => colorFor(v, "temperature"));
  if (index) {
    unit = index.unit;
    slots = index.maps.map((m) => ({ day: m.day, part: m.part, time: m.time })).sort((a, b) => a.time - b.time);
  } else {
    unit = single.unit;
    const slot = temp100mSlot(single.time);
    slots = [{ day: slot.day, part: slot.part, time: single.time }];
  }
  selected = Math.max(0, temp100mDefaultIndex(slots, Date.now()));
  for (const id of ["ribbon", "heat-wrap", "heat-note"]) $(id).hidden = false;
  renderTimes();
  renderLegend();
  map = makeMap();
  await new Promise((resolve) => map.once("style.load", resolve));
  addLayers();
  $("heat-time").addEventListener("change", (e) => choose(Number(e.target.value)));
  $("heat-prev").addEventListener("click", () => choose(selected - 1));
  $("heat-next").addEventListener("click", () => choose(selected + 1));
  $("obce-search").replaceChildren(placeSearch({ t, load: loadPlaces, choose: choosePlace }));
  showImage();
}

main();
