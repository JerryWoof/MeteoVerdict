import { Map as MapLibreMap, Marker, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";
import "./fit-map.js";

import { setUpLanguage } from "./i18n.js";
import {
  HOURS, MM_SCALE, boundsOf, clock, frameUrl, imageCoordinates, latestAtOrBefore, legendNumber,
  minutesBetween, parseStamp, parseView, rainRate, sourceUrl, timeline, toStamp, viewHash,
  frameFolder, pragueDayIndex, pragueDayWindow, previousDay,
} from "./radar.js";
import { hashHistory } from "./hash-history.js";
import {
  ALOFT_COLOURS, CATEGORIES, FILTER_KEYS, NODATA, buildLut, categoriesFrom, categoryOf, decodePixels, dbzLevel,
  filterLevels, labelKey, legendRows, maxzScale, parseFilter, rateLabel, simpleScale,
} from "./radar-palette.js";
import {
  SPEEDS, advanceClock, locate, motionFor, msPerDataMinute, quantize, upsampleFlow, validMotion,
  warpBlend,
} from "./radar-motion.js";
import {
  bracket, cellFeatures, compass, hourTicks, lonLatToPixel, nowcastSentence, relativeTime, sample,
  satelliteProduct,
} from "./radar-extras.js";
import { BASEMAP_ATTRIBUTION, BASEMAP_SPEC, GLYPHS, PLACE_LAYERS, baseLayers, basemapSources, topLayers } from "./radar-basemap.js";
import { INK, themeMap } from "./map-theme.js";
import { placeSearch } from "./place-search.js";
import { placeLabel, placesLoader } from "./places.js";
import placesUrl from "./data/obce.json?url";
import { addLocateControl, locationDot } from "./locate-control.js";
import { scrollToPanel } from "./panel-room.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();
const language = document.documentElement.lang === "cs" ? "cs" : "en";
// a number for the page: "0,4" in Czech, "0.4" in English
const dec = (text) => (language === "cs" ? String(text).replace(".", ",") : String(text));

// Live frames: the branch radar-live (force-pushed by the Radar workflow every ~10 min),
// served with CORS by raw.githubusercontent.com (cached about 5 min). Archived days:
// radar/days/YYYYMMDD/ on this site (from the releases radar-YYYY-MM, see pages.yml).
const LIVE = import.meta.env.VITE_RADAR_LIVE ?? "https://raw.githubusercontent.com/JerryWoof/MeteoVerdict/radar-live/";
const REFRESH_MS = 5 * 60 * 1000;
const STALE_MIN = 30;
const MINUTE = 60000;
const DEFAULT_LAYERS = ["radar", "sat", "cells"]; // a first visit: radar on clouds, with storms
const SAT_LAYERS = ["sat", "wv"];

// --- small storage helpers (private windows may throw) ----------------------------------
function stored(key, fallback) {
  try {
    return window.localStorage.getItem(`radar.${key}`) ?? fallback;
  } catch {
    return fallback;
  }
}
function store(key, value) {
  try {
    window.localStorage.setItem(`radar.${key}`, String(value));
  } catch {
    // keep working without storage
  }
}

const map = new MapLibreMap({
  container: "map",
  // the base map under the radar (radar-basemap.js); its labels go on top in addLayers()
  style: { version: 8, glyphs: GLYPHS, sources: basemapSources(), layers: baseLayers() },
  bounds: [
    [12.0, 48.5],
    [18.95, 51.1],
  ],
  fitBoundsOptions: { padding: 20 },
  attributionControl: { compact: true, customAttribution: `Radar: ČHMÚ (CC BY 4.0) · Satellite: contains modified EUMETSAT Meteosat data ${new Date().getFullYear()} (CC BY 4.0), processed by ČHMÚ · Boundaries, places: ČÚZK (CC BY 4.0) · ${BASEMAP_ATTRIBUTION}` },
});
map.addControl(new NavigationControl({ showCompass: false }));
const myDot = locationDot(map);
const applyTheme = themeMap(map, {
  ...BASEMAP_SPEC,
  "kraje-line": { "line-color": ["#3a444c", "#b5ab9e"] },
  "cell-tracks": { "line-color": INK },
  "cell-arrows": { "line-color": [["case", ["get", "hail"], "#b3001b", "#1d2329"], ["case", ["get", "hail"], "#ff5a6a", "#ece7df"]] },
  "cell-points": {
    "circle-color": [["case", ["get", "hail"], "#ffffff", "#1d2329"], ["case", ["get", "hail"], "#151412", "#ece7df"]],
    "circle-stroke-color": [["case", ["get", "hail"], "#d0021b", "#ffffff"], ["case", ["get", "hail"], "#ff5a6a", "#151412"]],
  },
});
addLocateControl(map, {
  t,
  places: () => loadPlaces(),
  onFix: ({ lat, lon }) => {
    myDot.show(lon, lat);
    map.easeTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 8.5) });
  },
});
// the style, not its tiles: "load" would wait for every base-map tile before the radar
const mapLoaded = new Promise((resolve) => map.once("style.load", resolve));

const hadHash = window.location.hash.length > 1;
let view = parseView(window.location.hash);
if (!hadHash) view.layers = DEFAULT_LAYERS;
view.filter = parseFilter(view.filter ?? stored("filter", "all"));
let index = null; // index.json of the shown source
let base = null; // its folder
let sourceDay = null; // the day of the shown source ("live" or an archived day)
/** The folder of a frame of the shown source (an archived Prague day spans two UTC folders). */
const folderOf = (stamp) => frameFolder(stamp, sourceDay, base);
let steps = [];
let allSteps = []; // every frame of the source, for the rain at a place
let days = [];
let shownMs = null; // the data time on the map (a whole minute)
let playing = false;
let clockState = { ms: 0, hold: 0 };
const DEFAULT_SPEED = 4;
let speed = SPEEDS.includes(Number(stored("speed2", DEFAULT_SPEED))) ? Number(stored("speed2", DEFAULT_SPEED)) : DEFAULT_SPEED;
// half strength by default: the clouds under the radar, not over it
let satOpacity = Math.min(1, Math.max(0.2, Number(stored("satOpacity", 0.5)) || 0.5));
let point = null; // {lon, lat, name?} of the rain-at-my-place panel

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

async function getJson(url, fresh = false) {
  try {
    const response = await fetch(url, fresh ? { cache: "no-cache" } : {});
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const has = (layer) => view.layers.includes(layer);
const firstTime = () => steps[0]?.time ?? 0;
const lastTime = () => steps.at(-1)?.time ?? 0;
const lastObserved = () => steps.findLast((s) => !s.forecast)?.time ?? null;
const radarUrl = (s) => frameUrl(folderOf(s.radar), s.forecast ? "nowcast" : "maxz", s.radar);

// --- decoded frames -----------------------------------------------------------------------
// url → Promise<{codes, w, h} | null>, least recently used dropped beyond cacheSize():
// the whole loop (radar and rain frames) fits, so a replay starts from memory
const cacheSize = () => Math.min(400, Math.max(120, 2 * steps.length + 16));
const frames = new Map();
const ready = new Map(); // url → decoded (only those finished)
const failed = new Set(); // urls that could not be loaded
let scratch = null;

async function decodeUrl(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob, { premultiplyAlpha: "none", colorSpaceConversion: "none" });
    const { width: w, height: h } = bitmap;
    scratch ??= document.createElement("canvas");
    scratch.width = w;
    scratch.height = h;
    const ctx = scratch.getContext("2d", { willReadFrequently: true });
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0);
    bitmap.close?.();
    return { codes: decodePixels(ctx.getImageData(0, 0, w, h).data), w, h };
  } catch {
    return null;
  }
}

