import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";
import "./fit-map.js";

import { COMBINED, weightTable } from "./forecast.js";
import { drawIcon, glyph, iconCanvas } from "./icons.js";
import { setUpLanguage } from "./i18n.js";
import { addLocateControl } from "./locate-control.js";
import { OUTSIDE_KM, nearestPlace } from "./home-place.js";
import { mapModelOptions, modelHorizon, modelPeriods, modelSymbol, parseModelParts, parseModels } from "./models.js";
import { MIN_ZOOM, addObceLayers, goToObec, nearestObec, obceDrawn, obcePartRows, paintObce } from "./obce-map.js";
import { obceFor } from "./obce-test.js";
import { placeSearch } from "./place-search.js";
import { placesLoader } from "./places.js";
import placesUrl from "./data/obce.json?url";
import { renderScale } from "./palette.js";
import { BASEMAP_ATTRIBUTION, BASEMAP_SPEC, GLYPHS, baseLayers, basemapSources, topLayers } from "./radar-basemap.js";
import { EDGE, INK, KRAJE, PAGE_BG, pick, themeMap } from "./map-theme.js";
import { onThemeChange } from "./theme.js";
import { fillPicker, issuedText } from "./picker.js";
import {
  COLOURS, LAYERS, NEUTRAL, PARTS, RAMPS, currentPart, dayLabel, displayName, ease,
  iconName, labelFor, lerpRow, mixColor, okresColours, parseOutlook, parseView,
  placeMarkers, playSteps, rampKey, rangeText, rowFor, startIndex, sunFor, sunRange, switchColours, summary,
  today, viewHash, gustOver, gustOverText, chmiNotice, CAPITALS, historyMode, leaveFor, measuredRedirect,
} from "./tv.js";
import { keepRoomForPanels, panelRoom, scrollToPanel, userMoved } from "./panel-room.js";
import { aiPath } from "./ai-source.js";
import { seatName, seatOkres } from "./seats.js";
import { AI_MODEL, aiMapView, aiPeriods, hasAi, loadAi, withAi } from "./ai-model.js";
setWorkerUrl(workerUrl);
const t = setUpLanguage();
const DETAIL = "forecast-detail.html";
const language = document.documentElement.lang;

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
// from this zoom the base map shows under the okres colours
const BASE_ZOOM = 7.5;
// the okres colours: solid at the country's zoom, see-through over the base map
// (and fainter still where the obce are drawn)
const FILL_OPACITY = ["step", ["zoom"], 0.85, BASE_ZOOM, 0.45, MIN_ZOOM, 0.2];
// hours of each part of the day, shown under its name
const HOURS = { night: "0–6", morning: "6–12", afternoon: "12–18", evening: "18–24", day: "0–24" };

// the detailed forecast per okres used to live at forecast.html#CZ0423 (now
// forecast-detail.html), the past days moved to the measured page: such links open there
// (also when pasted into the address bar of the open page, see applyHash)
const elsewhere = leaveFor(window.location.hash, today(Date.now()));
if (elsewhere) window.location.replace(elsewhere);

const map = new MapLibreMap({
  container: "map",
  // zoomed in, the radar page's base map (relief, water, rivers, main roads) under the okres
  // colours, which turn see-through, so a place is easier to find; at the country's zoom
  // nothing of it is drawn or loaded
  style: {
    version: 8,
    glyphs: GLYPHS,
    sources: basemapSources(),
    layers: [
      { id: "background", type: "background", paint: { "background-color": pick(PAGE_BG) } },
      ...baseLayers()
        .filter((layer) => layer.type !== "background")
        .map((layer) => ({ ...layer, minzoom: Math.max(layer.minzoom ?? 0, BASE_ZOOM) })),
    ],
  },
  bounds: BOUNDS,
  fitBoundsOptions: { padding: 20 },
  attributionControl: { customAttribution: `Boundaries: ČÚZK (CC BY 4.0) · ${BASEMAP_ATTRIBUTION}` },
});
// the map grows with a long okres panel (it shares a grid cell with it): keep it drawn
new ResizeObserver(() => map.resize()).observe(map.getContainer());
keepRoomForPanels(map.getContainer().parentElement, map.getContainer(), [document.getElementById("okres-panel")]);
map.addControl(new NavigationControl({ showCompass: false }));
const applyTheme = themeMap(map, {
  ...BASEMAP_SPEC,
  background: { "background-color": PAGE_BG },
  "okresy-line": { "line-color": EDGE },
  "kraje-line": { "line-color": KRAJE },
  "okres-selected": { "line-color": INK },
});
// the obce's value colours are data (computed per theme): draw them again
onThemeChange(() => paintObce(map, obceShown() ? obceDocs : [], state, panelObec));
// my location: the obec nearest to the position, selected with its panel open (as a search)
addLocateControl(map, {
  t,
  places: () => loadPlaces(),
  onFix: async ({ lat, lon, places }) => {
    await mapLoaded; // the layers are there once the map has loaded (a click before it is possible)
    await chooseObec(nearestPlace(places, lat, lon, OUTSIDE_KM));
  },
});
// registered at once: the map may finish loading while the forecast is still on its way
const mapLoaded = new Promise((resolve) => map.on("load", resolve));
// on a phone the attribution (compact there) starts open and covers half the map: fold it
mapLoaded.then(() => {
  if (window.innerWidth <= 700) map.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
});

async function fetchJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const getJson = fetchJson;

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

// in the page language: "7,4" in Czech
const fmt = (v, digits = 0) =>
  v == null ? "–" : v.toLocaleString(document.documentElement.lang || "en", { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false });
const percent = (p) => (p == null ? "–" : `${Math.round(p * 100)} %`);
const symbolText = (symbol) => (symbol ? t(`symbol.${symbol}`) : "");

// --- state, kept in the URL (tv.js parseView / viewHash) ----------------------------
let state = { day: null, part: null, colour: "temperature", shown: [], okres: null };
// test: the obce of the okresy loaded so far (those zoomed into): okres → {doc, rows}, or
// null without a file; obceDocs: the loaded ones (obce-map.js)
const obceLoaded = new Map(); // "blend|<okres>" or "ai|<okres>" → {doc, rows} or null
let obceDocs = [];
// the obce follow the map's model: MeteoVerdict AI's own obce files while the AI is shown
// (our blend's where an okres has none), our blend's with the combination; no other model has any
const obceSrc = () => (mapModel === AI_MODEL ? "ai" : "blend");
const obceShown = () => mapModel === COMBINED || mapModel === AI_MODEL;
const obceKey = (code) => `${obceSrc()}|${code}`;
const refreshObceDocs = () => {
  obceDocs = [...obceLoaded].filter(([key, v]) => v && key.startsWith(`${obceSrc()}|`)).map(([, v]) => v);
};
// test: the obec whose panel is open (in place of its okres's), or null
let panelObec = null;
let playing = null; // "day" or "week" while playing

