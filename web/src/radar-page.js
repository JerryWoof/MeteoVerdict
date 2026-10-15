import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { setUpLanguage } from "./i18n.js";
import {
  DBZ_SCALE, HOURS, LAYERS, MM_SCALE, boundsOf, clock, closestStep, frameUrl, imageCoordinates,
  legendNumber, localDay, minutesBetween, parseStamp, parseView, rainRate, sourceUrl, timeline,
  viewHash,
} from "./radar.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();

// Live frames: the branch radar-live (force-pushed by the Radar workflow every ~10 min),
// served with CORS by raw.githubusercontent.com (cached about 5 min). Archived days:
// radar/days/YYYYMMDD/ on this site (from the releases radar-YYYY-MM, see pages.yml).
const LIVE = import.meta.env.VITE_RADAR_LIVE ?? "https://raw.githubusercontent.com/JerryWoof/MeteoVerdict/radar-live/";
const FRAME_MS = 400; // animation speed
const REFRESH_MS = 5 * 60 * 1000;
const FOLDER = { radar: "maxz", rain: "merge1h" };

const map = new MapLibreMap({
  container: "map",
  style: {
    version: 8,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": "#f4f1ea" } }],
  },
  bounds: [
    [12.0, 48.5],
    [18.95, 51.1],
  ],
  fitBoundsOptions: { padding: 20 },
  attributionControl: { customAttribution: "Radar: ČHMÚ (CC BY 4.0) · Boundaries: ČÚZK (CC BY 4.0)" },
});
map.addControl(new NavigationControl({ showCompass: false }));
const mapLoaded = new Promise((resolve) => map.on("load", resolve));

let view = parseView(window.location.hash);
let index = null; // index.json of the shown source
let base = null; // its folder
let steps = [];
let step = -1;
let playing = null;
let days = [];

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

// --- map layers ---------------------------------------------------------------------
function addBoundaries() {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({ id: "okresy-fill", type: "fill", source: "okresy", paint: { "fill-color": "#ececec", "fill-opacity": 0.6 } });
  // radar layers go here, under the lines
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#8a949c", "line-width": 0.4 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#3a444c", "line-width": 1.1 } });
}

/** Show `url` in the raster layer `name` (created on first use), or hide it. */
function showImage(name, url, opacity) {
  const id = `${name}-image`;
  const source = map.getSource(id);
  if (!url) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
    return;
  }
  if (!source) {
    map.addSource(id, { type: "image", url, coordinates: imageCoordinates(boundsOf(index)) });
    map.addLayer(
      { id, type: "raster", source: id, paint: { "raster-opacity": opacity, "raster-fade-duration": 0 } },
      "okresy-line",
    );
  } else {
    source.updateImage({ url, coordinates: imageCoordinates(boundsOf(index)) });
    map.setPaintProperty(id, "raster-opacity", opacity);
    map.setLayoutProperty(id, "visibility", "visible");
  }
}

const preloaded = new Set();
function preload(url) {
  if (!url || preloaded.has(url)) return;
  preloaded.add(url);
  const image = new Image();
  image.src = url;
}

// --- rendering --------------------------------------------------------------------
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
  picker.hidden = view.day === "live";
  if (days.length) {
    picker.min = days[0];
    picker.max = days.at(-1);
  }
  if (view.day !== "live") picker.value = view.day;
  const hours = document.getElementById("hours");
  hours.hidden = view.day !== "live";
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

function renderLayers() {
  const box = document.getElementById("layers");
  box.replaceChildren(
    ...LAYERS.map((layer) => {
      const label = element("label", null, "check");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = view.layers.includes(layer);
      input.addEventListener("change", () => {
        const shown = input.checked ? [...view.layers, layer] : view.layers.filter((l) => l !== layer);
        update({ layers: LAYERS.filter((l) => shown.includes(l)) });
      });
      label.append(input, element("span", t(`radar.layer.${layer}`)));
      return label;
    }),
  );
  const legend = document.getElementById("radar-legend");
  legend.replaceChildren();
  if (view.layers.includes("radar")) legend.append(scale(DBZ_SCALE, t("radar.legendRadar"), (v) => `${v}`, true));
  if (view.layers.includes("rain")) legend.append(scale(MM_SCALE, t("radar.legendRain"), legendNumber, false));
  if (view.layers.includes("radar")) legend.append(element("p", t("radar.masked"), "note"));
}

/** A horizontal colour bar with the lower bound of each colour under it. */
function scale(colours, unit, label, withRate) {
  const box = element("div", null, "radar-scale");
  const bar = element("div", null, "bar");
  const numbers = element("div", null, "numbers");
  for (const [value, colour] of colours) {
    const cell = element("span");
    cell.style.background = colour;
    cell.title = withRate ? `${value} dBZ ≈ ${legendNumber(rainRate(value))} ${t("radar.rate")}` : `${legendNumber(value)} mm`;
    bar.append(cell);
    numbers.append(element("span", label(value)));
  }
  box.append(element("strong", unit), bar, numbers);
  return box;
}

function renderTicks() {
  const ticks = document.getElementById("ticks");
  ticks.replaceChildren();
  if (steps.length < 2) return;
  const first = steps[0].time;
  const span = steps.at(-1).time - first;
  const nowcast = steps.findIndex((s) => s.forecast);
  if (nowcast > 0) {
    const zone = element("span", null, "forecast-zone");
    zone.style.left = `${((steps[nowcast - 1].time - first) / span) * 100}%`;
    zone.style.right = "0";
    ticks.append(zone);
  }
}