function frame(url) {
  let promise = frames.get(url);
  if (promise) {
    frames.delete(url); // most recently used last
    frames.set(url, promise);
    return promise;
  }
  promise = decodeUrl(url).then((decoded) => {
    if (decoded) ready.set(url, decoded);
    else {
      // gone (the live folder drops old nowcasts every 5 min) or broken: never wait for
      // it again, and fetch a fresh frame list
      frames.delete(url); // a fresh frame list may bring it back
      failed.add(url);
      refreshSoon();
    }
    return decoded;
  });
  frames.set(url, promise);
  while (frames.size > cacheSize()) {
    const oldest = frames.keys().next().value;
    frames.delete(oldest);
    ready.delete(oldest);
  }
  return promise;
}

const motions = new Map(); // stamp → Promise<motion | null>
const motionReady = new Map();
function motion(stamp) {
  if (!motions.has(stamp)) {
    motions.set(
      stamp,
      getJson(`${folderOf(stamp)}motion/${stamp}.json`).then((m) => {
        const ok = validMotion(m) ? m : null;
        motionReady.set(stamp, ok);
        return ok;
      }),
    );
  }
  return motions.get(stamp);
}
const flows = new Map(); // `${stamp}|${seconds}|${scale}` → flow
function flowFor(pair, w, h, scale) {
  const m = motionReady.get(pair.stamp);
  if (!m) {
    if (!motionReady.has(pair.stamp)) motion(pair.stamp).then(() => requestDraw());
    return null;
  }
  const key = `${pair.stamp}|${pair.seconds}|${scale}`;
  if (!flows.has(key)) {
    if (flows.size > 40) flows.delete(flows.keys().next().value);
    flows.set(key, upsampleFlow(m, w, h, pair.seconds, scale));
  }
  return flows.get(key);
}

// --- canvases on the map ------------------------------------------------------------------
class GridCanvas {
  constructor(id, before) {
    this.id = id;
    this.before = before;
    this.canvas = document.createElement("canvas");
    this.canvas.width = 1;
    this.canvas.height = 1;
    this.scale = 1;
    this.visible = false;
    this.key = null;
  }
  ensure(w, h, scale) {
    const ow = Math.ceil(w / scale);
    const oh = Math.ceil(h / scale);
    if (this.canvas.width !== ow || this.canvas.height !== oh) {
      this.canvas.width = ow;
      this.canvas.height = oh;
      this.ctx = this.canvas.getContext("2d");
      this.image = this.ctx.createImageData(ow, oh);
      this.pixels = new Uint32Array(this.image.data.buffer);
    }
    this.ctx ??= this.canvas.getContext("2d");
    if (!map.getSource(this.id)) {
      map.addSource(this.id, { type: "canvas", canvas: this.canvas, coordinates: imageCoordinates(boundsOf(index)), animate: false });
      map.addLayer({ id: this.id, type: "raster", source: this.id, paint: { "raster-fade-duration": 0, "raster-resampling": "linear" } }, this.before);
    } else {
      map.getSource(this.id).setCoordinates(imageCoordinates(boundsOf(index)));
    }
  }
  commit(opacity) {
    this.ctx.putImageData(this.image, 0, 0);
    const source = map.getSource(this.id);
    source.play();
    if (this.opacity !== opacity) map.setPaintProperty(this.id, "raster-opacity", opacity);
    if (!this.visible) map.setLayoutProperty(this.id, "visibility", "visible");
    this.opacity = opacity;
    this.visible = true;
    // upload once, then stop re-uploading every frame
    cancelAnimationFrame(this.pauseId);
    this.pauseId = requestAnimationFrame(() => requestAnimationFrame(() => source.pause()));
  }
  hide() {
    if (this.visible && map.getLayer(this.id)) map.setLayoutProperty(this.id, "visibility", "none");
    this.visible = false;
    this.key = null;
  }
}

let radarCanvas;
let rainCanvas;
let lutRadar;
let hiddenByFilter = false; // the frame has echoes, but the "show from" setting hides (almost) all

/** True when a frame has echoes and the colour table hides practically all of them: at
 * most 25 pixels (about 25 km²) stay visible, out of at least ten times as many. */
function allHidden(codes, lut) {
  let echoes = 0;
  let shown = 0;
  for (let p = 0; p < codes.length; p++) {
    const c = codes[p];
    if (c === 0 || c === NODATA) continue;
    echoes++;
    if (lut[c] !== 0 && ++shown > 25) return false;
  }
  return echoes > 0 && echoes >= 10 * shown;
}
let lutRain;
let categories = CATEGORIES; // as index.json labels the classes
function makeLuts() {
  categories = categoriesFrom(index?.scales?.maxz);
  const f = filterLevels(view.filter, categories);
  const scale = maxzScale(index, null).map((r) => r[1]);
  lutRadar = buildLut({ solid: scale.length === 15 ? scale : undefined, minLevel: f.radar, aloft: f.aloft });
  lutRain = buildLut({ minLevel: f.rain, nodata: 0 });
  if (radarCanvas) radarCanvas.key = null;
  if (rainCanvas) rainCanvas.key = null;
}

// frame time of drawing (ms), to choose the resolution on slow devices
const perf = { samples: [], scale: 1, draws: 0 };
window.__radarPerf = perf;
function measure(ms) {
  perf.samples.push(ms);
  if (perf.samples.length > 30) perf.samples.shift();
  perf.draws++;
  perf.last = ms;
  perf.avg = perf.samples.reduce((a, b) => a + b, 0) / perf.samples.length;
  perf.max = Math.max(...perf.samples);
  // half resolution (4× fewer pixels) when a full-size frame takes too long
  if (perf.scale === 1 && perf.samples.length >= 8 && perf.avg > 14) {
    perf.scale = 2;
    perf.samples = [];
    flows.clear();
  }
}

/** Draw the radar at `shownMs` (warped between frames); false while frames load. */
function drawRadar() {
  if (!has("radar") || !steps.length) {
    radarCanvas?.hide();
    return true;
  }
  // plain frames, one after another: the frame at or before the time shown (no motion
  // morphing, no cross-fading: the user found the movement distracting)
  const { i } = locate(steps, shownMs);
  const a = steps[i];
  const urlA = radarUrl(a);
  if (failed.has(urlA)) return true; // missing: keep what is drawn and go on
  const A = ready.get(urlA);
  if (!A) {
    frame(urlA).then(() => requestDraw());
    return false;
  }
  const scale = perf.scale;
  const key = `${urlA}|${scale}`;
  if (radarCanvas.key === key) return true;
  const start = performance.now();
  radarCanvas.ensure(A.w, A.h, scale);
  warpBlend(radarCanvas.pixels, A.codes, null, A.w, A.h, null, 0, lutRadar, scale);
  radarCanvas.commit(a.forecast ? 0.75 : 0.9);
  measure(performance.now() - start);
  perf.mode = "frame";
  radarCanvas.key = key;
  hiddenByFilter = allHidden(A.codes, lutRadar);
  return true;
}