// --- which forecast the whole map shows: our combination (outlook.json) or one model's
// raw forecast (forecast/models-parts/<model>.json, all okresy). Not remembered: no
// storage and nothing in the URL, every page load starts on MeteoVerdict AI when it is offered
// (fresh file), else on the combination.
let mapModel = COMBINED;
let mapView = null; // parseModelParts of mapModel while it is shown
let mapStatus = null; // null, {loading: model} or {failed: model}
let mapToken = 0;
let modelIndex = null; // forecast/models-parts/index.json
let modelNames = {}; // meta.json models
let aiData = null; // MeteoVerdict AI as one more model (ai-model.js); null: not offered (missing or stale)
let mapChosen = false; // the user picked a map model: the AI default no longer applies
const modelViews = new Map(); // model → parsed file (loaded once)
let mapReady = false; // the selector works once the map has its layers

/** The panel of an okres starts on the map's model; MeteoVerdict AI without data there: the combination. */
const panelStart = (okres) => (mapModel === AI_MODEL && !hasAi(aiData, okres) ? COMBINED : mapModel);

/** What the map draws: the chosen model's view, or our combination. */
const shownView = () => (mapModel !== COMBINED && mapView ? mapView : outlook);
const modelName = (model) => (model === COMBINED ? t("forecast.pickCombined") : model === AI_MODEL ? t("ai.modelName") : modelNames[model] ?? model);

/** "Sat 10/19, 12:00": the end of a model's run, Prague time. */
function endText(ms) {
  return new Intl.DateTimeFormat(language, {
    weekday: "short", day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", timeZone: "Europe/Prague",
  }).format(ms);
}

// the first line of a day tab: "Today", "Tomorrow", "Wednesday"
function dayName(day) {
  const label = dayLabel(day, today(Date.now()), language);
  return label.key ? t(label.key) : label.name;
}

// "Today 10/12", "Wednesday 10/14" (headings, the week in the okres panel)
function dayText(day) {
  return `${dayName(day)} ${dayLabel(day, today(Date.now()), language).short}`;
}

// sunrise and sunset with their glyphs: "↑ 07:03–07:28 ↓ 17:59–18:23" (a range or a time)
// (`key` the tooltip's text)
function sunLine(rise, set, key) {
  const line = element("span", null, "sun");
  line.append(glyph("sunrise", 13), element("span", rise), glyph("sunset", 13), element("span", set));
  line.title = t(key, { rise, set });
  return line;
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
      // always two lines: "Today" / "Mon, 10/12", "Wednesday" / "Wed, 10/14"
      button.append(element("strong", dayName(day)), element("small", dayLabel(day, today(Date.now()), language).date));
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
  for (const scope of ["day", "week"]) {
    const button = document.getElementById(`play-${scope}`);
    button.textContent = playing === scope ? t("tv.pause") : t(`tv.play.${scope}`);
    button.setAttribute("aria-pressed", String(playing === scope));
    button.title = t(`tv.playHint.${scope}`);
  }
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
      radio.addEventListener("change", () => {
        update({ colour });
      });
      label.append(radio, element("span", t(`layer.${colour}`)));
      return label;
    }),
  );
  renderLegend();
}

function renderLegend() {
  // a single model: rain in mm (no probability), its raw cloud cover
  const single = Boolean(shownView()?.single);
  const key = rampKey(state.colour, true);
  renderScale(document.getElementById("scale"), key, t(single && state.colour === "cloud" ? "scale.cloudModel" : `scale.${key}`));
}

// --- markers: built once, their content updated in place (also between two states) --
const markers = new Map(); // okres → {marker, el, lngLat, canvas, icon, temp, chips}

function markerElement(o) {
  const el = element("button", null, "wx-marker");
  el.type = "button";
  el.title = displayName(o.name);
  const top = element("span", null, "wx-top");
  const canvas = iconCanvas("", 30);
  const temp = element("span", "", "wx-temp");
  top.append(canvas, temp);
  const chipBox = element("span", null, "wx-chips");
  const chips = {};
  for (const layer of LAYERS.filter((l) => l !== "temperature")) {
    const chip = element("span", null, `wx-chip ${layer}`);
    const text = element("span", "");
    chip.append(glyph(layer, 11), text);
    chipBox.append(chip);
    chips[layer] = { chip, text };
  }
  el.append(top, chipBox);
  el.addEventListener("click", (event) => {
    event.stopPropagation();
    update({ okres: o.code });
    scrollToPanel(document.getElementById("okres-panel"), true);
  });
  return { el, canvas, temp, chips, chipBox, icon: null };
}

/** Show a row (possibly between two states) in a marker. */
function setMarker(entry, row, part, shown) {
  entry.el.style.display = row ? "" : "none";
  if (!row) return;
  const icon = iconName(row.symbol, part, row);
  if (icon !== entry.icon) {
    entry.icon = icon;
    const ctx = entry.canvas.getContext("2d");
    if (icon) drawIcon(ctx, icon, entry.canvas.width);
    else ctx.clearRect(0, 0, entry.canvas.width, entry.canvas.height);
  }
  entry.temp.hidden = !shown.includes("temperature");
  entry.temp.textContent = labelFor(row, "temperature", part);
  let any = false;
  for (const [layer, { chip, text }] of Object.entries(entry.chips)) {
    text.textContent = labelFor(row, layer, part);
    // a single model without this variable (MeteoVerdict AI has no rain or cloud): no empty chip
    chip.hidden = !shown.includes(layer) || (row.single && !row.beyond && text.textContent === "");
    any ||= !chip.hidden;
  }
  entry.chipBox.hidden = !any;
}

function buildMarkers(outlook) {
  for (const o of outlook.okresy) {
    const parts = markerElement(o);
    const marker = new Marker({ element: parts.el }).setLngLat([o.lon, o.lat]).addTo(map);
    markers.set(o.code, { ...parts, marker, lngLat: [o.lon, o.lat] });
  }
}

function paintMarkers(outlook) {
  for (const [code, entry] of markers) {
    setMarker(entry, rowFor(outlook, code, state.day, state.part), state.part, state.shown);
  }
  declutter();
}

