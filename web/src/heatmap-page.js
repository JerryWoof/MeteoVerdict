import { Map as MapLibreMap, Marker, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { setUpLanguage } from "./i18n.js";
import { addLocateControl, locationDot } from "./locate-control.js";
import { placeSearch } from "./place-search.js";
import { placeLabel, placesLoader } from "./places.js";
import placesUrl from "./data/obce.json?url";
import { colorFor, renderScale } from "./palette.js";
import { keepRoomForPanels, userMoved } from "./panel-room.js";
import { BASEMAP_ATTRIBUTION, BASEMAP_SPEC, GLYPHS, baseLayers, basemapSources, topLayers } from "./radar-basemap.js";
import { themeMap } from "./map-theme.js";
import {
  TEMP100M_INDEX, TEMP100M_JSON, nearestPlaceOf, parseTemp100m, parseTemp100mIndex, temp100mDefaultIndex,
  temp100mFormat, temp100mGradient, temp100mLoader, temp100mSlot, temp100mSlotText,
} from "./ai-temp100m.js";
import {
  FROST_RISK_C, HEAT_INDEX, heatAllRange, heatFrostLevel, heatReadOptions, heatRiskRuns, heatRiskText, heatBlend, heatColourLut, heatDayMarks, heatFixedLut, heatHourRange, heatNearestHour, heatPaint,
  heatRampGradient, heatRampLut, heatSeriesAt, heatTemperatures, heatTimeAt, heatTimeText, heatValueAt, loadHeatModel, parseHeatIndex,
  heatHash, heatParseHash, heatStepAt,
} from "./ai-heat.js";
import { hashHistory } from "./hash-history.js";

// The heatmap tab: MeteoVerdict AI's 100 m temperature over the radar page's base map,
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
let heat = null; // the hourly map: { index, model, fixedLut, shrink, temps, allRange } once its images are loaded
const OPTIONS_KEY = "heat-options";
const COLOUR_MODES = ["hour", "all", "fixed"];
// the display options (remembered in the browser): colours and the frost risk overlay
const options = { colours: "all", frost: true };
try {
  Object.assign(options, heatReadOptions(JSON.parse(localStorage.getItem(OPTIONS_KEY) ?? "null")));
} catch {
  // no storage: the defaults
}
const saveOptions = () => {
  try {
    // the colours remembered are the ones clicked, not a link's
    localStorage.setItem(OPTIONS_KEY, JSON.stringify({ v: 3, ...options, colours: preferredColours }));
  } catch {
    // not remembered
  }
};
let preferredColours = options.colours; // the colours remembered in the browser: a link without colours shows them
let heatIndex = null; // its index.json, parsed
let sharpening = null; // percent of the full-size images downloaded while the coarse picture is shown, else null
let step = 0; // the hourly slider's position, in half hours
let unit = "°C";
let map = null;
let applyTheme = () => {};
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
  const myDot = locationDot(m);
  applyTheme = themeMap(m, { ...BASEMAP_SPEC, "okresy-line": { "line-color": ["#ffffff", "#151412"] } });
  addLocateControl(m, {
    t,
    places: () => loadPlaces(),
    onFix: ({ lat, lon }) => {
      myDot.show(lon, lat);
      m.easeTo({ center: [lon, lat], zoom: Math.max(m.getZoom(), 8.5) });
      setPoint(lon, lat, null, true); // the panel, as for a click on the map
    },
  });
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
  applyTheme();
  map.on("click", (event) => pickPoint(event.lngLat.lng, event.lngLat.lat));
  // the hover value only with a mouse: a tap on a phone also sends a mousemove, and that
  // tooltip stayed on the map next to the panel the tap opened
  if (window.matchMedia("(hover: hover)").matches) map.on("mousemove", showTip);
  map.getCanvas().addEventListener("mouseleave", () => tip?.remove());
}

/** The "All 5 days" range, worked out once in the background (the picture uses the hour's range until it is there). */
function ensureAllRange() {
  if (!heat || heat.allRange !== undefined) return;
  heat.allRange = null;
  return heatAllRange(heat.model, 16, 64, (done) => (done % 8 === 0 ? new Promise((r) => setTimeout(r)) : undefined)).then((range) => {
    heat.allRange = range ?? false;
    if (options.colours === "all") showHeat();
  });
}