function drawRain() {
  const current = steps[locate(steps, shownMs).i];
  if (!has("rain") || !current?.rain) {
    rainCanvas?.hide();
    return true;
  }
  const url = frameUrl(folderOf(current.rain), "merge1h", current.rain);
  const R = ready.get(url);
  if (!R) {
    frame(url).then(() => requestDraw());
    return false;
  }
  if (rainCanvas.key === url) return true;
  rainCanvas.ensure(R.w, R.h, 1);
  warpBlend(rainCanvas.pixels, R.codes, null, R.w, R.h, null, 0, lutRain, 1);
  rainCanvas.commit(0.8);
  rainCanvas.key = url;
  return true;
}

/** Show `url` in the raster layer `id` (created on first use), or hide it. */
const imageState = new Map(); // id → {url, opacity, visible}
function showImage(id, url, opacity, coordinates, before = "okresy-line") {
  const state = imageState.get(id) ?? {};
  if (!url) {
    if (state.visible && map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
    state.visible = false;
    imageState.set(id, state);
    return;
  }
  const source = map.getSource(id);
  if (!source) {
    map.addSource(id, { type: "image", url, coordinates });
    // satellite images in grey: ČHMÚ's night product is a false-colour RGB (pink ground,
    // purple clouds) that drowns the radar colours; grey keeps clouds as clouds
    const grey = id.startsWith("sat") ? { "raster-saturation": -1 } : {};
    map.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": opacity, "raster-fade-duration": 0, ...grey } }, before);
    imageState.set(id, { url, opacity, visible: true, coordinates: String(coordinates) });
    return;
  }
  if (state.url !== url || state.coordinates !== String(coordinates)) source.updateImage({ url, coordinates });
  if (state.opacity !== opacity) map.setPaintProperty(id, "raster-opacity", opacity);
  if (!state.visible) map.setLayoutProperty(id, "visibility", "visible");
  imageState.set(id, { url, opacity, visible: true, coordinates: String(coordinates) });
}

const preloaded = new Set();
function preload(url) {
  if (!url || preloaded.has(url)) return;
  preloaded.add(url);
  const image = new Image();
  image.src = url;
}

/** Fetch the images of the shown window into the browser cache so a frame change does not blink. */
function preloadSatellite(product, meta) {
  const first = firstTime() - 40 * MINUTE;
  for (const s of meta?.frames ?? []) {
    const ms = parseStamp(s);
    if (ms != null && ms >= first) preload(satUrl(product, meta, s));
  }
}

// satellite: the two frames around the time, cross-faded
function satelliteInfo() {
  const mode = has("wv") ? "wv" : has("sat") ? "sat" : "off";
  const product = satelliteProduct(mode === "sat" ? "clouds" : mode, shownMs ?? Date.now(), index?.satellite ?? {});
  if (!product) return null;
  const meta = index.satellite[product];
  const around = bracket(meta?.frames, shownMs, 30);
  if (around) return { product, meta, around };
  // no image near this time (a gap, or past "now" in the nowcast): keep the latest earlier
  // one on screen, or the earliest one before the first image, so the clouds never blink
  const times = (meta?.frames ?? []).map((s) => [s, parseStamp(s)]).filter(([, t]) => t != null).sort((a, b) => a[1] - b[1]);
  if (!times.length) return { product, meta, around: null };
  const before = times.filter(([, t]) => t <= shownMs).at(-1) ?? times[0];
  return { product, meta, around: { a: before[0], b: null, tau: 0 } };
}
function satUrl(product, meta, stamp) {
  return `${folderOf(stamp)}satellite/${product}/${stamp}.${meta?.ext ?? "jpg"}`;
}
function drawSatellite() {
  const info = satelliteInfo();
  if (!info?.around) {
    showImage("sat-a", null);
    showImage("sat-b", null);
    return info;
  }
  const { product, meta, around } = info;
  const b = meta.bounds;
  const coordinates = imageCoordinates(
    Array.isArray(b) && b.length === 2 ? { west: b[0][0], south: b[0][1], east: b[1][0], north: b[1][1] } : boundsOf(index),
  );
  // the nearest image, no cross-fade
  const nearest = around.b && around.tau >= 0.5 ? around.b : around.a;
  showImage("sat-a", satUrl(product, meta, nearest), satOpacity, coordinates, "okresy-line-under");
  showImage("sat-b", null);
  if (around.b) preload(satUrl(product, meta, around.b));
  preloadSatellite(product, meta);
  return info;
}

function drawEchotop() {
  const stamp = has("echotop") && !isForecastTime() ? latestAtOrBefore(index?.echotop, shownMs, 10) : null;
  showImage("echotop", stamp ? frameUrl(folderOf(stamp), "echotop", stamp) : null, 0.85, imageCoordinates(boundsOf(index)), "rain-canvas-slot");
}

let cellsData = new Map(); // stamp → Promise<cells>
function drawCells() {
  const stamp = has("cells") && !isForecastTime() ? latestAtOrBefore(index?.cells, shownMs, 10) : null;
  const source = map.getSource("cells");
  if (!stamp) {
    source?.setData({ type: "FeatureCollection", features: [] });
    return;
  }
  if (!cellsData.has(stamp)) cellsData.set(stamp, getJson(`${folderOf(stamp)}cells/${stamp}.json`));
  const forMs = shownMs;
  cellsData.get(stamp).then((cells) => {
    if (forMs !== shownMs) return;
    source?.setData(cellFeatures(cells, (shownMs - parseStamp(stamp)) / MINUTE));
  });
}

function isForecastTime() {
  const observed = lastObserved();
  return observed != null && shownMs > observed;
}

let drawPending = false;
function requestDraw() {
  if (drawPending) return;
  drawPending = true;
  requestAnimationFrame(() => {
    drawPending = false;
    drawAll();
  });
}

/** Everything that depends on the shown time. True when the radar frame was drawn. */
function drawAll() {
  if (!steps.length || shownMs == null) {
    radarCanvas?.hide();
    rainCanvas?.hide();
    showImage("sat-a", null);
    showImage("sat-b", null);
    showImage("echotop", null);
    map.getSource("cells")?.setData({ type: "FeatureCollection", features: [] });
    renderWhen(); // "no images for this day"
    return true;
  }
  const done = drawRadar();
  drawRain();
  drawSatellite();
  drawEchotop();
  drawCells();
  renderWhen();
  prefetch();
  return done;
}

/** Decode the next frames (and their motion) ahead of the animation. */
function prefetch() {
  const { i } = locate(steps, shownMs);
  const ahead = steps.slice(i, i + (playing ? 4 : 2));
  // near the end of a playing loop: the first frames too, so the replay starts at once
  if (playing && i >= steps.length - 4) ahead.push(...steps.slice(0, 4));
  for (const s of ahead) {
    if (has("radar")) frame(radarUrl(s));
    if (has("rain") && s.rain) frame(frameUrl(folderOf(s.rain), "merge1h", s.rain));
  }
}

// --- animation ------------------------------------------------------------------------------
let rafId = null;
let lastTick = null;
function tick(now) {
  if (!playing) return;
  const dt = lastTick == null ? 0 : Math.min(100, now - lastTick);
  lastTick = now;
  // every frame gets the same time on screen (a 5-minute frame's at this speed): the
  // nowcast's 10-minute steps and gaps in the data do not play slower
  const { i: at } = locate(steps, clockState.ms);
  const span = (steps[at + 1]?.time ?? 0) - (steps[at]?.time ?? 0);
  const rate = (span > 0 ? span : 5 * MINUTE) / (5 * msPerDataMinute(speed));
  const next = advanceClock(clockState, dt, { first: firstTime(), last: lastTime(), rate, holdMs: 1000 });
  // a frame that could not be loaded is not waited on: go straight to the next one
  if (has("radar")) {
    let { i } = locate(steps, next.ms);
    while (i < steps.length - 1 && failed.has(radarUrl(steps[i]))) {
      i += 1;
      next.ms = steps[i].time;
    }
  }
  const target = quantize(next.ms);
  if (target !== shownMs) {
    const previous = shownMs;
    shownMs = target;
    if (!drawAll()) {
      // wait for the frames instead of skipping them
      shownMs = previous;
      next.ms = clockState.ms;
    }
  }
  clockState = next;
  rafId = requestAnimationFrame(tick);
}

function play() {
  if (playing) return stop();
  if (steps.length < 2) return;
  playing = true;
  clockState = { ms: shownMs >= lastTime() ? firstTime() : shownMs, hold: 0 };
  shownMs = quantize(clockState.ms);
  lastTick = null;
  rafId = requestAnimationFrame(tick);
  renderPlay();
  // a playing loop has no moment in the link: a reload or the language switch opens live,
  // not on the frame where the loop started
  writeHash();
}

function stop() {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = null;
  if (playing) {
    playing = false;
    renderPlay();
    writeHash();
    refreshPoint();
  }
}

/** Jump to a time (stops the animation). */
function goTo(ms) {
  stop();
  shownMs = Math.min(lastTime(), Math.max(firstTime(), quantize(ms)));
  requestDraw();
  writeHash();
}

function stepBy(direction) {
  if (!steps.length) return;
  const { i, tau } = locate(steps, shownMs);
  const target = direction < 0 ? (tau > 0 ? i : i - 1) : i + 1;
  goTo(steps[Math.min(steps.length - 1, Math.max(0, target))].time);
}

// --- map layers --------------------------------------------------------------------------
function addLayers() {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  // order: satellite, radar, echo tops, 1-hour sums, then the lines and the storm cells
  const empty = { type: "geojson", data: { type: "FeatureCollection", features: [] } };
  map.addSource("slot", empty);
  map.addLayer({ id: "okresy-line-under", type: "line", source: "slot" });
  map.addLayer({ id: "radar-canvas-slot", type: "line", source: "slot" });
  map.addLayer({ id: "rain-canvas-slot", type: "line", source: "slot" });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#8a949c", "line-width": 0.4 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#3a444c", "line-width": 1.1 } });
  // the base map's national border and place labels: over the radar, under the storm cells
  for (const layer of topLayers(language)) map.addLayer(layer);
  radarCanvas = new GridCanvas("radar-canvas", "rain-canvas-slot");
  rainCanvas = new GridCanvas("rain-canvas", "okresy-line");

  map.addSource("cells", empty);
  map.addLayer({
    id: "cell-tracks", type: "line", source: "cells", filter: ["==", ["get", "kind"], "track"],
    paint: { "line-color": "#1d2329", "line-width": 1.5, "line-dasharray": [2, 2], "line-opacity": 0.7 },
  });
  map.addLayer({
    id: "cell-arrows", type: "line", source: "cells", filter: ["==", ["get", "kind"], "arrow"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": ["case", ["get", "hail"], "#b3001b", "#1d2329"], "line-width": 2.5 },
  });
  map.addLayer({
    id: "cell-points", type: "circle", source: "cells", filter: ["==", ["get", "kind"], "cell"],
    paint: {
      "circle-radius": ["case", ["get", "hail"], 9, 6],
      "circle-color": ["case", ["get", "hail"], "#ffffff", "#1d2329"],
      "circle-stroke-color": ["case", ["get", "hail"], "#d0021b", "#ffffff"],
      "circle-stroke-width": ["case", ["get", "hail"], 4, 2],
    },
  });
  applyTheme();
  for (const layer of ["cell-points", ...PLACE_LAYERS]) {
    map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }
  const around = (p, r) => [
    [p.x - r, p.y - r],
    [p.x + r, p.y + r],
  ];
  map.on("click", (event) => {
    const hit = map.queryRenderedFeatures(around(event.point, 10), { layers: ["cell-points"] })[0];
    if (hit) return showCell(hit);
    // a town label: that town's point, with its name
    const label = map.queryRenderedFeatures(around(event.point, 3), { layers: PLACE_LAYERS })[0];
    if (label?.geometry?.type === "Point") {
      const [lon, lat] = label.geometry.coordinates;
      const name = label.properties[`name:${language}`] ?? label.properties.name;
      return setPoint(lon, lat, name);
    }
    setPoint(event.lngLat.lng, event.lngLat.lat);
  });
}

const cellPopup = new Popup({ closeButton: true, maxWidth: "16rem", className: "cell-popup" });
function showCell(feature) {
  const p = feature.properties;
  const box = element("div");
  box.append(element("strong", p.hail ? `${t("radar.cell.title")} · ${t("radar.cell.hail")}` : t("radar.cell.title")));
  const dbz = Number(p.max_dbz);
  if (Number.isFinite(dbz)) {
    box.append(element("p", t("radar.cell.maxDbz", { dbz: Math.round(dbz), cat: t(`radar.cat.${categoryOf(dbzLevel(dbz), categories) ?? "drizzle"}`).toLowerCase() })));
  }
  if (p.echotop_km != null && p.echotop_km !== "null") box.append(element("p", t("radar.cell.echotop", { km: dec(legendNumber(Number(p.echotop_km))) })));
  if (p.area_km2 != null && p.area_km2 !== "null") box.append(element("p", t("radar.cell.area", { area: Math.round(Number(p.area_km2)) })));
  const speedKmh = Number(p.speed_kmh);
  box.append(
    element("p", speedKmh >= 3 ? t("radar.cell.motion", { dir: t(`radar.dir.${compass(Number(p.dir_deg))}`), speed: Math.round(speedKmh) }) : t("radar.cell.still")),
  );
  cellPopup.setLngLat(feature.geometry.coordinates).setDOMContent(box).addTo(map);
}

// --- rain at my place ------------------------------------------------------------------------
let marker = null;
let pointToken = 0;
function setPoint(lon, lat, name = null) {
  point = { lon, lat, name };
  marker ??= new Marker({ color: "#c0392b" });
  marker.setLngLat([lon, lat]).addTo(map);
  if (window.innerWidth <= 700) document.getElementById("show").open = false;
  refreshPoint();
  scrollToPanel(document.getElementById("point-panel"), true);
}

function closePoint() {
  point = null;
  marker?.remove();
  document.getElementById("point-panel").hidden = true;
  scrollToPanel(document.getElementById("point-panel"), false);
}

async function refreshPoint() {
  if (!point) return;
  const panel = document.getElementById("point-panel");
  panel.hidden = false;
  const token = ++pointToken;
  const title = element("div", null, "point-title");
  const where = { lat: dec(point.lat.toFixed(2)), lon: dec(point.lon.toFixed(2)) };
  title.append(element("strong", point.name ? t("radar.point.titlePlace", { name: point.name }) : t("radar.point.title", where)));
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("radar.point.close"));
  close.addEventListener("click", closePoint);
  title.append(close);
  if (!steps.length) {
    panel.replaceChildren(title, element("p", view.day === "live" ? t("radar.noLive") : t("radar.noDay")));
    return;
  }
  const live = view.day === "live";
  const anchor = live ? lastObserved() ?? lastTime() : steps[locate(steps, shownMs).i].time;
  const chosen = allSteps.filter((s) => s.time >= anchor - 2 * 3600000 && s.time <= anchor + 3600000 && (live || !s.forecast));
  if (panel.dataset.key !== `${point.lon},${point.lat},${point.name},${anchor}`) {
    panel.replaceChildren(title, element("p", t("radar.point.loading"), "muted"));
  }
  const decoded = await Promise.all(chosen.map((s) => frame(radarUrl(s))));
  if (token !== pointToken) return;
  const grid = decoded.find(Boolean);
  const pixel = grid && lonLatToPixel(point.lon, point.lat, boundsOf(index), grid.w, grid.h);
  if (!pixel) {
    panel.replaceChildren(title, element("p", t("radar.point.outside")));
    return;
  }
  const series = chosen
    .map((s, k) => (decoded[k] ? sample(s.time, decoded[k].codes[pixel.row * decoded[k].w + pixel.col], s.forecast) : null))
    .filter(Boolean);
  const lines = [title];
  if (live) {
    const said = nowcastSentence(series, anchor, categories);
    const cat = (key) => t(`radar.cat.${key}`);
    let text;
    if (said.key === "now") {
      text = t("radar.point.now", { cat: cat(said.cat).toLowerCase(), rate: dec(rateLabel(said.rate)) });
      if (said.then === "stops") text += ` ${t("radar.point.stops", { min: said.min })}`;
      if (said.then === "continues") text += ` ${t("radar.point.continues", { peak: cat(said.peak).toLowerCase() })}`;
    } else if (said.key === "expected") text = t("radar.point.expected", { cat: cat(said.cat), min: said.min });
    else text = t(`radar.point.${said.key}`);
    lines.push(element("p", text, `sentence ${said.key}`));
  } else lines.push(element("p", t("radar.point.archive"), "sentence"));
  lines.push(pointChart(series, anchor, live));
  lines.push(element("p", t("radar.point.note"), "muted"));
  panel.replaceChildren(...lines);
  panel.dataset.key = `${point.lon},${point.lat},${point.name},${anchor}`;
}

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs, text) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text != null) e.textContent = text;
  return e;
}