// phones: zoomed out to the whole country the 77 markers of a narrow map would cover each
// other and the okresy: only the kraj towns' (tv.js CAPITALS) until zoomed in by at least
// half a step (one press of "+" is a whole step). A tap on any okres opens it all the same.
const PHONE_WIDTH = 700;
const ALL_MARKERS_ZOOM_IN = 0.5;
function overview() {
  if (window.innerWidth > PHONE_WIDTH) return false;
  const whole = map.cameraForBounds(BOUNDS, { padding: 20 })?.zoom;
  return whole != null && map.getZoom() < whole + ALL_MARKERS_ZOOM_IN;
}

function declutter() {
  const onlyTowns = overview();
  const boxes = [...markers]
    .filter(([, m]) => m.el.style.display !== "none")
    .filter(([code]) => !onlyTowns || CAPITALS.includes(code) || code === state.okres)
    .map(([code, m]) => {
      m.el.hidden = false;
      const p = map.project(m.lngLat);
      const box = { code, x: p.x, y: p.y, w: m.el.offsetWidth, h: m.el.offsetHeight };
      // only the kraj towns: the biggest first (CAPITALS's order, Praha first), as many as fit
      if (onlyTowns && code !== state.okres) box.priority = 1 + CAPITALS.indexOf(code);
      return box;
    });
  const shown = placeMarkers(boxes, 4, state.okres);
  // test: zoomed in, the obce stand in for their okres's marker
  if (obceDocs.length && obceShown() && map.getZoom() >= MIN_ZOOM) {
    for (const code of obceDrawn()) shown.delete(code);
  }
  for (const [code, m] of markers) {
    m.el.hidden = !shown.has(code);
    m.el.classList.toggle("selected", code === state.okres);
  }
}

// --- headline: follows the values shown --------------------------------------------
// the note on the map while a single model is shown (or loading), with the way back
function modelBanner(view) {
  if (mapStatus?.failed) return element("p", t("tv.bannerFailed", { model: modelName(mapStatus.failed) }), "model-banner failed");
  if (mapStatus?.loading) return element("p", t("tv.bannerLoading", { model: modelName(mapStatus.loading) }), "model-banner");
  // MeteoVerdict AI: only its name says "experimental", no banner and no way back
  if (!view.single || mapModel === AI_MODEL) return null;
  const banner = element("div", null, "model-banner");
  banner.append(element("p", t("tv.banner", { model: modelName(mapModel), time: issuedText(view.generated) ?? "–" })));
  const cut = view.days.some((day) => view.okresy.some((o) => rowFor(view, o.code, day, "day")?.beyond));
  if (cut && view.lastHour != null) banner.append(element("p", t("tv.bannerHorizon", { end: endText(view.lastHour) }), "horizon"));
  const back = element("button", t("tv.bannerBack"), "back");
  back.type = "button";
  back.addEventListener("click", () => setMapModel(COMBINED));
  banner.append(back);
  return banner;
}