/** The hourly map's picture at the slider's time (the latest request wins). */
let composeFrame = 0;
function showHeat() {
  cancelAnimationFrame(composeFrame);
  composeFrame = requestAnimationFrame(() => {
    if (!heat || !map) return;
    if (options.colours === "all") ensureAllRange();
    heat.temps = heatTemperatures(heat.model, step / 2, heat.shrink, heat.temps);
    const hourRange = heatHourRange(heat.temps.hist) ?? { lo: -15, hi: 32 };
    const range = options.colours === "fixed" ? null : options.colours === "all" && heat.allRange ? heat.allRange : hourRange;
    const lut = range ? heatRampLut(range.lo, range.hi) : heat.fixedLut;
    const { data, width, height } = heatPaint(heat.temps, lut, options);
    renderLegend(range);
    const image = new ImageData(data, width, height);
    if (!map.getSource("heat")) map.addSource("heat", { type: "image", coordinates: heat.index.coordinates });
    map.getSource("heat").updateImage({ image, coordinates: heat.index.coordinates });
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

/** A legend end in the page language ("21,5°" in Czech). */
const degrees = (value) => `${value.toLocaleString(language)}°`;

/** The hourly map's legend: the active ramp with its ends in °C (`range` null: the fixed scale), and the overlays' swatches. */
function renderHourlyLegend(range) {
  const box = $("scale");
  if (!range) renderScale(box, "temperature", t("heat.legend"));
  else {
    const bar = element("div", null, "bar");
    bar.style.background = heatRampGradient();
    box.replaceChildren(element("div", t("heat.legend"), "scale-title"), bar, element("div", `${degrees(range.lo)} … ${degrees(range.hi)}`, "scale-ends"));
  }
  if (options.frost) {
    const row = element("div", null, "scale-key");
    row.append(element("span", null, "swatch frost"), element("span", t("heat.legendFrost")));
    box.append(row);
  }
}

function renderLegend(range) {
  const box = $("scale");
  if (heatIndex && heat) return renderHourlyLegend(range);
  if (!source?.single) return renderScale(box, "temperature", t("heat.legend"));
  // the old single image has its own colours: its own legend
  const { min, max } = source.single;
  const bar = element("div", null, "bar");
  bar.style.background = temp100mGradient(source.single);
  box.replaceChildren(element("div", t("heat.legend"), "scale-title"), bar, element("div", `${degrees(min)} … ${degrees(max)}`, "scale-ends"));
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
  const time = heatTimeText(heatTimeAt(hours, step / 2), language);
  $("heat-label").textContent = sharpening === null ? time : `${time} · ${t("heat.sharpening", { pct: sharpening })}`;
  $("heat-prev").disabled = step <= 0;
  $("heat-next").disabled = step >= (hours.length - 1) * 2;
}

/** Moves the hourly slider to `k` half hours (a click on a chart, the buttons move by whole hours). */
function chooseStep(k) {
  step = Math.max(0, Math.min((heatIndex.hours.length - 1) * 2, Math.round(k)));
  timeChosen = true;
  renderHourly();
  showHeat();
  renderPanel();
  writeHashSoon();
}

// --- the view in the address (ai-heat.js heatParseHash): the time once chosen, the colours
// once chosen (else the browser's remembered ones), the clicked place. A new place is a step
// in the history; the slider and the colours replace the current entry.
let timeChosen = false;
let coloursChosen = false;
const address = hashHistory((hash) => applyHash(hash));

function writeHash(push = false) {
  if (!heatIndex) return; // the older day-part maps keep no state in the address
  clearTimeout(hashTimer);
  address.write(heatHash({
    time: timeChosen ? heatTimeAt(heatIndex.hours, step / 2) : null,
    colours: coloursChosen ? options.colours : null,
    point: point && !point.own && { lat: point.lat, lng: point.lng },
  }), push);
}
// the slider moves in many small steps: the address follows once it rests (browsers limit the writes)
let hashTimer = 0;
const writeHashSoon = () => {
  clearTimeout(hashTimer);
  hashTimer = setTimeout(() => writeHash(), 300);
};

/** The view of a hash (on load, Back/Forward, a pasted link); `apply`: draw it (the page is running). */
function readHash(hash, apply = true) {
  if (!heatIndex) return;
  const view = heatParseHash(hash);
  timeChosen = view.time != null;
  step = timeChosen ? heatStepAt(heatIndex.hours, view.time) : heatNearestHour(heatIndex.hours, Date.now()) * 2;
  coloursChosen = view.colours != null;
  options.colours = view.colours ?? preferredColours;
  if (!apply) {
    point = view.point && { ...view.point, name: null };
    return;
  }
  renderHourly();
  for (const b of document.querySelectorAll("#heat-options .seg-buttons button")) b.setAttribute("aria-pressed", String(b.dataset.mode === options.colours));
  showHeat();
  if (view.point) setPoint(view.point.lng, view.point.lat);
  else closePoint(false);
  writeHash(); // what is shown (a garbage part dropped)
}
function applyHash(hash) {
  if (map) readHash(hash);
}

function choose(k) {
  if (heatIndex) return chooseStep(k);
  if (k < 0 || k >= slots.length) return;
  selected = k;
  renderTimes();
  showImage();
}

// --- the point: where someone clicked or searched -----------------------------------------
// `own`: my location, kept out of the address (links share clicked places, not where someone is)
function setPoint(lng, lat, name = null, own = false) {
  point = { lng, lat, name, own };
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

function closePoint(write = true) {
  point = null;
  marker?.remove();
  $("heat-panel").hidden = true;
  if (write) writeHash();
}

/** A place clicked or found: the panel, and a step in the browser's history. */
function pickPoint(lng, lat, name = null) {
  setPoint(lng, lat, name);
  writeHash(true);
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
  // the range always holds the frost risk line
  const lo = Math.floor(Math.min(...finiteValues, FROST_RISK_C));
  const hi = Math.max(Math.ceil(Math.max(...finiteValues)), FROST_RISK_C, lo + 1);
  const last = series.length - 1;
  const x = (pos) => left + (pos / last) * (W - left - right);
  const y = (v) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const svg = svgElement("svg", { viewBox: `0 0 ${W} ${H}`, class: "heat-chart", role: "img", "aria-label": t("heat.chart") });
  for (const mark of heatDayMarks(heatIndex.hours, language)) {
    svg.append(svgElement("line", { x1: x(mark.pos), x2: x(mark.pos), y1: top, y2: H - bottom, class: "grid" }));
    svg.append(svgElement("text", { x: x(mark.pos) + 2, y: H - 4, class: "tick" }, mark.label));
  }
  // the area below the frost risk line, shaded lightly
  if (lo < FROST_RISK_C) svg.append(svgElement("rect", { x: left, y: y(FROST_RISK_C), width: W - left - right, height: y(lo) - y(FROST_RISK_C), class: "frost" }));
  if (lo < 0 && hi > 0) svg.append(svgElement("line", { x1: left, x2: W - right, y1: y(0), y2: y(0), class: "zero" }));
  svg.append(svgElement("line", { x1: left, x2: W - right, y1: y(FROST_RISK_C), y2: y(FROST_RISK_C), class: "risk" }));
  svg.append(svgElement("text", { x: W - right - 2, y: y(FROST_RISK_C) - 2, class: "tick end risk-label" }, `${FROST_RISK_C} °C`));
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
  close.addEventListener("click", () => closePoint());
  title.append(element("strong", at.label ?? t("heat.coords", { lat: at.lat.toFixed(2), lon: at.lng.toFixed(2) })), close);
  const value = heatBlend(at.series, step / 2);
  const lines = [
    title,
    element("div", Number.isFinite(value) ? temp100mFormat(value, language, unit) : "–", "heat-big"),
    element("div", heatTimeText(heatTimeAt(heatIndex.hours, step / 2), language), "heat-when-label"),
  ];
  const level = heatFrostLevel(value);
  if (level) lines.splice(2, 0, element("div", t(level === 2 ? "heat.frostNow" : "heat.risk"), "heat-risk"));
  const runs = heatRiskRuns(at.series);
  if (runs.length) lines.push(element("div", t("heat.riskTimes", { times: heatRiskText(runs, heatIndex.hours, language) }), "heat-risk-times"));
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
  pickPoint(place.lon, place.lat, placeLabel(place));
  if (!map.getBounds().contains([place.lon, place.lat])) map.easeTo({ center: [place.lon, place.lat] });
}

/** The options row above the map: the colour buttons and the two overlay checkboxes. */
function renderOptions() {
  const box = $("heat-options");
  const change = () => {
    saveOptions();
    writeHash();
    for (const b of box.querySelectorAll(".seg-buttons button")) b.setAttribute("aria-pressed", String(b.dataset.mode === options.colours));
    showHeat();
  };
  const seg = element("div", null, "seg");
  seg.append(element("span", t("heat.colours")));
  const buttons = element("span", null, "seg-buttons");
  for (const mode of COLOUR_MODES) {
    const button = element("button", t(`heat.col.${mode}`));
    button.type = "button";
    button.dataset.mode = mode;
    button.setAttribute("aria-pressed", String(options.colours === mode));
    button.addEventListener("click", () => {
      options.colours = mode;
      preferredColours = mode;
      coloursChosen = true;
      change();
    });
    buttons.append(button);
  }
  seg.append(buttons);
  const check = (key, label) => {
    const wrap = element("label", null, "check");
    const input = element("input");
    input.type = "checkbox";
    input.checked = options[key];
    input.addEventListener("change", () => {
      options[key] = input.checked;
      change();
    });
    wrap.append(input, element("span", label));
    return wrap;
  };
  box.replaceChildren(seg, check("frost", t("heat.frost")));
  box.hidden = false;
}

/** The hourly map: the slider's range, the images' download (with its progress), the first picture. */
async function startHourly() {
  const hours = heatIndex.hours;
  heat = null;
  step = heatNearestHour(hours, Date.now()) * 2;
  readHash(window.location.hash, false); // a link's time, colours and place
  for (const id of ["ribbon", "heat-wrap", "heat-note"]) $(id).hidden = false;
  $("heat-time").hidden = true;
  $("heat-range").hidden = false;
  $("heat-label").hidden = false;
  renderLegend();
  renderHourly();
  map = makeMap();
  await new Promise((resolve) => map.once("style.load", resolve));
  addLayers();
  if (point) setPoint(point.lng, point.lat, point.name, point.own); // the link's place: its marker now, its panel once the map loads
  writeHash();
  $("heat-range").addEventListener("input", (e) => chooseStep(Number(e.target.value)));
  $("heat-prev").addEventListener("click", () => chooseStep(step - 2));
  $("heat-next").addEventListener("click", () => chooseStep(step + 2));
  $("obce-search").replaceChildren(placeSearch({ t, load: loadPlaces, choose: choosePlace }));
  // the label above the map shows the download's progress, then the time again
  const label = $("heat-label");
  const percent = (done, total) => (total ? Math.min(100, Math.floor((done / total) * 100)) : 0);
  const setModel = (model, shrink) => {
    if (!heat) heat = { fixedLut: heatFixedLut(heatColourLut((v) => colorFor(v, "temperature"))), temps: null, allRange: undefined };
    Object.assign(heat, { index: model.index, model, shrink });
  };
  // the coarse set first (a few hundred kB): drawn at once, the full-size one replaces it later
  const coarse = heatIndex.lo;
  label.textContent = t("heat.loadingMap", { pct: 0 });
  if (coarse) {
    try {
      setModel(await loadHeatModel(coarse, (done, total) => (label.textContent = t("heat.loadingMap", { pct: percent(done, total) }))), 1);
    } catch {
      heat = null; // the full-size set below, as without a coarse one
    }
  }
  if (heat) sharpening = 0;
  const loadFull = async () => {
    const model = await loadHeatModel(heatIndex, (done, total) => {
      if (!heat) label.textContent = t("heat.loadingMap", { pct: percent(done, total) });
      else {
        sharpening = percent(done, total);
        renderHourly();
      }
    });
    setModel(model, pictureShrink(heatIndex.width));
  };
  if (heat) {
    // the full-size images load in the background; the page works with the coarse ones meanwhile
    renderHourly();
    renderOptions();
    if (options.colours === "all") await ensureAllRange();
    showHeat();
    if (point) setPoint(point.lng, point.lat, point.name, point.own);
    try {
      await loadFull();
    } catch {
      // the coarse picture stays
    }
    sharpening = null;
    renderHourly();
    showHeat();
    if (point) setPoint(point.lng, point.lat, point.name, point.own);
    return;
  }
  try {
    await loadFull();
  } catch {
    label.textContent = t("heat.loadFailed");
    return;
  }
  renderHourly();
  renderOptions();
  // the colours of "All 5 days" must not change while scrubbing: wait for the range before the first picture
  if (options.colours === "all") await ensureAllRange();
  showHeat();
  if (point) setPoint(point.lng, point.lat, point.name, point.own);
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
