import { Map as MapLibreMap, Marker, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { COMBINED, weightTable } from "./forecast.js";
import { drawIcon, glyph, iconCanvas } from "./icons.js";
import { setUpLanguage } from "./i18n.js";
import { mapModelOptions, modelHorizon, modelPeriods, parseModelParts, parseModels } from "./models.js";
import {
  OBSERVED_LAYERS, defaultLead, difference, nearestDay, parseObservedDay, parseObservedIndex, pastTabs,
  observedSummary, stationLink, stationValues,
} from "./observed.js";
import { fillPicker, issuedText } from "./picker.js";
import {
  ALL_LAYERS, LAYERS, NEUTRAL, PARTS, RAMPS, colorFor, currentPart, dayLabel, displayName, ease,
  iconName, labelFor, lerpRow, mixColor, mmView, nextColour, okresColours, parseOutlook, parseView,
  placeMarkers, playSteps, rampKey, rangeText, rowFor, startIndex, sunFor, sunRange, switchColours, summary,
  today, viewHash,
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
let playing = null; // "day" or "week" while playing

// --- which forecast the whole map shows: our combination (outlook.json) or one model's
// raw forecast (forecast/models-parts/<model>.json, all okresy). Not remembered: no
// storage and nothing in the URL, every page load starts on the combination.
let mapModel = COMBINED;
let mapView = null; // parseModelParts of mapModel while it is shown
let mapStatus = null; // null, {loading: model} or {failed: model}
let mapToken = 0;
let modelIndex = null; // forecast/models-parts/index.json
let modelNames = {}; // meta.json models
const modelViews = new Map(); // model → parsed file (loaded once)
let mapReady = false; // the selector works once the map has its layers

// --- past days: what was measured (observed.js; data/scores/observed/ from
// `mvd observed-map`). The model selector applies to the forecast days only.
let observedIndex = parseObservedIndex(null);
const observedViews = new Map(); // day → parsed view (null: the file failed)
const observedLoads = new Map(); // day → promise of the parsed view
let showStations = false; // the stations' own values as dots (past days; not remembered)
let stationIndex = null; // promise of data/scores/station/index.json
const stationDocs = new Map(); // day → promise of <day>-stations.json
let panelLead = null; // the forecast lead of the panel's comparison (null: one day before)

const todayIso = () => today(Date.now());
const isPast = (day) => day != null && day < todayIso();
/** The values a day offers: the forecast's four, or on a past day also gust and sunshine. */
const layersOf = (day) => (isPast(day) ? OBSERVED_LAYERS : LAYERS);
/** The map colour of a state (a past-only colour falls back to temperature on forecast days). */
const colourOf = (s) => (layersOf(s.day).includes(s.colour) ? s.colour : "temperature");
const shownOf = (s) => s.shown.filter((l) => layersOf(s.day).includes(l));

function loadObserved(day) {
  if (!observedLoads.has(day)) {
    observedLoads.set(
      day,
      getJson(`data/scores/observed/${day}.json`).then((doc) => {
        observedViews.set(day, parseObservedDay(doc, outlook.okresy));
        return observedViews.get(day);
      }),
    );
  }
  return observedLoads.get(day);
}

/** A past day's view; while its file loads (or when it failed) an empty one that says so. */
function pastView(day) {
  if (observedViews.get(day)) return observedViews.get(day);
  const failed = observedViews.has(day);
  // redraw once it is there (not before the map has its layers: main draws then)
  if (!failed) loadObserved(day).then(() => mapReady && state.day === day && update({}, Boolean(playing)));
  return {
    observed: true, loading: !failed, failed, day, days: [day], parts: PARTS, okresy: outlook.okresy,
    rows: new Map(), forecasts: [], stations: 0, source: "hourly",
  };
}

/** What the map draws: a past day's measurements, the chosen model's view, or our combination. */
const shownView = () => {
  if (isPast(state.day)) return pastView(state.day);
  return mapModel !== COMBINED && mapView ? mapView : outlook;
};
const modelName = (model) => (model === COMBINED ? t("forecast.pickCombined") : modelNames[model] ?? model);

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
// "older": a date field for any measured day before the tabs
function olderControl(past) {
  const box = element("label", null, "daytab past older");
  const input = document.createElement("input");
  input.type = "date";
  input.min = past[0].day;
  input.max = past.at(-1).day;
  input.value = isPast(state.day) ? state.day : "";
  input.setAttribute("aria-label", t("obs.pickDate"));
  input.addEventListener("change", () => {
    const day = nearestDay({ days: past }, input.value);
    if (day) update({ day });
  });
  box.title = t("obs.pickHint", { first: dayLabel(past[0].day, todayIso(), language).short, last: dayLabel(past.at(-1).day, todayIso(), language).short });
  box.append(element("strong", t("obs.older")), input);
  return box;
}

let scrolledTo = null; // the day the tabs were last scrolled to

function renderWhen() {
  const now = todayIso();
  const past = isPast(state.day);
  document.body.classList.toggle("past", past);
  const days = document.getElementById("days");
  days.setAttribute("aria-label", t("tv.day"));
  const tab = (day, measured) => {
    const button = element("button", null, measured ? "daytab past" : "daytab");
    button.type = "button";
    button.setAttribute("aria-pressed", String(day === state.day));
    // always two lines: "Today" / "Mon, 10/12", "Wednesday" / "Wed, 10/14"; a past day
    // "Yesterday" / "measured · Thu 10/16"
    const date = dayLabel(day, now, language).date;
    button.append(element("strong", dayName(day)), element("small", measured ? t("obs.tabDate", { date }) : date));
    button.addEventListener("click", () => update({ day }));
    return button;
  };
  const measured = observedIndex.days.filter((d) => d.day < now);
  const children = [];
  if (measured.length) {
    children.push(olderControl(measured), ...pastTabs(observedIndex, now, state.day).map((d) => tab(d, true)));
    children.push(element("span", null, "daytabs-divider"));
  }
  children.push(...outlook.days.map((d) => tab(d, false)));
  days.replaceChildren(...children);
  // keep the chosen day in view (the row scrolls on phones), with a glimpse of the day before
  const pressed = days.querySelector('.daytab[aria-pressed="true"]');
  if (pressed && scrolledTo !== state.day) {
    scrolledTo = state.day;
    // a past day keeps the date field in view, a forecast day a bit of yesterday
    const before = past ? (days.querySelector(".older")?.offsetWidth ?? 0) : 56;
    days.scrollLeft = Math.max(0, pressed.offsetLeft - days.offsetLeft - before);
  }
  const view = shownView();
  const available = view.observed && !view.loading ? view.parts : PARTS;
  const parts = document.getElementById("parts");
  parts.setAttribute("aria-label", t("tv.part"));
  parts.replaceChildren(
    ...PARTS.map((part) => {
      const button = element("button", null);
      button.type = "button";
      button.setAttribute("aria-pressed", String(part === state.part));
      // an older day has the whole day only (ČHMÚ's daily values)
      button.disabled = !available.includes(part);
      if (button.disabled) button.title = t("obs.dayOnly");
      button.append(element("span", t(`part.${part}`)), element("small", HOURS[part]));
      button.addEventListener("click", () => update({ part }));
      return button;
    }),
  );
  for (const scope of ["day", "week"]) {
    const button = document.getElementById(`play-${scope}`);
    button.textContent = playing === scope ? t("tv.pause") : t(`tv.play.${scope}`);
    button.setAttribute("aria-pressed", String(playing === scope));
    button.title = t(past && scope === "day" ? "obs.playHint" : `tv.playHint.${scope}`);
    // a past day plays its own parts; the week is the forecast's
    button.hidden = past && (scope === "week" || available.length < 2);
  }
  // the model selector is for forecasts: on a past day a note instead
  document.getElementById("map-model").hidden = past;
  const note = document.getElementById("map-model-note");
  note.hidden = !past;
  note.textContent = past ? t("obs.modelNote") : "";
}

// --- what: values at the markers and the map colour (box on the map) ------------------
function renderShow() {
  const layers = layersOf(state.day);
  const values = document.getElementById("values");
  values.replaceChildren(
    ...layers.map((layer) => {
      const label = element("label", null, "check");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = state.shown.includes(layer);
      box.addEventListener("change", () => {
        const shown = box.checked ? [...state.shown, layer] : state.shown.filter((l) => l !== layer);
        update({ shown: ALL_LAYERS.filter((l) => shown.includes(l)) });
      });
      label.append(box, glyph(layer), element("span", t(`layer.${layer}`)));
      return label;
    }),
  );
  const colours = document.getElementById("colours");
  colours.replaceChildren(
    ...layers.map((colour) => {
      const label = element("label", null, "check");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "colour";
      radio.checked = colour === colourOf(state);
      radio.addEventListener("change", () => update({ colour }));
      label.append(radio, element("span", t(`layer.${colour}`)));
      return label;
    }),
  );
  document.getElementById("stations-box").hidden = !isPast(state.day);
  document.getElementById("stations-toggle").checked = showStations;
  renderScale();
}

function renderScale() {
  const box = document.getElementById("scale");
  // a single model: rain in mm (no probability), its raw cloud cover; a past day: measured
  const view = shownView();
  const single = Boolean(view?.single);
  const colour = colourOf(state);
  const key = rampKey(colour, mmView(view));
  const ramp = RAMPS[key];
  if (!ramp) {
    box.replaceChildren();
    return;
  }
  const [low, high] = [ramp[0][0], ramp.at(-1)[0]];
  const stops = ramp.map(([v]) => `${colorFor(v, key)} ${((v - low) / (high - low)) * 100}%`);
  const bar = element("div", null, "bar");
  bar.style.background = `linear-gradient(to right, ${stops.join(", ")})`;
  const show = (v) => ({
    temperature: `${v}°`, precipitation: `${v * 100} %`, precipitationMm: `${v} mm`, wind: `${v} m/s`, cloud: `${v} %`,
    gust: `${v} m/s`, sunshine: `${v} h`,
  })[key];
  let title = single && colour === "cloud" ? "scale.cloudModel" : `scale.${key}`;
  if (view?.observed) title = `obs.scale.${key}`;
  box.replaceChildren(
    element("div", t(title), "scale-title"),
    bar,
    element("div", `${show(low)} … ${show(high)}`, "scale-ends"),
  );
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
    update({ okres: o.code });
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
    chip.hidden = !shown.includes(layer);
    any ||= !chip.hidden;
    text.textContent = labelFor(row, layer, part);
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
    setMarker(entry, rowFor(outlook, code, state.day, state.part), state.part, shownOf(state));
  }
  declutter();
}

function declutter() {
  const boxes = [...markers]
    .filter(([, m]) => m.el.style.display !== "none")
    .map(([code, m]) => {
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
// the note on the map while a single model is shown (or loading), with the way back
function modelBanner(view) {
  if (mapStatus?.failed) return element("p", t("tv.bannerFailed", { model: modelName(mapStatus.failed) }), "model-banner failed");
  if (mapStatus?.loading) return element("p", t("tv.bannerLoading", { model: modelName(mapStatus.loading) }), "model-banner");
  if (!view.single) return null;
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

// "1 stanice", "3 stanice", "12 stanic" / "1 station", "12 stations"
const plural = new Intl.PluralRules(language);
const stationsText = (n) => t(`obs.st.${plural.select(n) === "one" ? "one" : plural.select(n) === "few" ? "few" : "other"}`, { n });
const fmt1 = (v) => (v == null ? "–" : v.toLocaleString(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }));

// the badge every past day carries, so it is never taken for a forecast
function pastBanner(view) {
  const banner = element("p", null, "past-banner");
  banner.append(element("strong", t("obs.badge")), element("span", t(view.source === "daily" ? "obs.bannerDaily" : "obs.bannerHourly")));
  return banner;
}

function renderPastHeadline(view) {
  const box = document.getElementById("headline");
  box.classList.remove("single");
  box.classList.add("past");
  const heading = element("h2", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`);
  const children = [pastBanner(view), heading];
  if (view.loading || view.failed) {
    children.push(element("p", t(view.loading ? "obs.loading" : "obs.failed")));
    box.replaceChildren(...children);
    return;
  }
  const s = observedSummary(view, state.part);
  if (!s.okresy) {
    children.push(element("p", t("obs.noPart")));
    box.replaceChildren(...children);
    return;
  }
  const line = (layer, text) => {
    const p = element("p", null, "line");
    p.append(glyph(layer), element("span", text));
    return p;
  };
  const colour = colourOf(state);
  const shown = (l) => shownOf(state).includes(l) || colour === l;
  const name = (hit) => displayName(hit.name);
  if (shown("temperature") || !OBSERVED_LAYERS.some(shown)) {
    const warm = s.warmest && line("temperature", t(state.part === "night" ? "obs.warmestNight" : "obs.warmest", { okres: name(s.warmest), value: fmt(s.warmest.value) }));
    const cold = s.coldest && line("temperature", t("obs.coldest", { okres: name(s.coldest), value: fmt(s.coldest.value) }));
    children.push(...(state.part === "night" ? [cold, warm] : [warm, cold]).filter(Boolean));
  }
  if (shown("precipitation") && s.wettest) {
    const rained = s.wettest.value >= 0.1;
    children.push(line("precipitation", rained
      ? t("obs.wettest", { okres: name(s.wettest), value: fmt1(s.wettest.value), station: fmt1(s.wettestStation?.value) })
      : t("obs.dry")));
    if (rained) children.push(line("precipitation", t("obs.wetOkresy", { n: s.wet, of: s.rainOkresy })));
  }
  if ((shown("wind") || shown("gust")) && s.gust) {
    children.push(line("gust", t("obs.gust", { okres: name(s.gust), value: fmt(s.gust.value) })));
  }
  if (shown("sunshine") && s.sunniest) {
    children.push(line("sunshine", t("obs.sunniest", { okres: name(s.sunniest), value: fmt1(s.sunniest.value) })));
  }
  if (playing && RAMPS[colour]) {
    const badge = element("p", null, "playing");
    badge.append(glyph(colour), element("span", t("tv.mapShows", { layer: t(`layer.${colour}`) })));
    children.splice(2, 0, badge);
  }
  children.push(element("p", t("obs.from", { n: s.stations }), "source"));
  box.replaceChildren(...children);
}

function renderHeadline(outlook) {
  if (outlook.observed) {
    renderPastHeadline(outlook);
    return;
  }
  document.getElementById("headline").classList.remove("past");
  const s = summary(outlook, state.day, state.part);
  const box = document.getElementById("headline");
  const banner = modelBanner(outlook);
  box.classList.toggle("single", Boolean(outlook.single));
  if (!s) {
    const note = outlook.single && outlook.lastHour != null
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
  const shown = (l) => shownOf(state).includes(l) || colourOf(state) === l;
  // temperature also when nothing else is chosen
  if (shown("temperature") || !LAYERS.some(shown)) {
    const warm = line("temperature", t("tv.warmest", { okres: displayName(s.warmest.name), value: fmt(s.warmest.value) }));
    const cold = line("temperature", t("tv.coldest", { okres: displayName(s.coldest.name), value: fmt(s.coldest.value) }));
    // at night the coldest place comes first
    lines.push(...(state.part === "night" ? [cold, warm] : [warm, cold]));
  }
  if (shown("precipitation")) {
    lines.push(line("precipitation", t(s.single ? "tv.rainyModel" : "tv.rainy", { n: s.rainy, of: s.okresy })));
  }
  if (shown("wind")) lines.push(line("wind", t("tv.windiest", { okres: displayName(s.windiest.name), value: fmt(s.windiest.value) })));
  if (shown("cloud")) lines.push(line("cloud", t("tv.clearIn", { n: s.clear, of: s.okresy })));
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
  if (playing && RAMPS[colourOf(state)]) {
    // while playing the map colour changes every round: say which one it is
    const badge = element("p", null, "playing");
    badge.append(glyph(colourOf(state)), element("span", t("tv.mapShows", { layer: t(`layer.${colourOf(state)}`) })));
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
    ]).then(([weights, models, meta]) => {
      entry.table = weightTable(weights);
      entry.parsed = parseModels(models);
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
  if (!data.periods.has(panelModel)) data.periods.set(panelModel, modelPeriods(data.parsed, panelModel));
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

const rainText = (row, single) => {
  if (!single) return percent(row.rain_probability);
  return row.precipitation == null ? "–" : `${fmt(row.precipitation, 1)} mm`;
};

function partCell(row, part, single) {
  const cell = element("div", null, "part");
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
    ...(mapView && mapModel !== COMBINED ? [mapModel] : []),
  ]);
  const chosen = fillPicker(select, {
    table: data.table,
    names: { ...modelNames, ...data.names },
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
  if (data.status === "loading") notes.push(element("p", t("tv.modelLoading"), "model-note"));
  if (data.status === "missing") notes.push(element("p", t("tv.modelUnavailable"), "model-note"));
  if (single) {
    let text = t("tv.modelNote", { time: issuedText(rows.generated) ?? "–" });
    // days of our forecast the model does not cover whole
    const cut = outlook.days.some((day) => rowFor(outlook, state.okres, day, "day") && !periods.get(`${day}|day`));
    if (cut && rows.end != null) text += ` ${t("tv.modelHorizon", { end: endText(rows.end) })}`;
    const note = element("p", text, "model-note");
    note.title = t("tv.modelNoteMore");
    notes.push(note);
  }
  if (panelModel !== mapModel) notes.push(element("p", t("tv.panelOnly", { map: modelName(mapModel) }), "model-note"));
  return [label, ...notes];
}

// the day's strongest wind and, where the single runs reach, its strongest gust
function windCell(row) {
  if (!row) return element("td", "", "num");
  if (row.gust == null) return element("td", `${fmt(row.wind)} m/s`, "num");
  const td = element("td", `${fmt(row.wind)} / ${fmt(row.gust)} m/s`, row.gust_warning ? "num gust-warning" : "num");
  td.title = t("tv.windGustCell");
  return td;
}

function renderPanel(outlook) {
  const panel = document.getElementById("okres-panel");
  if (!state.okres) {
    panel.replaceChildren();
    return;
  }
  if (isPast(state.day)) {
    renderPastPanel(shownView());
    return;
  }
  panel.classList.remove("past");
  const info = outlook.okresy.find((o) => o.code === state.okres);
  const data = okresData(state.okres);
  const rows = panelRows(data);
  const { single, rowOf } = rows;
  panel.classList.toggle("single", single);
  const now = rowOf(state.day, state.part);
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("chart.close"));
  close.addEventListener("click", () => update({ okres: null }));
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
      single
        ? t("tv.rainModel", { amount: fmt(now.precipitation, 1) })
        : t("tv.rain", { chance: percent(now.rain_probability), amount: fmt(now.precipitation, 1) }),
      // gusts from the single runs: null beyond the newest run and in older files
      now.gust != null ? t("tv.windGust", { value: fmt(now.wind), gust: fmt(now.gust) }) : t("tv.wind", { value: fmt(now.wind) }),
      t("tv.cloud", { value: fmt(now.cloud) }),
    ]) {
      facts.append(element("li", text));
    }
    if (now.gust_warning) facts.append(element("li", t("tv.gustWarning"), "gust-warning"));
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
  const detail = element("a", t("tv.detail"));
  detail.href = `forecast.html#${state.okres}`;
  panel.replaceChildren(
    close,
    element("h2", displayName(info?.name ?? state.okres)),
    element("p", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`, "when"),
    ...modelPicker(data, rows),
    big,
    facts,
    strip,
    week,
    detail,
  );
}


// --- the okres panel of a past day: what was measured, and what we had forecast ---------
const symbolMeasured = (symbol) => (symbol ? t(`diary.symbol.${symbol}`) : "");

/** The measured values of an okres's part of day, each with its number of stations. */
function measuredFacts(row) {
  const facts = element("ul", null, "facts");
  const add = (text, className) => facts.append(element("li", text, className));
  const n = row.counts;
  if (row.symbol) add(symbolMeasured(row.symbol));
  if (n.t) {
    let text = t("obs.temp", { high: fmt(row.tmax), low: fmt(row.tmin), stations: stationsText(n.t) });
    if (n.t > 1) text += ` ${t("obs.tempRange", { low: fmt(row.tmin_lo), high: fmt(row.tmax_hi) })}`;
    add(text);
  } else add(t("obs.noTemp"), "missing");
  if (n.r) {
    let text = t("obs.rain", { amount: fmt1(row.precipitation), stations: stationsText(n.r) });
    if (n.r > 1 && row.precipitation_hi > 0) text += ` ${t("obs.rainMax", { amount: fmt1(row.precipitation_hi) })}`;
    add(text);
  } else add(t("obs.noRain"), "missing");
  if (n.w && n.g) {
    add(t("obs.wind", { wind: fmt(row.wind), gust: fmt(row.gust), stations: stationsText(Math.max(n.w, n.g)) }));
  } else if (n.g) {
    // older days (daily values): the gust only
    add(t("obs.gustOnly", { gust: fmt(row.gust), stations: stationsText(n.g) }));
  } else if (n.w) {
    add(t("obs.windOnly", { wind: fmt(row.wind), stations: stationsText(n.w) }));
  } else add(t("obs.noWind"), "missing");
  if (n.s) add(t("obs.sunshine", { hours: fmt1(row.sunshine), stations: stationsText(n.s) }));
  if (n.c) add(t("obs.cloud", { value: fmt(row.cloud), stations: stationsText(n.c) }));
  if (row.ph?.length) add(t("obs.phenomena", { list: row.ph.map((c) => t(`pheno.${c}`)).join(", ") }));
  return facts;
}

/** "13° · 1.4 mm" with the symbol: one side of the comparison. */
function compareCell(row, part, measured) {
  const td = element("td", null, "cmp");
  if (!row) {
    td.textContent = "–";
    return td;
  }
  const symbol = measured ? symbolMeasured(row.symbol) : symbolText(row.symbol);
  td.append(
    iconCanvas(iconName(row.symbol, part, measured ? row : { dark: part === "night" }), 22, symbol),
    element("strong", labelFor({ ...row, measured: true }, "temperature", part)),
    element("span", row.precipitation == null ? "–" : `${fmt1(row.precipitation)} mm`, "rain"),
  );
  if (!measured && row.rain_probability != null) td.title = t("tv.rain", { chance: percent(row.rain_probability), amount: fmt1(row.precipitation) });
  return td;
}

/** "Forecast vs. measured": our archived forecast of that day beside the measurements. */
function compareSection(view) {
  const box = element("section", null, "compare");
  box.append(element("h3", t("obs.compareTitle")));
  const forecasts = view.forecasts ?? [];
  if (!forecasts.length) {
    box.append(element("p", t("obs.noForecast"), "model-note"));
    return box;
  }
  const lead = forecasts.some((f) => f.lead === panelLead) ? panelLead : defaultLead(forecasts);
  const chosen = forecasts.find((f) => f.lead === lead);
  if (forecasts.length > 1) {
    const leads = element("div", null, "segmented leads");
    leads.setAttribute("aria-label", t("obs.leadPick"));
    for (const f of forecasts) {
      const button = element("button", t(`obs.lead.${Math.min(f.lead, 3)}`, { n: f.lead }));
      button.type = "button";
      button.setAttribute("aria-pressed", String(f.lead === lead));
      button.addEventListener("click", () => {
        panelLead = f.lead;
        renderPanel(outlook);
      });
      leads.append(button);
    }
    box.append(leads);
  }
  box.append(element("p", t(`obs.issued.${Math.min(lead, 3)}`, { n: lead, time: issuedText(chosen.issued) ?? "–" }), "model-note"));
  const table = element("table", null, "compare-table");
  const head = element("tr");
  head.append(element("th", ""), element("th", t("obs.forecast")), element("th", t("obs.measured")), element("th", "Δ", "num"));
  head.lastChild.title = t("obs.deltaHint");
  table.append(head);
  for (const part of view.parts) {
    const measured = rowFor(view, state.okres, state.day, part);
    const forecast = chosen.rows.get(`${state.okres}|${part}`);
    const tr = element("tr", null, part === state.part ? "current" : "");
    tr.addEventListener("click", () => update({ part }));
    const delta = difference(forecast, measured, "temperature", part);
    tr.append(
      element("td", t(`part.${part}`)),
      compareCell(forecast, part, false),
      compareCell(measured, part, true),
      element("td", delta == null ? "" : `${delta > 0 ? "+" : ""}${fmt(delta)}°`, "num delta"),
    );
    table.append(tr);
  }
  box.append(table, element("p", t("obs.compareNote"), "model-note"));
  return box;
}

/** The okres's stations that day, linked to their pages (the diary opens on that day). */
function stationsSection(view) {
  const ids = rowFor(view, state.okres, state.day, "day")?.stations ?? [];
  const box = element("section", null, "obs-stations");
  box.append(element("h3", t("obs.stationsTitle", { stations: stationsText(ids.length) })));
  if (!ids.length) {
    box.append(element("p", t("obs.noStations"), "model-note"));
    return box;
  }
  const list = element("ul");
  const names = new Map();
  for (const id of ids) {
    const a = element("a", id);
    a.href = stationLink(id, state.day);
    names.set(id, a);
    const li = element("li");
    li.append(a);
    list.append(li);
  }
  stationIndex ??= getJson("data/scores/station/index.json");
  stationIndex.then((index) => {
    for (const s of index?.stations ?? []) if (names.has(s.id)) names.get(s.id).textContent = s.name;
  });
  box.append(list);
  return box;
}

function renderPastPanel(view) {
  const panel = document.getElementById("okres-panel");
  panel.classList.remove("single");
  panel.classList.add("past");
  const info = outlook.okresy.find((o) => o.code === state.okres);
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("chart.close"));
  close.addEventListener("click", () => update({ okres: null }));
  const when = element("p", null, "when");
  when.append(element("span", t("obs.badge"), "past-badge"), element("span", ` ${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`));
  const head = [close, element("h2", displayName(info?.name ?? state.okres)), when];
  if (view.loading || view.failed) {
    panel.replaceChildren(...head, element("p", t(view.loading ? "obs.loading" : "obs.failed")));
    return;
  }
  const row = rowFor(view, state.okres, state.day, state.part);
  const big = element("div", null, "now");
  big.append(
    iconCanvas(row ? iconName(row.symbol, state.part, row) : "", 64, symbolMeasured(row?.symbol)),
    element("div", row ? labelFor(row, "temperature", state.part) : "–", "big-temp"),
  );
  const children = [...head, big];
  if (row) children.push(measuredFacts(row));
  if (view.parts.length > 1) {
    const strip = element("div", null, "strip");
    strip.append(...PARTS.slice(0, 4).map((p) => partCell(rowFor(view, state.okres, state.day, p), p, true)));
    children.push(strip);
  } else {
    children.push(element("p", t("obs.dailyNote"), "model-note"));
  }
  children.push(compareSection(view), stationsSection(view), element("p", t("obs.panelNote"), "model-note"));
  panel.replaceChildren(...children);
}

// --- the stations' own values (dots), past days only -------------------------------------
const NO_STATIONS = { type: "FeatureCollection", features: [] };

function stationLabel(value, layer, part) {
  const row = { measured: true, tmax: value, tmin: value, precipitation: value, wind: value, gust: value, sunshine: value, cloud: value };
  return labelFor(row, layer, part);
}

function paintStations() {
  const source = map.getSource("obs-stations");
  if (!source) return;
  if (!(isPast(state.day) && showStations)) {
    source.setData(NO_STATIONS);
    return;
  }
  const { day, part } = state;
  const layer = colourOf(state);
  stationIndex ??= getJson("data/scores/station/index.json");
  if (!stationDocs.has(day)) stationDocs.set(day, getJson(`data/scores/observed/${day}-stations.json`));
  Promise.all([stationDocs.get(day), stationIndex]).then(([doc, index]) => {
    if (state.day !== day || state.part !== part || colourOf(state) !== layer || !showStations) return;
    const key = rampKey(layer, true);
    const features = stationValues(doc, index, part, layer).map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      properties: {
        id: p.id, name: p.name, label: stationLabel(p.value, layer, part),
        color: RAMPS[key] ? colorFor(p.value, key) : "#7b8791",
      },
    }));
    source.setData({ type: "FeatureCollection", features });
  });
}

function stationPopup(event) {
  const feature = event.features?.[0];
  if (!feature) return;
  const { id, name, label } = feature.properties;
  const box = element("div", null, "station-pop");
  const link = element("a", t("obs.stationLink"));
  link.href = stationLink(id, state.day);
  box.append(element("strong", name), element("span", ` ${label}`), element("br"), link);
  new Popup({ closeButton: true, maxWidth: "16rem" }).setLngLat(feature.geometry.coordinates).setDOMContent(box).addTo(map);
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

function paintFill(colours) {
  const pairs = [...colours].flat();
  map.setPaintProperty("okresy-fill", "fill-color", pairs.length ? ["match", ["get", "code"], ...pairs, NEUTRAL] : NEUTRAL);
}

/** Draw the current state at once (after a click, or at the end of a transition). */
function update(change = {}, fromPlay = false) {
  if (!fromPlay) stopPlay();
  // another okres (or none) starts on the forecast the map shows
  if ("okres" in change && change.okres !== state.okres) panelModel = mapModel;
  if ("day" in change && change.day !== state.day) panelLead = null;
  state = { ...state, ...change };
  const view = shownView();
  // an older measured day has the whole day only
  if (view.observed && !view.loading && !view.parts.includes(state.part)) state = { ...state, part: "day" };
  window.history.replaceState(null, "", viewHash(state));
  renderWhen();
  renderShow();
  paintFill(okresColours(view, state.day, state.part, colourOf(state)));
  map.setFilter("okres-selected", ["==", ["get", "code"], state.okres ?? ""]);
  paintMarkers(view);
  renderHeadline(view);
  renderPanel(outlook);
  paintStations();
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
  renderWhen();
  renderHeadline(shownView());
}

/** Move to `target` (a part of state), interpolating colours and values; false if stopped. */
async function transition(target, token) {
  const from = { ...state };
  const to = { ...state, ...target };
  const view = shownView();
  const coloursFrom = okresColours(view, from.day, from.part, colourOf(from));
  const coloursTo = okresColours(view, to.day, to.part, colourOf(to));
  // the labels and boxes already show where we are going
  state = to;
  renderWhen();
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
      colourOf(from) === colourOf(to)
        ? new Map([...coloursTo].map(([code, c]) => [code, mixColor(coloursFrom.get(code) ?? c, c, f)]))
        : switchColours(coloursFrom, coloursTo, Math.min(1, elapsed / SWITCH_MS)),
    );
    for (const [code, entry] of markers) {
      const row = lerpRow(rowFor(view, code, from.day, from.part), rowFor(view, code, to.day, to.part), f);
      setMarker(entry, row, f < 0.5 ? from.part : to.part, shownOf(to));
    }
    if (f >= 1) break;
  }
  update({}, true);
  return true;
}

/**
 * Play the parts of the shown day ("day") or of every day ("week"), from the part shown
 * now; after each round start again with the next map colour (temperature → rain →
 * wind → cloud → temperature), which is then also shown at the okresy.
 */
async function play(scope) {
  stopPlay();
  playing = scope;
  const token = ++playToken;
  const chosen = state.shown;
  // a single model: only the parts it covers
  const steps = playSteps(shownView(), scope, state.day);
  if (steps.length === 0) return stopPlay();
  let i = startIndex(steps, state.day, state.part);
  renderWhen();
  if (!(await transition(steps[i], token))) return;
  for (;;) {
    await sleep(HOLD_MS);
    if (token !== playToken) return;
    i += 1;
    let target = steps[i % steps.length];
    if (i % steps.length === 0) {
      const layers = layersOf(state.day);
      const colour = nextColour(colourOf(state), layers);
      target = { ...target, colour, shown: ALL_LAYERS.filter((l) => chosen.includes(l) || l === colour) };
    }
    if (!(await transition(target, token))) return;
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
  select.replaceChildren(
    option(COMBINED, t("forecast.pickCombined")),
    ...(ranked.length ? [group("tv.mapModelRanked", ranked)] : []),
    ...(others.length ? [group("tv.mapModelOthers", others)] : []),
  );
  select.value = mapModel;
  select.disabled = !mapReady || options.length === 0;
  document.getElementById("map-model").title = t(options.length ? "tv.mapModelHint" : "tv.mapModelsMissing");
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
    update();
    return;
  }
  if (!modelViews.has(model)) {
    mapStatus = { loading: model };
    renderHeadline(shownView());
    const doc = await getJson(`data/scores/forecast/models-parts/${model}.json`);
    const view = parseModelParts(doc, outlook);
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
  panelModel = mapModel;
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
  // the stations' own values on a past day ("Stations" in the box), above the okresy
  map.addSource("obs-stations", { type: "geojson", data: NO_STATIONS });
  map.addLayer({
    id: "obs-stations",
    type: "circle",
    source: "obs-stations",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 4, 9, 7],
      "circle-color": ["get", "color"],
      "circle-stroke-color": "#1d2329",
      "circle-stroke-width": 1,
    },
  });
  map.on("click", "obs-stations", stationPopup);
  map.on("mouseenter", "obs-stations", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "obs-stations", () => (map.getCanvas().style.cursor = ""));
  map.on("click", "okresy-fill", (event) => {
    // a click on a station dot opens its popup, not the okres
    if (map.queryRenderedFeatures(event.point, { layers: ["obs-stations"] }).length) return;
    update({ okres: event.features[0].properties.code });
  });
  map.on("mouseenter", "okresy-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "okresy-fill", () => (map.getCanvas().style.cursor = ""));
  map.on("moveend", declutter);
}

async function main() {
  // the forecast, and the index of the measured past days (small; may be missing)
  const [outlookDoc, observedDoc] = await Promise.all([
    getJson("data/scores/outlook.json"),
    getJson("data/scores/observed/index.json"),
  ]);
  outlook = parseOutlook(outlookDoc);
  observedIndex = parseObservedIndex(observedDoc);
  const status = document.getElementById("status");
  if (outlook.okresy.length === 0) {
    status.textContent = t("tv.none");
    return;
  }
  const generated = outlook.generated ? new Date(outlook.generated) : null;
  status.textContent = generated && !Number.isNaN(generated.getTime())
    ? t("tv.updated", {
      time: new Intl.DateTimeFormat(language, { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague" }).format(generated),
    })
    : "";
  const now = Date.now();
  const first = outlook.days.includes(today(now)) ? today(now) : outlook.days[0];
  const pastDays = observedIndex.days.map((d) => d.day).filter((d) => d < today(now));
  state = parseView(window.location.hash, { ...outlook, days: [...pastDays, ...outlook.days] }, {
    day: first,
    part: first === today(now) ? currentPart(now) : "afternoon",
  });
  // phones: the box starts folded so the map stays visible
  const show = document.getElementById("show");
  if (window.innerWidth <= 700) show.open = false;
  document.getElementById("play-day").addEventListener("click", () => togglePlay("day"));
  document.getElementById("play-week").addEventListener("click", () => togglePlay("week"));
  document.getElementById("stations-toggle").addEventListener("change", (event) => {
    showStations = event.target.checked;
    paintStations();
  });
  const picker = document.getElementById("map-model-select");
  picker.setAttribute("autocomplete", "off");
  renderMapPicker();
  picker.disabled = true; // until the map is there
  // the models offered for the whole map, by their mean rank over Czechia
  metaJson ??= getJson("data/scores/meta.json");
  Promise.all([getJson("data/scores/forecast/models-parts/index.json"), metaJson]).then(([index, meta]) => {
    modelIndex = index;
    modelNames = { ...meta?.models };
    renderMapPicker();
    if (state.okres) renderPanel(outlook);
  });
  await mapLoaded;
  addLayers();
  buildMarkers(outlook);
  mapReady = true;
  update();
  picker.addEventListener("change", () => setMapModel(picker.value));
  renderMapPicker();
}

main();