function renderStep() {
  const slider = document.getElementById("time");
  slider.max = String(Math.max(steps.length - 1, 0));
  slider.value = String(Math.max(step, 0));
  slider.disabled = steps.length < 2;
  const output = document.getElementById("clock");
  const headline = document.getElementById("headline");
  const current = steps[step];
  document.body.classList.toggle("forecast", Boolean(current?.forecast));
  if (!current) {
    output.textContent = "";
    headline.replaceChildren(element("p", view.day === "live" ? t("radar.noLive") : t("radar.noDay")));
    showImage("radar", null);
    showImage("rain", null);
    return;
  }
  output.textContent = `${clock(current.time)}`;
  const lines = [element("h2", `${clock(current.time)} · ${current.forecast ? "" : localDay(current.time)}`.replace(/ · $/, ""))];
  const badge = element("span", current.forecast ? t("radar.forecast", { lead: current.lead }) : t("radar.measured"), current.forecast ? "badge forecast" : "badge");
  lines.push(badge);
  if (current.forecast) {
    lines.push(element("p", t("radar.forecastNote", { time: clock(parseStamp(index.nowcast.base)) }), "line"));
  }
  if (view.layers.includes("rain")) {
    lines.push(element("p", current.rain ? t("radar.rainAt", { time: clock(parseStamp(current.rain)) }) : t("radar.rainNone"), "line"));
  }
  lines.push(element("p", t("radar.prague"), "line muted"));
  headline.replaceChildren(...lines);

  const folder = current.forecast ? "nowcast" : FOLDER.radar;
  showImage("radar", view.layers.includes("radar") ? frameUrl(base, folder, current.radar) : null, current.forecast ? 0.7 : 0.85);
  showImage("rain", view.layers.includes("rain") && current.rain ? frameUrl(base, FOLDER.rain, current.rain) : null, 0.8);
  // the next frames, for a smooth animation
  for (const next of steps.slice(step + 1, step + 4)) {
    if (view.layers.includes("radar")) preload(frameUrl(base, next.forecast ? "nowcast" : FOLDER.radar, next.radar));
    if (view.layers.includes("rain") && next.rain) preload(frameUrl(base, FOLDER.rain, next.rain));
  }
}

function renderStatus() {
  const status = document.getElementById("status");
  if (view.day !== "live") {
    status.textContent = t("radar.statusDay", { day: view.day });
    return;
  }
  const last = steps.findLast((s) => !s.forecast);
  status.textContent = last
    ? t("radar.status", { time: clock(last.time), ago: t("radar.ago", { min: minutesBetween(last.time, Date.now()) }) })
    : t("radar.noLive");
}

function renderPlay() {
  const button = document.getElementById("play");
  button.textContent = playing ? t("radar.pause") : t("radar.play");
  button.setAttribute("aria-pressed", String(Boolean(playing)));
  button.disabled = steps.length < 2;
}

function writeHash() {
  const time = view.time && step >= 0 && !steps[step]?.forecast ? steps[step].radar : null;
  history.replaceState(null, "", viewHash({ ...view, time }));
}

// --- state ----------------------------------------------------------------------
async function load(fresh = false) {
  base = sourceUrl(view.day, LIVE);
  index = await getJson(`${base}index.json`, fresh);
  steps = timeline(index, { hours: view.day === "live" ? view.hours : null });
  step = closestStep(steps, view.time ? parseStamp(view.time) : null);
}

async function update(change) {
  const reload = "day" in change || "hours" in change;
  view = { ...view, ...change };
  if (reload) {
    stop();
    await load();
  }
  renderSource();
  renderLayers();
  renderTicks();
  renderStep();
  renderStatus();
  renderPlay();
  writeHash();
}

function stop() {
  if (playing) clearInterval(playing);
  playing = null;
}

function play() {
  if (playing) {
    stop();
    renderPlay();
    return;
  }
  if (step >= steps.length - 1) step = -1;
  playing = setInterval(() => {
    step = step >= steps.length - 1 ? 0 : step + 1;
    renderStep();
  }, FRAME_MS);
  renderPlay();
}

document.getElementById("play").addEventListener("click", play);
document.getElementById("time").addEventListener("input", (event) => {
  stop();
  step = Number(event.target.value);
  view.time = steps[step]?.forecast ? null : steps[step]?.radar;
  renderStep();
  renderPlay();
  writeHash();
});
document.getElementById("day").addEventListener("change", (event) => {
  if (event.target.value) update({ day: event.target.value, time: null });
});
window.addEventListener("hashchange", () => {
  const next = parseView(window.location.hash);
  if (viewHash(next) !== viewHash({ ...view, time: view.time })) update(next);
});

// keep the live view current; a viewer at "now" stays at now
setInterval(async () => {
  if (view.day !== "live" || playing) return;
  const atNow = step === closestStep(steps, null);
  await load(true);
  if (atNow) step = closestStep(steps, null);
  renderTicks();
  renderStep();
  renderStatus();
}, REFRESH_MS);

async function main() {
  const [, daysJson] = await Promise.all([mapLoaded, getJson("radar/days.json")]);
  days = Array.isArray(daysJson) ? daysJson : [];
  // phones: the box starts folded so the map stays visible
  if (window.innerWidth <= 700) document.getElementById("show").open = false;
  addBoundaries();
  await update({ day: view.day });
}

main();