function renderHeadline(outlook) {
  const s = summary(outlook, state.day, state.part);
  const box = document.getElementById("headline");
  const banner = modelBanner(outlook);
  box.classList.toggle("single", Boolean(outlook.single));
  if (!s) {
    // "beyond its horizon" only after the model's last hour, not for a past day it never covered
    const note = outlook.single && outlook.lastHour != null && state.day >= today(outlook.lastHour)
      ? t("tv.beyondPart", { end: endText(outlook.lastHour) })
      : t("tv.noPart");
    box.replaceChildren(...(banner ? [banner] : []), element("h2", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`), element("p", note));
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
  if (shown("precipitation") && s.hasRain) {
    lines.push(line("precipitation", t(s.single ? "tv.rainyModel" : "tv.rainy", { n: s.rainy, of: s.okresy })));
  }
  if (shown("wind")) lines.push(line("wind", t("tv.windiest", { okres: displayName(s.windiest.name), value: fmt(s.windiest.value) })));
  if (shown("cloud") && s.hasCloud) lines.push(line("cloud", t("tv.clearIn", { n: s.clear, of: s.okresy })));
  // the day's sunrise and sunset, earliest to latest over the okresy (about 25 minutes apart)
  const sun = sunRange(outlook, state.day);
  if (sun) {
    for (const [key, times] of [["sunrise", sun.sunrise], ["sunset", sun.sunset]]) {
      const p = line(key, t(`tv.${key}`, { time: rangeText(times) }));
      p.title = t("tv.sunRange", { rise: rangeText(sun.sunrise), set: rangeText(sun.sunset) });
      lines.push(p);
    }
  }
  const heading = element("h2", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`);
  const children = [...(banner ? [banner] : []), heading, ...lines];
  if (playing && RAMPS[state.colour]) {
    // while playing the map colour changes every round: say which one it is
    const badge = element("p", null, "playing");
    badge.append(glyph(state.colour), element("span", t("tv.mapShows", { layer: t(`layer.${state.colour}`) })));
    children.splice(children.indexOf(heading) + 1, 0, badge);
  }
  box.replaceChildren(...children);
}

// --- okres panel ------------------------------------------------------------------
// Which forecast the panel shows: our combination (outlook.json), or one model's raw
// forecast (forecast/models/<okres>.json, parts and days by the outlook's rules, models.js).
// Not remembered. Every opening of an okres starts on the forecast the map shows (the map's
// selector); the panel's own selector changes only the panel, never the map.
let panelModel = COMBINED;
// okres → {status: "loading" | "ready" | "missing", table, parsed, periods: Map model → rows}
const okresFiles = new Map();
let metaJson = null;

/** The okres's weights and models' forecasts (static files, loaded when it is opened). */
function okresData(code) {
  if (!okresFiles.has(code)) {
    const entry = { status: "loading", table: new Map(), parsed: null, periods: new Map(), names: {} };
    okresFiles.set(code, entry);
    metaJson ??= getJson("data/scores/meta.json");
    Promise.all([
      getJson(`data/scores/forecast/${code}.json`),
      getJson(`data/scores/forecast/models/${code}.json`),
      metaJson,
      loadAi(getJson),
    ]).then(([weights, models, meta, ai]) => {
      entry.table = weightTable(weights);
      entry.parsed = withAi(parseModels(models), ai, code);
      entry.ai = ai;
      entry.names = { ...meta?.models };
      entry.status = entry.parsed ? "ready" : "missing";
      if (state.okres === code) renderPanel(outlook);
    });
  }
  return okresFiles.get(code);
}

/**
 * The panel's rows: (day, part) → row of the combination or of the chosen model (from
 * the okres's own per-model file; while that loads, the map's model from the map's file).
 */
function panelRows(data) {
  const combined = { single: false, rowOf: (day, part) => rowFor(outlook, state.okres, day, part) };
  if (panelModel === COMBINED) return combined;
  if (!(data.status === "ready" && data.parsed.models[panelModel])) {
    if (panelModel !== mapModel || !mapView) return combined;
    const periods = {
      get: (key) => {
        const row = mapView.rows.get(`${state.okres}|${key}`);
        return row && !row.beyond ? row : undefined;
      },
    };
    return {
      single: true,
      periods,
      generated: mapView.generated,
      end: mapView.lastHour,
      rowOf: (day, part) => periods.get(`${day}|${part}`),
    };
  }
  if (!data.periods.has(panelModel)) {
    const own = modelPeriods(data.parsed, panelModel);
    data.periods.set(panelModel, panelModel === AI_MODEL ? aiPeriods(own, data.ai, state.okres) : own);
  }
  const periods = data.periods.get(panelModel);
  return {
    single: true,
    periods,
    generated: data.parsed.generated,
    end: modelHorizon(data.parsed, panelModel),
    // with the day's sunrise and sunset, for the night symbols
    rowOf: (day, part) => {
      const row = periods.get(`${day}|${part}`);
      return row ? { ...row, ...sunFor(outlook, state.okres, day) } : undefined;
    },
  };
}

const rainText = (row) => {
  if (row.precipitation != null) return `${fmt(row.precipitation, 1)} mm`;
  return row.rain_probability == null ? "–" : percent(row.rain_probability);
};

// a part of the day in the panel's strip: a button showing that part on the map and in
// the panel, as the part buttons above the map do
function partCell(row, part, single) {
  const cell = element("button", null, part === state.part ? "part current" : "part");
  cell.type = "button";
  cell.setAttribute("aria-pressed", String(part === state.part));
  cell.addEventListener("click", () => update({ part }));
  cell.append(
    element("span", t(`part.${part}`), "part-name"),
    iconCanvas(row ? iconName(row.symbol, part, row) : "", 34, symbolText(row?.symbol)),
    element("strong", row ? labelFor(row, "temperature", part) : "–"),
    element("span", row ? rainText(row, single) : "", "rain"),
  );
  return cell;
}

// the "Forecast" selector and, for a single model, what it is and where it ends
function modelPicker(data, rows) {
  const { single, periods } = rows;
  const label = element("label", null, "model-pick");
  const select = document.createElement("select");
  select.autocomplete = "off";
  const ready = data.status === "ready";
  // the map's model is offered also while the okres's file loads (the map has its values)
  const available = new Set([
    ...(ready ? Object.keys(data.parsed.models) : []),
    ...(mapView && mapModel !== COMBINED && (mapModel !== AI_MODEL || hasAi(aiData, state.okres)) ? [mapModel] : []),
  ]);
  const chosen = fillPicker(select, {
    table: data.table,
    names: { ...modelNames, ...data.names, [AI_MODEL]: t("ai.modelName") },
    available,
    selected: panelModel,
    t,
  });
  if (ready || available.has(panelModel)) panelModel = chosen;
  select.disabled = available.size === 0;
  // the panel's own choice: only the panel changes, never the map
  select.addEventListener("change", () => {
    panelModel = select.value;
    renderPanel(outlook);
    document.querySelector("#okres-panel .model-pick select")?.focus();
  });
  label.append(element("span", t("forecast.pick")), select);
  const notes = [];
  // no note while the map's own rows stand in (panelRows): it would vanish and shift the panel
  if (data.status === "loading" && !(panelModel === mapModel && mapView)) notes.push(element("p", t("tv.modelLoading"), "model-note"));
  if (data.status === "missing") notes.push(element("p", t("tv.modelUnavailable"), "model-note"));
  if (single && panelModel !== AI_MODEL) {
    let text = t("tv.modelNote", { time: issuedText(rows.generated) ?? "–" });
    // days of our forecast the model does not cover whole
    const cut = outlook.days.some((day) => rowFor(outlook, state.okres, day, "day") && !periods.get(`${day}|day`));
    if (cut && rows.end != null) text += ` ${t("tv.modelHorizon", { end: endText(rows.end) })}`;
    if (text) {
      const note = element("p", text.trim(), "model-note");
      note.title = t("tv.modelNoteMore");
      notes.push(note);
    }
  }
  if (mapModel === AI_MODEL && panelModel === COMBINED && !hasAi(aiData, state.okres)) {
    notes.push(element("p", t("tv.aiFallback"), "model-note"));
  } else if (panelModel !== mapModel) notes.push(element("p", t("tv.panelOnly", { map: modelName(mapModel) }), "model-note"));
  return [label, ...notes];
}

// the day's strongest wind and, where the single runs reach, its strongest gust
function windCell(row) {
  if (!row) return element("td", "", "num");
  if (row.gust == null) return element("td", `${fmt(row.wind)} m/s`, "num");
  const td = element("td", `${fmt(row.wind)} / ${fmt(row.gust)} m/s`, gustOver(row) ? "num gust-over-threshold" : "num");
  td.title = gustOver(row) ? `${t("tv.windGustCell")}. ${gustOverText(t, language)}` : t("tv.windGustCell");
  return td;
}

// test: the panel of an obec (obce-map.js): as the okres's with our combination, but its
// rows have no symbol, cloud or rain probability (rain in mm)
// the okres's further values of the part (MeteoVerdict AI's obce file): "dohlednost 20 km, CAPE 0 J/kg …"
const OKRES_EXTRA = [
  ["visibility", "km", 0], ["fog_probability", "%", 0], ["temperature_5cm", "°C", 1], ["cloud_cover_low", "%", 0],
  ["shortwave_radiation", "W/m²", 0], ["cape", "J/kg", 0], ["snowfall", "cm", 1], ["snow_depth", "cm", 0],
  ["snow_depth_water_equivalent", "mm", 0],
];
function okresExtras(values) {
  if (!values) return "";
  const snow = ["snowfall", "snow_depth", "snow_depth_water_equivalent"];
  return OKRES_EXTRA
    .filter(([v]) => values[v] != null && !(snow.includes(v) && values[v] <= 0))
    .map(([v, unit, digits]) => `${v === "cape" ? "CAPE" : t(`forecast.extra.${v}`).toLowerCase()} ${fmt(v === "fog_probability" ? values[v] * 100 : values[v], digits)} ${unit}`)
    .join(", ");
}

function renderObecPanel(panel, { doc, rows, ai: ownAi }) {
  const place = doc.places.find((p) => p.name === panelObec);
  const own = rows.get(panelObec) ?? new Map();
  // the okres's sky for the obec (no symbols in the obec files): its symbol, from its cloud
  // with the obec's own rain and temperature where the okres has the cloud
  const okresRow = (day, part) => rowFor(outlook, state.okres, day, part);
  const rowOf = (day, part) => {
    const row = own.get(`${day}|${part}`);
    const sky = okresRow(day, part);
    if (!row) return undefined;
    if (!sky) return row;
    const symbol = sky.cloud != null && row.tmin != null
      ? modelSymbol(sky.cloud, row.precipitation, (row.tmin + row.tmax) / 2) ?? sky.symbol
      : sky.symbol;
    return { ...row, symbol, cloud: sky.cloud, sunshine: sky.sunshine, ...sunFor(outlook, state.okres, day) };
  };
  const info = outlook.okresy.find((o) => o.code === state.okres);
  panel.classList.remove("single");
  const now = rowOf(state.day, state.part);
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("chart.close"));
  close.addEventListener("click", () => {
    update({ okres: null });
    scrollToPanel(document.getElementById("okres-panel"), false);
  });
  const big = element("div", null, "now");
  big.append(element("div", now ? labelFor(now, "temperature", state.part) : "–", "big-temp"));
  const facts = element("ul", null, "facts");
  if (now) {
    for (const text of [
      t("tv.range", { low: fmt(now.tmin), high: fmt(now.tmax) }),
      t("tv.obecRain", { amount: fmt(now.precipitation, 1) }),
      now.gust != null ? t("tv.windGust", { value: fmt(now.wind), gust: fmt(now.gust) }) : t("tv.wind", { value: fmt(now.wind) }),
      ...(now.direction != null ? [t("tv.obecDirection", { dir: Math.round(now.direction) })] : []),
      ...(now.cloud != null ? [t("tv.cloud", { value: fmt(now.cloud, 0) })] : []),
      ...(now.humidity != null
        ? [t("tv.obecAir", { humidity: fmt(now.humidity, 0), dew: fmt(now.dew_point, 1), pressure: fmt(now.pressure, 0) })]
        : []),
      ...(okresExtras(now.okres) ? [t("tv.obecOkresExtra", { items: okresExtras(now.okres) })] : []),
    ]) {
      facts.append(element("li", text));
    }
  }
  const sun = sunFor(outlook, state.okres, state.day);
  if (sun) {
    const li = element("li");
    li.append(sunLine(sun.sunrise, sun.sunset, "tv.sun"));
    facts.append(li);
  }
  const strip = element("div", null, "strip");
  strip.append(...PARTS.slice(0, 4).map((p) => partCell(rowOf(state.day, p), p, true)));
  const week = element("table", null, "week");
  for (const day of outlook.days) {
    const ownRow = rowOf(day, "day");
    if (!ownRow && day < state.day) continue;
    // a day the obec's hours do not cover whole: the okres's values, marked
    const fallback = ownRow ? null : okresRow(day, "day");
    const row = ownRow ?? fallback;
    const tr = element("tr");
    tr.className = [day === state.day ? "current" : "", fallback ? "okres-values" : ""].join(" ").trim();
    if (fallback) tr.title = t("tv.obecDayOkres");
    tr.addEventListener("click", () => update({ day }));
    const iconCell = element("td");
    iconCell.append(iconCanvas(row ? iconName(row.symbol, "day", row) : "", 26, symbolText(row?.symbol)));
    tr.append(
      element("td", dayText(day)),
      iconCell,
      element("td", row ? `${fmt(row.tmax)}° / ${fmt(row.tmin)}°` : "–", "num"),
      element("td", row ? rainText(row, true) : "", "num rain"),
      windCell(row),
    );
    week.append(tr);
  }
  const back = element("a", t("tv.obecOkres", { okres: displayName(info?.name ?? state.okres) }));
  back.href = "#";
  back.addEventListener("click", (event) => {
    event.preventDefault();
    update({ okres: state.okres });
  });
  const note = element("p", t(ownAi ? "ai.obecNote" : "tv.obecNote", { okres: displayName(info?.name ?? state.okres) }), "model-note");
  // how good the obec forecast is away from the stations (not the AI's, a different method)
  const accuracy = element("p", null, "model-note");
  const link = element("a", t("forecast.obecAccuracy"));
  link.href = "methodology.html#obce-loso";
  accuracy.append(link);
  // the detail of the obec's okres town (seats.js), every model's lines there
  const detail = townDetail(state.okres);
  panel.replaceChildren(
    close,
    element("h2", `${panelObec}${place ? ` (${Math.round(place.elevation)} m)` : ""}`),
    ...(place?.population != null
      ? [element("p", t("tv.obecPopulation", { people: place.population.toLocaleString(language) }), "when")]
      : []),
    element("p", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`, "when"),
    note,
    ...(ownAi ? [] : [accuracy]),
    back,
    big,
    facts,
    strip,
    week,
    detail,
  );
}

function renderPanel(outlook) {
  const panel = document.getElementById("okres-panel");
  if (!state.okres) {
    panel.replaceChildren();
    return;
  }
  const obecDoc = panelObec ? obceLoaded.get(obceKey(state.okres)) : null;
  if (obecDoc) {
    renderObecPanel(panel, obecDoc);
    return;
  }
  const info = outlook.okresy.find((o) => o.code === state.okres);
  const data = okresData(state.okres);
  const rows = panelRows(data);
  const { single, rowOf } = rows;
  panel.classList.toggle("single", single);
  const now = rowOf(state.day, state.part);
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("chart.close"));
  close.addEventListener("click", () => {
    update({ okres: null });
    scrollToPanel(document.getElementById("okres-panel"), false);
  });
  const big = element("div", null, "now");
  big.append(
    iconCanvas(now ? iconName(now.symbol, state.part, now) : "", 64, symbolText(now?.symbol)),
    element("div", now ? labelFor(now, "temperature", state.part) : "–", "big-temp"),
  );
  const facts = element("ul", null, "facts");
  if (now) {
    for (const text of [
      symbolText(now.symbol),
      t("tv.range", { low: fmt(now.tmin), high: fmt(now.tmax) }),
      single || now.rain_probability == null
        ? t("tv.rainModel", { amount: fmt(now.precipitation, 1) })
        : t("tv.rain", { chance: percent(now.rain_probability), amount: fmt(now.precipitation, 1) }),
      // gusts from the single runs: null beyond the newest run and in older files
      now.gust != null ? t("tv.windGust", { value: fmt(now.wind), gust: fmt(now.gust) }) : t("tv.wind", { value: fmt(now.wind) }),
      t("tv.cloud", { value: fmt(now.cloud) }),
    ]) {
      facts.append(element("li", text));
    }
    if (gustOver(now)) {
      facts.append(element("li", gustOverText(t, language), "gust-over-threshold"));
      facts.append(chmiNotice(t, "li"));
    }
  }
  const sun = sunFor(outlook, state.okres, state.day);
  if (sun) {
    // the whole day's, whatever part is shown
    const li = element("li");
    li.append(sunLine(sun.sunrise, sun.sunset, "tv.sun"));
    facts.append(li);
  }
  const strip = element("div", null, "strip");
  strip.append(...PARTS.slice(0, 4).map((p) => partCell(rowOf(state.day, p), p, single)));
  const week = element("table", null, "week");
  for (const day of outlook.days) {
    const row = rowOf(day, "day");
    const tr = element("tr");
    if (day === state.day) tr.className = "current";
    tr.addEventListener("click", () => update({ day }));
    const iconCell = element("td");
    iconCell.append(iconCanvas(row ? iconName(row.symbol, "day", row) : "", 26, symbolText(row?.symbol)));
    tr.append(
      element("td", dayText(day)),
      iconCell,
      element("td", row ? `${fmt(row.tmax)}° / ${fmt(row.tmin)}°` : "–", "num"),
      element("td", row ? rainText(row, single) : "", "num rain"),
      windCell(row),
    );
    week.append(tr);
  }
  // the day table can flag a gust on another day than the one in the facts above
  const weekFlagged = outlook.days.some((day) => gustOver(rowOf(day, "day")));
  const detail = townDetail(state.okres);
  panel.replaceChildren(
    close,
    element("h2", displayName(info?.name ?? state.okres)),
    element("p", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`, "when"),
    ...modelPicker(data, rows),
    big,
    facts,
    strip,
    week,
    ...(weekFlagged && !gustOver(now) ? [chmiNotice(t)] : []),
    detail,
  );
}

// --- update loop ------------------------------------------------------------------
let outlook = null;

/** The link to the detail of an okres's town (seats.js): Praha for Praha-východ, … */
function townDetail(code) {
  const seat = seatOkres(code);
  const detail = element("a", t("tv.detail", { town: seatName(seat, outlook?.okresy.find((o) => o.code === seat)?.name ?? seat) }));
  detail.href = `${DETAIL}#${seat}`;
  // directly under it, the link to what was measured in this okres
  const measured = element("a", t("tv.measuredLink"));
  measured.href = `measured.html#${code}`;
  const links = element("div", null, "detail-links");
  links.append(detail, measured);
  return links;
}
let padding = null;

/** Fit Czechia beside the okres panel on wide screens, and back when it closes. */
const movedByUser = userMoved(map);
// up to 1024 px the panel sits under the map (style.css), so the map never moves for it
const PANEL_BESIDE = 1024;
function fitView() {
  const right = window.innerWidth > PANEL_BESIDE && state.okres ? panelRoom() : 20;
  if (padding && padding.right === right) return;
  // someone moved the map themselves: leave it where they put it
  if (padding && movedByUser()) return;
  const first = padding === null;
  padding = { top: 20, bottom: 20, left: 20, right };
  map.fitBounds(BOUNDS, { padding, duration: first ? 0 : 400 });
}

function paintFill(colours) {
  const pairs = [...colours].flat();
  map.setPaintProperty("okresy-fill", "fill-color", pairs.length ? ["match", ["get", "code"], ...pairs, NEUTRAL] : NEUTRAL);
}

/**
 * Draw the current state at once (after a click, or at the end of a transition). The
 * address follows: another day, okres or obec as a new step of the browser's history (Back
 * returns to it), anything else in place (tv.js historyMode); `replace` keeps it in place
 * (opening a link, Back and Forward themselves).
 */
function update(change = {}, { fromPlay = false, replace = false } = {}) {
  // a past day ("Yesterday", the first tab) is what was measured: the measured page shows
  // that day, as a link or a reload of that day's address would
  if (!fromPlay && change.day && change.day < today(Date.now())) {
    const hash = measuredRedirect(viewHash({ ...state, ...change, obec: null }), today(Date.now()));
    if (hash) {
      window.location.assign(`measured.html${hash}`);
      return;
    }
  }
  if (!fromPlay) stopPlay();
  const before = { ...state, obec: panelObec };
  // another okres (or none) starts on the forecast the map shows
  if ("okres" in change && change.okres !== state.okres) panelModel = panelStart(change.okres);
  // test: an obec's panel (change.obec) or its okres's; any other okres change closes it
  if ("okres" in change) panelObec = change.okres ? change.obec ?? null : null;
  const { obec: _obec, ...rest } = change;
  state = { ...state, ...rest };
  const after = { ...state, obec: panelObec };
  const hash = viewHash(after);
  if (hash !== window.location.hash) {
    if (!replace && !fromPlay && historyMode(before, after) === "push") window.history.pushState(null, "", hash);
    else window.history.replaceState(null, "", hash);
  }
  const view = shownView();
  paintMeasuredLink();
  renderWhen(outlook);
  renderShow();
  paintFill(okresColours(view, state.day, state.part, state.colour));
  map.setFilter("okres-selected", ["==", ["get", "code"], state.okres ?? ""]);
  if (mapReady || obceDocs.length) paintObce(map, obceShown() ? obceDocs : [], state, panelObec);
  paintMarkers(view);
  renderHeadline(view);
  renderPanel(outlook);
  fitView();
}

// --- play: smooth transitions through the parts of a day (or of every day), each
// round with the next map colour -----------------------------------------------------
const TRANSITION_MS = 1100;
// a change of the map colour (another value) is quicker
const SWITCH_MS = 500;
const HOLD_MS = 1400;
let playToken = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function stopPlay() {
  if (!playing) return;
  playing = null;
  playToken += 1;
  renderWhen(outlook);
  renderHeadline(shownView());
}

/** Move to `target` (a part of state), interpolating colours and values; false if stopped. */
async function transition(target, token) {
  const from = { ...state };
  const to = { ...state, ...target };
  const view = shownView();
  const coloursFrom = okresColours(view, from.day, from.part, from.colour);
  const coloursTo = okresColours(view, to.day, to.part, to.colour);
  // the labels and boxes already show where we are going
  state = to;
  renderWhen(outlook);
  renderShow();
  renderHeadline(view);
  const start = performance.now();
  for (;;) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    if (token !== playToken) return false;
    const elapsed = performance.now() - start;
    const f = ease(Math.min(1, elapsed / TRANSITION_MS));
    // the same value: colours move smoothly; another value: a quick fade through the
    // background, so the two are never mixed
    paintFill(
      from.colour === to.colour
        ? new Map([...coloursTo].map(([code, c]) => [code, mixColor(coloursFrom.get(code) ?? c, c, f)]))
        : switchColours(coloursFrom, coloursTo, Math.min(1, elapsed / SWITCH_MS)),
    );
    for (const [code, entry] of markers) {
      const row = lerpRow(rowFor(view, code, from.day, from.part), rowFor(view, code, to.day, to.part), f);
      setMarker(entry, row, f < 0.5 ? from.part : to.part, to.shown);
    }
    if (f >= 1) break;
  }
  update({}, { fromPlay: true });
  return true;
}