/** Bars of the class at the place (height by class, so drizzle stays visible), now line. */
function pointChart(series, anchor, live) {
  const W = 300;
  const H = 118;
  // room above the top guide for the unit, so "mm/h" does not sit on its number
  const top = 16;
  const bottom = 18;
  const left = 30;
  const first = anchor - 2 * 3600000;
  const last = anchor + 3600000;
  const x = (ms) => left + ((ms - first) / (last - first)) * (W - left - 4);
  const y = (level) => H - bottom - (level / 15) * (H - top - bottom);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": t("radar.point.chart"), class: "point-chart" });
  if (live) chart.append(svg("rect", { x: x(anchor), y: top, width: x(last) - x(anchor), height: H - top - bottom, class: "future" }));
  // mm/h guide lines at light, moderate, heavy, hail
  for (const dbz of [20, 28, 40, 56]) {
    const level = dbzLevel(dbz);
    chart.append(svg("line", { x1: left, x2: W - 4, y1: y(level), y2: y(level), class: "guide" }));
    chart.append(svg("text", { x: left - 3, y: y(level) + 3, class: "axis", "text-anchor": "end" }, dec(rateLabel(rainRate(dbz)))));
  }
  chart.append(svg("text", { x: 2, y: 9, class: "axis" }, "mm/h"));
  const barW = Math.max(2, ((W - left) / 36) * 0.8);
  const solid = maxzScale(index, null).map((r) => r[1]);
  for (const s of series) {
    if (!s.level) continue;
    const colour = s.aloft ? ALOFT_COLOURS[s.level - 1] : solid[s.level - 1] ?? "#888";
    chart.append(svg("rect", { x: x(s.time) - barW / 2, y: y(s.level), width: barW, height: y(0) - y(s.level), fill: colour, class: s.forecast ? "bar forecast" : "bar" }));
  }
  chart.append(svg("line", { x1: left, x2: W - 4, y1: y(0), y2: y(0), class: "base" }));
  chart.append(svg("line", { x1: x(anchor), x2: x(anchor), y1: top, y2: H - bottom, class: "now" }));
  if (shownMs >= first && shownMs <= last) chart.append(svg("line", { x1: x(shownMs), x2: x(shownMs), y1: top, y2: H - bottom, class: "shown" }));
  chart.append(svg("text", { x: x(first), y: H - 4, class: "axis" }, clock(first)));
  chart.append(svg("text", { x: x(anchor), y: H - 4, class: "axis", "text-anchor": "middle" }, live ? t("radar.nowMark") : clock(anchor)));
  chart.append(svg("text", { x: W - 4, y: H - 4, class: "axis", "text-anchor": "end" }, clock(last)));
  return chart;
}