/**
 * Play the parts of the shown day ("day") or of every day ("week"), from the part shown
 * now, round after round, with exactly the options chosen (colour, values, legend): play
 * never switches them.
 */
async function play(scope) {
  stopPlay();
  playing = scope;
  const token = ++playToken;
  // a single model: only the parts it covers
  const steps = playSteps(shownView(), scope, state.day);
  if (steps.length === 0) return stopPlay();
  let i = startIndex(steps, state.day, state.part);
  renderWhen(outlook);
  if (!(await transition(steps[i], token))) return;
  for (;;) {
    await sleep(HOLD_MS);
    if (token !== playToken) return;
    i += 1;
    if (!(await transition(steps[i % steps.length], token))) return;
  }
}

function togglePlay(scope) {
  if (playing === scope) stopPlay();
  else play(scope);
}

// --- the map's forecast selector ------------------------------------------------------
function renderMapPicker() {
  const select = document.getElementById("map-model-select");
  const options = mapModelOptions(modelIndex, modelNames);
  const option = (model, text) => {
    const o = document.createElement("option");
    o.value = model;
    o.textContent = text;
    return o;
  };
  const rank = (r) => r.toLocaleString(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const group = (key, list) => {
    const g = document.createElement("optgroup");
    g.label = t(key);
    g.append(...list);
    return g;
  };
  const ranked = options.filter((o) => o.rank != null)
    .map((o) => option(o.model, t("forecast.pickOption", { position: o.position, model: o.name, rank: rank(o.rank) })));
  const others = options.filter((o) => o.rank == null).map((o) => option(o.model, o.name));
  // MeteoVerdict AI (experimental in its name): the first option, above our combination
  const aiOption = aiData ? [option(AI_MODEL, t("ai.modelName"))] : [];
  select.replaceChildren(
    ...aiOption,
    option(COMBINED, t("forecast.pickCombined")),
    ...(ranked.length ? [group("tv.mapModelRanked", ranked)] : []),
    ...(others.length ? [group("tv.mapModelOthers", others)] : []),
  );
  select.value = mapModel;
  select.disabled = !mapReady || (options.length === 0 && !aiOption.length);
  document.getElementById("map-model").title = t(options.length ? "tv.mapModelHint" : "tv.mapModelsMissing");
}

/** Once the map and a fresh AI file are there, MeteoVerdict AI is the default (unless chosen already). */
function defaultToAi() {
  if (!aiData || !mapReady || mapChosen || mapModel !== COMBINED) return;
  setMapModel(AI_MODEL);
}

/** The link below the map to the measured page, for the okres open in the panel (measured.html#CZxxxx). */
function paintMeasuredLink() {
  // with a panel open the link is in the panel (townDetail); without one it stays below the map
  document.getElementById("measured-link").hidden = Boolean(state.okres);
}

/** After the map's model changed: the obce of the open okres and of those in view, for the new source. */
async function switchObce() {
  if (!obceShown()) return;
  if (state.okres) await obceOf(state.okres);
  loadObceInView();
}

/** Switch the whole map (and the okres panel) to `model`, or back to our combination. */
async function setMapModel(model) {
  const token = ++mapToken;
  stopPlay();
  document.getElementById("map-model-select").value = model;
  if (model === COMBINED) {
    mapModel = COMBINED;
    mapView = null;
    mapStatus = null;
    panelModel = COMBINED;
    refreshObceDocs();
    await switchObce();
    update();
    return;
  }
  if (!modelViews.has(model)) {
    mapStatus = { loading: model };
    renderHeadline(shownView());
    const view = model === AI_MODEL
      ? aiMapView(aiData, outlook)
      : parseModelParts(await getJson(`data/scores/forecast/models-parts/${model}.json`), outlook);
    if (view) modelViews.set(model, view);
  }
  if (token !== mapToken) return;
  const view = modelViews.get(model);
  if (!view) {
    mapModel = COMBINED;
    mapView = null;
    mapStatus = { failed: model };
    document.getElementById("map-model-select").value = COMBINED;
  } else {
    mapModel = model;
    mapView = view;
    mapStatus = null;
  }
  // the open okres follows the map
  panelModel = panelStart(state.okres);
  refreshObceDocs();
  await switchObce();
  if (token !== mapToken) return;
  update();
}

function addLayers() {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({ id: "okresy-fill", type: "fill", source: "okresy", paint: { "fill-color": "#ececec", "fill-opacity": FILL_OPACITY } });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.2 } });
  // the towns' and cities' names over the base map (the obce of the test have their own)
  for (const layer of topLayers(language).filter((l) => l.id === "place-town" || l.id === "place-city")) {
    map.addLayer({ ...layer, minzoom: Math.max(layer.minzoom ?? 0, BASE_ZOOM) });
  }
  map.addLayer({
    id: "okres-selected",
    type: "line",
    source: "okresy",
    filter: ["==", ["get", "code"], ""],
    paint: { "line-color": "#1d2329", "line-width": 2.5 },
  });
  addObceLayers(map, (okres, obec) => update({ okres, obec }));
  applyTheme();
  map.on("click", "okresy-fill", (event) => {
    // a click on an obec's label opens its panel, not the okres's
    if (map.queryRenderedFeatures(event.point, { layers: ["obce-test-label"] }).length) return;
    update({ okres: event.features[0].properties.code });
    scrollToPanel(document.getElementById("okres-panel"), true);
  });
  map.on("mouseenter", "okresy-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "okresy-fill", () => (map.getCanvas().style.cursor = ""));
  map.on("moveend", declutter);
}

// --- test: the obce (obce-map.js) ------------------------------------------------------
const loadPlaces = placesLoader(placesUrl);

/** The okres's obce (its file, loaded once); null without one. */
async function obceOf(code) {
  const key = obceKey(code);
  if (!obceLoaded.has(key)) {
    const ai = obceSrc() === "ai" ? await getJson(aiPath(`data/scores/forecast/obce-${code}.json`)).catch(() => null) : null;
    const doc = ai?.places ? ai : await obceFor(code, getJson);
    obceLoaded.set(key, doc ? { doc, rows: obcePartRows(doc), ai: doc === ai } : null);
    refreshObceDocs();
  }
  return obceLoaded.get(key);
}

/** Zoomed in: load the obce of the okresy in view, then draw them. */
async function loadObceInView() {
  if (map.getZoom() < MIN_ZOOM) return;
  const codes = new Set(map.queryRenderedFeatures({ layers: ["okresy-fill"] }).map((f) => f.properties.code));
  const missing = [...codes].filter((code) => !obceLoaded.has(obceKey(code)));
  if (!missing.length) return;
  await Promise.all(missing.map(obceOf));
  paintObce(map, obceShown() ? obceDocs : [], state, panelObec);
  declutter();
}

/**
 * Phones: the panel is below the map, out of sight after a search or a link to an obec.
 * Scroll so the map (the obec in its middle) is at the top and the panel's top below it.
 */