// --- controls ------------------------------------------------------------------------------
const dateFormat = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", {
  weekday: "short", day: "numeric", month: language === "cs" ? "long" : "short", timeZone: "Europe/Prague",
});
const dayLong = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const shortDate = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function renderSource() {
  const source = document.getElementById("source");
  source.replaceChildren(
    ...["live", "archive"].map((kind) => {
      const button = element("button", t(`radar.${kind}`));
      button.type = "button";
      const active = kind === "live" ? view.day === "live" : view.day !== "live";
      button.setAttribute("aria-pressed", String(active));
      button.disabled = kind === "archive" && !days.length;
      button.addEventListener("click", () => {
        if (kind === "live") update({ day: "live", time: null });
        else if (view.day === "live" && days.length) update({ day: days.at(-1), time: null });
      });
      return button;
    }),
  );
  const picker = document.getElementById("day");
  document.getElementById("day-pick").hidden = view.day === "live";
  if (days.length) {
    picker.min = days[0];
    picker.max = days.at(-1);
  }
  if (view.day !== "live") picker.value = view.day;
  const range = document.getElementById("day-range");
  range.textContent = days.length
    ? `${t("radar.dayRange", { from: shortDate.format(Date.parse(days[0])), to: shortDate.format(Date.parse(days.at(-1))) })} · ${t("radar.dayHint")}`
    : t("radar.dayNone");
  document.getElementById("window").hidden = view.day !== "live";
  document.getElementById("window-hint").textContent = t("radar.hoursHint");
  const hours = document.getElementById("hours");
  hours.setAttribute("aria-label", t("radar.hoursLabel"));
  hours.replaceChildren(
    ...HOURS.map((n) => {
      const button = element("button", t("radar.hours", { n }));
      button.type = "button";
      button.setAttribute("aria-pressed", String(n === view.hours));
      button.addEventListener("click", () => update({ hours: n, time: null }));
      return button;
    }),
  );
}