function revealPanel() {
  const frame = document.getElementById("map").getBoundingClientRect();
  const panel = document.getElementById("okres-panel").getBoundingClientRect();
  if (panel.top < frame.bottom - 1 || panel.top + 80 <= window.innerHeight) return;
  window.scrollTo({ top: window.scrollY + frame.top - 8, behavior: "smooth" });
}

/** A place found in the search: its okres's file, the obec there nearest to it, its panel. */
async function chooseObec(place) {
  // the places list names Prague's okres as the city, ČÚZK's okresy as its territory
  const info = outlook.okresy.find((o) => o.name === place.okres)
    ?? (place.okres === "Hlavní město Praha" ? outlook.okresy.find((o) => o.code === "CZ0100") : null);
  if (!info) return;
  const loaded = await obceOf(info.code);
  const obec = nearestObec(loaded?.doc, place.lat, place.lon);
  if (!obec) return;
  if (!obceShown()) await setMapModel(COMBINED);
  update({ okres: info.code, obec: obec.name });
  goToObec(map, [obec.lon, obec.lat]);
  revealPanel();
}

/** The view of a hash (tv.js parseView), with this page's defaults: today and its part now. */
function viewOf(hash) {
  const now = Date.now();
  const first = outlook.days.includes(today(now)) ? today(now) : outlook.days[0];
  const view = parseView(hash, outlook, {
    day: first,
    part: first === today(now) ? currentPart(now) : "afternoon",
  });
  // gust and sunshine are measured values (the measured page), not the forecast's
  if (!LAYERS.includes(view.colour)) view.colour = "temperature";
  view.shown = view.shown.filter((l) => LAYERS.includes(l));
  return view;
}