function renderSpeed() {
  const group = document.getElementById("speed");
  group.setAttribute("aria-label", t("radar.speed"));
  group.replaceChildren(
    ...SPEEDS.map((s) => {
      const button = element("button", ">".repeat(SPEEDS.indexOf(s) + 1));
      button.type = "button";
      button.title = `${t("radar.speed")} ${s}×`;
      button.setAttribute("aria-label", `${t("radar.speed")} ${s}×`);
      button.setAttribute("aria-pressed", String(s === speed));
      button.addEventListener("click", () => {
        speed = s;
        store("speed2", speed);
        renderSpeed();
      });
      return button;
    }),
  );
}

function check(layer, label) {
  const wrap = element("label", null, "check");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = has(layer);
  input.addEventListener("change", () => {
    const shown = input.checked ? [...view.layers, layer] : view.layers.filter((l) => l !== layer);
    update({ layers: shown });
  });
  wrap.append(input, element("span", label));
  return wrap;
}

function renderLayers() {
  const box = document.getElementById("layers");
  const parts = [check("radar", t("radar.layer.radar"))];
  // show from
  const filter = element("label", null, "filter");
  filter.append(element("span", t("radar.filter")));
  const select = document.createElement("select");
  select.id = "filter";
  for (const key of FILTER_KEYS) {
    const option = element("option", t(`radar.filter.${key}`));
    option.value = key;
    option.selected = key === view.filter;
    select.append(option);
  }
  select.addEventListener("change", () => {
    store("filter", select.value);
    update({ filter: select.value });
  });
  filter.append(select);
  parts.push(filter);
  parts.push(check("rain", t("radar.layer.rain")));
  if (index?.echotop?.length) parts.push(check("echotop", t("radar.layer.echotop")));
  if (index?.cells?.length) parts.push(check("cells", t("radar.layer.cells")));
  const products = Object.entries(index?.satellite ?? {}).filter(([, m]) => m?.frames?.length).map(([p]) => p);
  if (products.length) {
    const sat = element("div", null, "sat-row");
    sat.append(element("span", t("radar.sat")));
    const group = element("span", null, "segmented small");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", t("radar.sat"));
    const current = has("wv") ? "wv" : has("sat") ? "sat" : "off";
    for (const mode of ["off", "sat", "wv"]) {
      if (mode === "wv" && !products.includes("wv062")) continue;
      const button = element("button", t(`radar.sat.${mode}`));
      button.type = "button";
      button.setAttribute("aria-pressed", String(mode === current));
      button.addEventListener("click", () => {
        const rest = view.layers.filter((l) => !SAT_LAYERS.includes(l));
        update({ layers: mode === "off" ? rest : [...rest, mode] });
      });
      group.append(button);
    }
    sat.append(group);
    if (current !== "off") {
      const opacity = document.createElement("input");
      opacity.type = "range";
      opacity.min = "0.2";
      opacity.max = "1";
      opacity.step = "0.05";
      opacity.value = String(satOpacity);
      opacity.setAttribute("aria-label", t("radar.sat.opacity"));
      opacity.title = t("radar.sat.opacity");
      opacity.addEventListener("input", () => {
        satOpacity = Number(opacity.value);
        store("satOpacity", satOpacity);
        drawSatellite();
      });
      sat.append(opacity);
    }
    parts.push(sat);
  }
  if (view.day !== "live" && (!products.length || !index?.cells?.length)) parts.push(element("p", t("radar.notAvailable"), "note"));
  box.replaceChildren(...parts);
  renderLegend();
}

function renderLegend() {
  const legend = document.getElementById("radar-legend");
  const parts = [];
  const f = filterLevels(view.filter, categories);
  if (has("radar")) {
    const box = element("div", null, "radar-legend-box");
    box.append(element("strong", t("radar.legendRadar")));
    const labels = { en: {}, cs: {} };
    for (const key of ["drizzle", "light", "moderate", "heavy", "veryHeavy", "hail"]) labels.en[key] = labels.cs[key] = t(`radar.cat.${key}`);
    // our words for the labels we know (the same as in the sentences), the backend's otherwise
    const scale = maxzScale(index, labels).map((row) => {
      const key = labelKey(row[3]);
      return key ? [row[0], row[1], row[2], labels.en[key], labels.cs[key]] : row;
    });
    const rows = legendRows(scale, language);
    const list = element("ul", null, "legend-rows");
    for (const row of rows) {
      const item = element("li");
      // every class of the row below the "show from" setting
      if (row.dbzTo != null && dbzLevel(row.dbzTo) <= f.radar) item.className = "off";
      const swatch = element("span", null, "swatch");
      swatch.style.background = row.colours.length > 1 ? `linear-gradient(90deg, ${row.colours.join(", ")})` : row.colours[0];
      swatch.title = `${row.dbz}${row.dbzTo ? `–${row.dbzTo}` : "+"} dBZ`;
      const words = element("span", row.label.charAt(0).toUpperCase() + row.label.slice(1), "words");
      const mm = element("span", row.to != null ? t("radar.range", { from: dec(rateLabel(row.from)), to: dec(rateLabel(row.to)) }) : t("radar.rangeTop", { from: dec(rateLabel(row.from)) }), "mm");
      item.append(swatch, words, mm);
      list.append(item);
    }
    box.append(list);
    const aloft = element("p", null, f.aloft ? "aloft" : "aloft off");
    const swatch = element("span", null, "swatch");
    swatch.style.background = `linear-gradient(90deg, ${ALOFT_COLOURS.slice(0, 12).join(", ")})`;
    aloft.append(swatch, element("span", t("radar.aloft")));
    box.append(aloft);
    if (view.filter !== "all") box.append(element("p", t("radar.filterNote", { mm: dec(legendNumber(MM_SCALE[f.rain - 1][0])) }), "note strong"));
    box.append(element("p", `${t("radar.winter")} ${t("radar.dbz")}`, "note"));
    parts.push(box);
  }
  if (has("rain")) {
    parts.push(scaleBar(simpleScale(index, "merge1h", MM_SCALE), `${t("radar.legendRain")} (mm)`, (v) => dec(legendNumber(v))));
    parts.push(element("p", t("radar.rainExplain"), "note"));
  }
  if (has("echotop") && index?.echotop?.length) {
    const echotop = simpleScale(index, "echotop", null);
    if (echotop) parts.push(scaleBar(echotop, t("radar.legendEchotop"), (v) => dec(legendNumber(v))));
    parts.push(element("p", t("radar.echotopExplain"), "note"));
  }
  if (has("cells") && index?.cells?.length) parts.push(element("p", t("radar.cellsExplain"), "note"));
  const sat = satelliteInfo();
  if (sat) parts.push(element("p", t(`radar.sat.product.${sat.product}`), "note"));
  legend.replaceChildren(...parts);
}

/** A horizontal colour bar with the lower bound of each colour under it. */
function scaleBar(colours, unit, label) {
  const box = element("div", null, "radar-scale");
  const bar = element("div", null, "bar");
  const numbers = element("div", null, "numbers");
  bar.style.gridTemplateColumns = `repeat(${colours.length}, 1fr)`;
  numbers.style.gridTemplateColumns = `repeat(${colours.length}, 1fr)`;
  for (const [value, colour] of colours) {
    const cell = element("span");
    cell.style.background = colour;
    cell.title = label(value);
    bar.append(cell);
    numbers.append(element("span", label(value)));
  }
  box.append(element("strong", unit), bar, numbers);
  return box;
}

function renderPointHint() {
  const hint = document.getElementById("point-hint");
  hint.replaceChildren(element("span", `${t("radar.point.hint")} `), placeSearch({ t, load: loadPlaces, choose: choosePlace }));
}

// --- find a place: every obec with its okres (places.js, data/obce.json) --------------------
const loadPlaces = placesLoader(placesUrl);

/** Choose a place: the rain-at-a-place point, as a click there would; the map moves only
 * when the place is outside the view. */
function choosePlace(place) {
  setPoint(place.lon, place.lat, placeLabel(place));
  if (!map.getBounds().contains([place.lon, place.lat])) map.easeTo({ center: [place.lon, place.lat] });
}

/** Percent position on the timeline, corrected for the 16 px thumb of the range input. */
function trackPosition(ms) {
  const span = lastTime() - firstTime();
  const p = span > 0 ? (ms - firstTime()) / span : 0;
  return `calc(${(p * 100).toFixed(3)}% + ${((0.5 - p) * 16).toFixed(1)}px)`;
}

function renderTimeline() {
  const slider = document.getElementById("time");
  const span = Math.round((lastTime() - firstTime()) / MINUTE);
  slider.max = String(Math.max(span, 0));
  slider.disabled = steps.length < 2;
  const ticks = document.getElementById("ticks");
  const labels = document.getElementById("tick-labels");
  ticks.replaceChildren();
  labels.replaceChildren();
  if (steps.length < 2) return;
  const observed = lastObserved();
  if (observed != null && observed < lastTime()) {
    const zone = element("span", null, "forecast-zone");
    zone.style.left = trackPosition(observed);
    zone.style.right = "0";
    ticks.append(zone);
  }
  // the frames themselves, as small dots
  for (const s of steps) {
    const dot = element("span", null, s.forecast ? "frame forecast" : "frame");
    dot.style.left = trackPosition(s.time);
    ticks.append(dot);
  }
  const maxLabels = window.innerWidth <= 500 ? 4 : 8;
  for (const tick of hourTicks(firstTime(), lastTime(), maxLabels)) {
    const mark = element("span", null, "hour");
    mark.style.left = trackPosition(tick.ms);
    ticks.append(mark);
    const label = element("span", `${String(tick.hour).padStart(2, "0")}:00`, "hour-label");
    label.style.left = trackPosition(tick.ms);
    labels.append(label);
  }
  if (view.day === "live") {
    const now = Math.min(lastTime(), Math.max(firstTime(), Date.now()));
    const mark = element("span", null, "now");
    mark.style.left = trackPosition(now);
    ticks.append(mark);
    const label = element("span", t("radar.nowMark"), "now-label");
    label.style.left = trackPosition(now);
    ticks.append(label);
  }
}

function relLabel(ms) {
  const r = relativeTime(ms, Date.now());
  return t(`radar.rel.${r.key}`, { n: r.n });
}

/** The big time label, the slider, the headline: what the map shows right now. */
function renderWhen() {
  const slider = document.getElementById("time");
  const clockEl = document.getElementById("clock");
  const date = document.getElementById("date");
  const rel = document.getElementById("rel");
  const kind = document.getElementById("kind");
  const headline = document.getElementById("headline");
  if (!steps.length || shownMs == null) {
    for (const e of [clockEl, date, rel, kind]) e.textContent = "";
    kind.hidden = true;
    headline.replaceChildren(element("p", view.day === "live" ? t("radar.noLive") : t("radar.noDay")));
    document.body.classList.remove("forecast");
    return;
  }
  kind.hidden = false;
  if (!slider.matches(":active")) slider.value = String(Math.round((shownMs - firstTime()) / MINUTE));
  const forecast = isForecastTime();
  const { i } = locate(steps, shownMs);
  const lead = forecast ? Math.round((shownMs - lastObserved()) / MINUTE) : 0;
  clockEl.textContent = clock(shownMs);
  date.textContent = dateFormat.format(shownMs);
  const sinceNow = Date.now() - shownMs;
  rel.textContent = Math.abs(sinceNow) < 2 * 86400000 ? relLabel(shownMs) : "";
  kind.textContent = forecast ? t("radar.forecast", { lead }) : t("radar.measured");
  kind.className = forecast ? "badge forecast" : "badge";
  slider.setAttribute("aria-valuetext", `${clock(shownMs)} ${date.textContent}, ${kind.textContent}`);
  document.body.classList.toggle("forecast", forecast);

  // headline on the map: what, and how fresh the data are
  const lines = [];
  const h2 = element("h2");
  h2.append(element("span", clock(shownMs)), element("span", forecast ? t("radar.forecastShort") : t("radar.measured"), forecast ? "badge forecast" : "badge"));
  lines.push(h2);
  if (forecast && index?.nowcast?.base) lines.push(element("p", t("radar.forecastNote", { time: clock(parseStamp(index.nowcast.base)) }), "line"));
  if (has("radar") && hiddenByFilter) lines.push(element("p", t("radar.allHidden"), "line warning"));
  if (has("rain")) {
    const current = steps[i];
    lines.push(element("p", current?.rain ? t("radar.rainAt", { time: clock(parseStamp(current.rain)) }) : t("radar.rainNone"), "line"));
  }
  const sat = has("sat") || has("wv") ? satelliteInfo() : null;
  if (sat && !sat.around) lines.push(element("p", t("radar.sat.none"), "line muted"));
  else if (sat?.around) lines.push(element("p", t("radar.sat.at", { time: clock(parseStamp(sat.around.tau >= 0.5 && sat.around.b ? sat.around.b : sat.around.a)) }), "line muted"));
  if (view.day === "live") {
    const observed = lastObserved();
    if (observed != null) {
      const age = minutesBetween(observed, Date.now());
      const fresh = element("p", t("radar.newest", { time: clock(observed), ago: t("radar.ago", { min: age }) }), age > STALE_MIN ? "line fresh stale" : "line fresh");
      lines.push(fresh);
      if (age > STALE_MIN) lines.push(element("p", t("radar.stale", { min: age }), "line warning"));
    }
  }
  lines.push(element("p", t("radar.prague"), "line muted"));
  headline.replaceChildren(...lines);
}

function renderStatus() {
  const status = document.getElementById("status");
  status.classList.remove("stale");
  if (view.day !== "live") {
    status.textContent = t("radar.statusDay", { day: dayLong.format(new Date(`${view.day}T12:00:00Z`)) });
    return;
  }
  const observed = lastObserved();
  if (observed == null) {
    status.textContent = t("radar.noLive");
    return;
  }
  const age = minutesBetween(observed, Date.now());
  status.textContent = t("radar.status", { time: clock(observed), ago: t("radar.ago", { min: age }) });
  status.classList.toggle("stale", age > STALE_MIN);
}

function renderPlay() {
  const button = document.getElementById("play");
  button.textContent = playing ? t("radar.pause") : t("radar.play");
  button.setAttribute("aria-pressed", String(playing));
  button.disabled = steps.length < 2;
}