/** A link to an obec ("#okres/obec", from the home page): its panel open, the map on it. */
async function openObec({ okres, obec: name }) {
  if (!okres || !name) return;
  const place = (await obceOf(okres))?.doc.places.find((p) => p.name === name);
  if (!place) return;
  if (!obceShown()) await setMapModel(COMBINED);
  update({ okres, obec: name }, { replace: true });
  goToObec(map, [place.lon, place.lat]);
}

/** The view of the address now (pasted, or Back and Forward), unless it is shown already. */
async function applyHash() {
  const elsewhere = leaveFor(window.location.hash, today(Date.now()));
  if (elsewhere) {
    window.location.replace(elsewhere);
    return;
  }
  const view = viewOf(window.location.hash);
  const { obec, ...rest } = view;
  if (viewHash(view) === viewHash({ ...state, obec: panelObec })) return;
  // the obec's panel once its okres's obce are loaded (openObec); until then the okres's
  update({ ...rest, obec: null }, { replace: true });
  await openObec(view);
}

async function main() {
  outlook = parseOutlook(await getJson("data/scores/outlook.json"));
  const status = document.getElementById("status");
  if (outlook.okresy.length === 0) {
    status.textContent = t("tv.none");
    return;
  }
  const generated = outlook.generated ? new Date(outlook.generated) : null;
  status.textContent = generated && !Number.isNaN(generated.getTime())
    ? t("tv.updated", {
      // the same date and time as in every page's header: "21. 10. 2026 1:32", "21 Oct 2026, 01:32"
      time: new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Prague" }).format(generated),
    })
    : "";
  state = viewOf(window.location.hash);
  // phones: the box starts folded so the map stays visible
  const show = document.getElementById("show");
  if (window.innerWidth <= 700) show.open = false;
  document.getElementById("play-day").addEventListener("click", () => togglePlay("day"));
  document.getElementById("play-week").addEventListener("click", () => togglePlay("week"));
  const picker = document.getElementById("map-model-select");
  picker.setAttribute("autocomplete", "off");
  renderMapPicker();
  picker.disabled = true; // until the map is there
  // the models offered for the whole map, by their mean rank over Czechia
  metaJson ??= getJson("data/scores/meta.json");
  // loaded before the first drawing: the AI is the default, so the map and an okres panel
  // opened by a link start on it, not on the blend for a moment (a flicker)
  const modelsLoaded = Promise.all([getJson("data/scores/forecast/models-parts/index.json"), metaJson, loadAi(getJson)]).then(([index, meta, ai]) => {
    modelIndex = index;
    aiData = ai;
    modelNames = { ...meta?.models };
    renderMapPicker();
  });
  await Promise.all([mapLoaded, modelsLoaded]);
  if (aiData && !mapChosen) {
    const view = aiMapView(aiData, outlook);
    if (view) {
      modelViews.set(AI_MODEL, view);
      mapModel = AI_MODEL;
      mapView = view;
      panelModel = panelStart(state.okres);
      refreshObceDocs();
    }
  }
  addLayers();
  buildMarkers(outlook);
  update({}, { replace: true });
  await openObec(state);
  // a link to an okres or an obec: its panel in sight on phones too
  if (state.okres) revealPanel();
  // an address pasted into the open page, and Back and Forward through the days, okresy
  // and obce clicked (update pushes those): the view of that address, without a reload
  window.addEventListener("hashchange", applyHash);
  window.addEventListener("popstate", applyHash);
  // test: the obce of the okresy in view, loaded once zoomed in, and the search above
  map.on("moveend", loadObceInView);
  loadObceInView();
  // MeteoVerdict AI (shown below the map while the AI is the map's model): forecast vs
  // measured, its scores against our blend and its experiments
  document.getElementById("obce-search").replaceChildren(
    placeSearch({ t, load: loadPlaces, choose: chooseObec }),
  );
  picker.addEventListener("change", () => {
    mapChosen = true;
    setMapModel(picker.value);
  });
  mapReady = true;
  renderMapPicker();
  defaultToAi();
}

if (!elsewhere) main();