// Back/Forward and a link pasted on the open page show that view; another day (live or an
// archived one) is a step in the history, the other choices replace the current entry
const address = hashHistory((hash) => {
  const next = parseView(hash);
  next.filter = parseFilter(next.filter ?? view.filter);
  if (viewHash(next) !== viewHash(view)) update(next, false);
  else writeHash(); // the same view: the address as the page writes it
});

function writeHash(push = false) {
  const time = !playing && shownMs != null && steps.length && shownMs !== lastObserved() && !isForecastTime() ? toStamp(shownMs) : null;
  view.time = time;
  address.write(viewHash({ ...view, time }), push);
}

// --- state ----------------------------------------------------------------------------
// only the latest load applies, and a failed refresh keeps what is shown
let loadToken = 0;
async function load(fresh = false) {
  const token = ++loadToken;
  const day = view.day;
  const nextBase = sourceUrl(day, LIVE);
  // a day missing from the archive's list (typed into the date field): no request, the page says there are no images
  const archived = day === "live" || !days.length || days.includes(day);
  const next = !archived ? null : day === "live" ? await getJson(`${nextBase}index.json`, fresh) : await loadPragueDay(day);
  if (token !== loadToken) return false;
  if (!next && fresh && nextBase === base && index) return false;
  base = nextBase;
  sourceDay = day;
  index = next;
  steps = timeline(index, { hours: view.day === "live" ? view.hours : null });
  allSteps = timeline(index);
  cellsData = new Map();
  motions.clear();
  motionReady.clear();
  flows.clear();
  makeLuts();
  return true;
}

/** An archived day as a day in Prague (radar.js pragueDayIndex): its UTC folder's index and the day before's. */
async function loadPragueDay(day) {
  const before = previousDay(day);
  const [own, earlier] = await Promise.all([
    getJson(`${sourceUrl(day, LIVE)}index.json`),
    days.includes(before) ? getJson(`${sourceUrl(before, LIVE)}index.json`) : null,
  ]);
  return pragueDayIndex(own, earlier, pragueDayWindow(day));
}

function initialTime() {
  if (!steps.length) return null;
  const wanted = view.time ? parseStamp(view.time) : null;
  const at = wanted ?? lastObserved() ?? lastTime();
  return Math.min(lastTime(), Math.max(firstTime(), quantize(at)));
}

/** Apply a change of the view; `step`: another day is a new history entry (false for Back/Forward). */
async function update(change, step = true) {
  const reload = "day" in change || "hours" in change;
  const push = step && "day" in change && change.day !== view.day;
  view = { ...view, ...change };
  view.filter = parseFilter(view.filter);
  if (reload) {
    stop();
    if (!(await load())) return;
    shownMs = initialTime();
  }
  if ("filter" in change && !reload) makeLuts();
  renderSource();
  renderLayers();
  renderTimeline();
  renderStatus();
  renderPlay();
  if (!drawAll()) requestDraw();
  writeHash(push);
  if (reload || "filter" in change) refreshPoint();
}

document.getElementById("play").addEventListener("click", play);
const slider = document.getElementById("time");
slider.addEventListener("input", () => goTo(firstTime() + Number(slider.value) * MINUTE));
slider.addEventListener("change", () => refreshPoint());
document.getElementById("day").addEventListener("change", (event) => {
  if (event.target.value) update({ day: event.target.value, time: null });
});

// keyboard: space plays, arrows step by frame, Home/End jump to the first frame / now
document.addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.target;
  const tag = target?.tagName;
  const onSlider = target === slider;
  const typing = (tag === "INPUT" && !onSlider && target.type !== "checkbox") || tag === "SELECT" || tag === "TEXTAREA" || target?.isContentEditable;
  if (typing) return;
  if (event.key === " " || event.code === "Space") {
    if (tag === "BUTTON" || tag === "SUMMARY" || (tag === "INPUT" && target.type === "checkbox")) return;
    event.preventDefault();
    play();
  } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    if (!onSlider && tag === "INPUT") return;
    event.preventDefault();
    stepBy(event.key === "ArrowLeft" ? -1 : 1);
  } else if (event.key === "Home" || event.key === "End") {
    if (!onSlider && tag === "INPUT") return;
    event.preventDefault();
    goTo(event.key === "Home" ? firstTime() : lastObserved() ?? lastTime());
  }
});

// a frame went missing: reload the frame list (at most every 20 s)
let refreshTimer = null;
let lastRefresh = 0;
function refreshSoon() {
  if (refreshTimer || view.day !== "live") return;
  const wait = Math.max(0, 20000 - (Date.now() - lastRefresh));
  refreshTimer = setTimeout(async () => {
    refreshTimer = null;
    lastRefresh = Date.now();
    const keep = shownMs;
    if (!(await load(true))) return;
    for (const url of failed) frames.delete(url);
    failed.clear();
    shownMs = Math.min(lastTime(), Math.max(firstTime(), keep ?? initialTime()));
    renderTimeline();
    renderStatus();
    requestDraw();
  }, wait);
}

// keep the live view current; a viewer at "now" stays at now
setInterval(async () => {
  if (view.day !== "live" || playing) return;
  const atNow = shownMs === quantize(lastObserved() ?? 0);
  if (!(await load(true))) return;
  if (atNow || shownMs == null) shownMs = initialTime();
  shownMs = Math.min(lastTime(), Math.max(firstTime(), shownMs));
  if (atNow) shownMs = quantize(lastObserved() ?? lastTime());
  renderLayers();
  renderTimeline();
  renderStatus();
  requestDraw();
  refreshPoint();
}, REFRESH_MS);
// the age of the newest frame
setInterval(() => {
  renderStatus();
  if (!playing) renderWhen();
}, 30000);

async function main() {
  renderSpeed();
  renderPointHint();
  const [, daysJson] = await Promise.all([mapLoaded, getJson("radar/days.json")]);
  days = Array.isArray(daysJson) ? daysJson : [];
  // phones: the box starts folded so the map stays visible
  if (window.innerWidth <= 700) document.getElementById("show").open = false;
  // the credits folded behind (i) at every width (they are in full in the footer too), as on
  // the heatmap: open they wrap to two lines up to ~1100 px and run under the legend and the
  // point panel, and on phones they cover a third of the map
  map.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
  addLayers();
  await update({ day: view.day });
  window.addEventListener("resize", () => renderTimeline());
  // opens on the frame "now" and does not play until the play button is pressed
}

main();

// for tests in a headless browser: jump to a time / play
/** Draw every minute of the shown window once, synchronously: frame times for a report. */
async function bench(scale = perf.scale) {
  stop();
  await Promise.all(steps.map((s) => frame(radarUrl(s))));
  await Promise.all((index?.motion ?? []).map((m) => motion(m)));
  const saved = [perf.scale, shownMs];
  perf.scale = scale;
  const times = [];
  for (let ms = firstTime(); ms <= lastTime(); ms += MINUTE) {
    shownMs = ms;
    const start = performance.now();
    drawRadar();
    times.push(performance.now() - start);
  }
  [perf.scale, shownMs] = saved;
  requestDraw();
  times.sort((a, b) => a - b);
  return { n: times.length, median: times[times.length >> 1], p95: times[Math.floor(times.length * 0.95)], max: times.at(-1) };
}

// for checks in a browser: jump to a time, play, place a point, measure
window.__radar = { map, goTo, play, stop, setPoint, bench, state: () => ({ shownMs, playing, steps: steps.length, perf }) };
