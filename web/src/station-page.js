// The measured-weather page (measured.html, "Naměřeno / Measured"): without a station
// the map of what ČHMÚ's stations measured, by day and part of day, each station with
// its own values or each okres with the mean of its stations (measured.js,
// data/scores/observed/ from `mvd observed-map`); "Kinds of station" the map of the
// network. With a station (#WSI): its weather day by day (the diary), then every element
// it measures with its history (site/data/station/<WSI>.json from `mvd station-pages`).
import * as Plot from "@observablehq/plot";

import "./style.css";

import { setUpLanguage } from "./i18n.js";
import {
  VIEWS, defaultElement, elementLabel, elementName, elementOrder, unitOf, formatNumber, isTotal, latestValues,
  parseStationHash, searchStations, seriesPoints, spanLabel, stepTime, viewsWith,
} from "./station.js";
import {
  KIND_COLORS, classifyStation, elementFor, elevationGradient, ELEVATION_STOPS, filterStations, hasElements,
  kindCounts, measureCounts, withCoordinates,
} from "./station-map.js";
import { createStationMap } from "./station-map-view.js";
import { createDiary } from "./diary-view.js";
import { parseDiaryQuery } from "./diary.js";
import { glyph } from "./icons.js";
import {
  DEFAULT_LAYER, KINDS_HASH, dayTabs, defaultDay, kindsStation, landingHash, okresRows, pageMode, parseLanding, stationHref, stationRows,
  stationSummary,
} from "./measured.js";
import { createMeasuredMap } from "./measured-map-view.js";
import { errorRampKey, renderScale } from "./palette.js";
import { createOkresPanel } from "./measured-okres.js";
import { OBSERVED_LAYERS, nearestDay, observedSummary, parseObservedDay, parseObservedIndex } from "./observed.js";
import {
  DEFAULT_SHOWN, dayLabel, displayName, labelFor, okresColours, rampKey, today, valueFor,
} from "./tv.js";
import { keepRoomForPanels } from "./panel-room.js";
import { DEFAULT_ERR, DEFAULT_MODEL, ERROR_VARS, LEADS, AI, createModelCompare, errorLookup, modelOptions, splitModelHash, withModelHash } from "./station-model.js";

const t = setUpLanguage();
const language = document.documentElement.lang;
const DATA = "data/scores/station";
const OBSERVED = "data/scores/observed";
const $ = (id) => document.getElementById(id);

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function el(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

const DATE = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { dateStyle: "medium" });
const DATE_TIME = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Prague",
});
const updated = (generated) => {
  const time = generated ? new Date(generated) : null;
  return time && !Number.isNaN(time.getTime()) ? t("station.updated", { time: DATE_TIME.format(time) }) : "";
};

const diary = createDiary({ dataPath: DATA, t, language });
const models = createModelCompare({ getJson, t, language });

/** The hash of the page without the model choice (";m=…;l=…", station-model.js); a choice in it
 * becomes the page's. */
function cleanHash() {
  const { hash, model, lead, err } = splitModelHash(window.location.hash);
  if (model) {
    models.state.model = model;
    models.state.lead = lead;
    models.state.err = err === undefined ? DEFAULT_ERR : err;
  }
  return hash;
}
/** A hash of the page with the model choice appended. */
const hashWith = (hash) => withModelHash(hash, models.state);

// --- search: the index of all stations ------------------------------------------------
let index = [];

function fillSearch() {
  const list = $("station-list");
  list.replaceChildren(
    ...index.map((s) => {
      const option = document.createElement("option");
      option.value = s.name;
      option.label = [s.okres, s.elevation != null ? `${Math.round(s.elevation)} m` : null].filter(Boolean).join(", ");
      return option;
    }),
  );
  const input = $("search");
  const go = () => {
    const [hit] = searchStations(index, input.value, 1);
    // from the measured map: the diary opens on the day shown there
    if (hit) openStation(hit.id, mode === "measured" ? landing?.day : null);
  };
  input.addEventListener("change", go);
  $("controls").addEventListener("submit", (event) => {
    event.preventDefault();
    go();
  });
}

// --- one station ------------------------------------------------------------------------
let doc = null;

function facts(station) {
  const parts = [station.id];
  if (station.elevation != null) parts.push(t("station.elevation", { m: formatNumber(Math.round(station.elevation)) }));
  if (station.lat != null) parts.push(`${station.lat.toFixed(4)}° N, ${station.lon.toFixed(4)}° E`);
  if (station.okres) parts.push(`${t("control.okres")} ${displayName(station.okres)}`);
  if (station.active != null) parts.push(t(station.active ? "station.active" : "station.closed"));
  return parts.join(" · ");
}

// 24-hour clock in both languages
const TICK = {
  "10min": (d) => d.toLocaleString(language === "cs" ? "cs-CZ" : "en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }),
};

/** A time as the view needs it: the minute, the day, the month or the year. */
function when(view, time) {
  if (view === "phenomena") return String(time.getUTCFullYear());
  if (view === "monthly") return time.toISOString().slice(0, 7);
  if (view === "daily") return DATE.format(time);
  return DATE_TIME.format(time);
}

function chart(view, element) {
  const series = doc.series[view];
  const points = seriesPoints(series, element);
  if (!points.length) return null;
  const entry = doc.elements[element];
  const how = series.how?.[element] ?? "";
  const unit = unitOf(entry, language) ?? "";
  const bars = isTotal(element, how, view);
  const unitLabel = view === "phenomena" ? t("station.days") : unit;
  const width = Math.min(1100, document.querySelector("main").clientWidth - 8);
  const withGaps = seriesPoints(series, element, true);
  let mark;
  if (bars && points.length * 2 < width) {
    mark = Plot.rectY(points, {
      x1: "time",
      x2: (p) => stepTime(p.time, series.step, 1), // one period, also before a gap
      y: "value",
      fill: "#1f78b4",
      inset: points.length * 4 < width ? 0.5 : 0, // a gap between bars only where they are wide
    });
  } else if (bars) {
    // more bars than pixels: a filled step area, which stays visible
    mark = Plot.areaY(withGaps, { x: "time", y: "value", curve: "step-after", fill: "#1f78b4" });
  } else {
    mark = Plot.lineY(withGaps, {
      x: "time", y: "value", stroke: "#1f78b4", strokeWidth: view === "monthly" ? 1 : 1.3,
    });
  }
  const plot = Plot.plot({
    width,
    height: 230,
    marginLeft: 52,
    style: { fontSize: "11px" },
    x: { label: null, type: "utc", tickFormat: TICK[view] },
    y: { label: unitLabel || null, grid: true, tickFormat: (v) => formatNumber(v) },
    marks: [
      mark,
      Plot.tip(points, Plot.pointerX({
        x: "time",
        y: "value",
        title: (p) => `${when(view, p.time)}\n${formatNumber(p.value)} ${unitLabel}`,
      })),
    ],
  });
  const box = el("section", null, "station-chart");
  const heading = el("h3", t(`station.view.${view}`));
  heading.append(el("span", ` · ${spanLabel(points)}`, "muted"));
  box.append(heading, plot);
  return box;
}

function renderCharts(element) {
  const charts = VIEWS.map((view) => chart(view, element)).filter(Boolean);
  $("charts").replaceChildren(...charts);
  const hows = VIEWS.map((v) => doc.series[v]?.how?.[element]).filter(Boolean);
  $("how").textContent = hows.length ? t("station.how", { how: [...new Set(hows)].join(", ") }) : "";
}

function renderElements() {
  const latest = latestValues(doc);
  const table = $("elements");
  const head = el("tr");
  for (const key of ["code", "name", "height", "since", "latest", "views"]) head.append(el("th", t(`station.col.${key}`)));
  const rows = elementOrder(Object.keys(doc.elements)).map((code) => {
    const entry = doc.elements[code];
    const tr = el("tr");
    const link = el("a", code);
    link.href = `#${doc.station.id}/${code}`;
    const codeCell = el("td");
    codeCell.append(link);
    const value = latest[code];
    const views = viewsWith(doc, code);
    tr.append(
      codeCell,
      el("td", elementLabel(code, entry, language)),
      el("td", entry.height != null ? `${formatNumber(entry.height)} m` : "–"),
      el("td", entry.since ? t("station.since", { since: entry.since, until: entry.until ?? t("station.ongoing") }) : "–"),
      el("td", value ? `${formatNumber(value.value)} ${value.view === "phenomena" ? t("station.days") : (unitOf(entry, language) ?? "")} (${when(value.view, value.time)})` : "–"),
      el("td", views.map((v) => t(`station.short.${v}`)).join(", ") || "–"),
    );
    if (!views.length) tr.className = "muted";
    return tr;
  });
  table.replaceChildren(head, ...rows);
  $("elements-title").hidden = false;
}

function fillElements(current) {
  const select = $("element");
  const codes = Object.keys(doc.elements).filter((e) => viewsWith(doc, e).length);
  codes.sort((a, b) => elementName(a, doc.elements[a], language).localeCompare(elementName(b, doc.elements[b], language), language));
  select.replaceChildren(
    ...codes.map((code) => {
      const option = el("option", `${elementLabel(code, doc.elements[code], language)} · ${code}`);
      option.value = code;
      option.selected = code === current;
      return option;
    }),
  );
  $("pick").hidden = codes.length === 0;
}

// --- the page's three views ---------------------------------------------------------------
let mode = null; // "measured", "kinds" or "station"
let placed = []; // stations of the index with coordinates
let stationIndexDoc = null; // data/scores/station/index.json
const top = $("station-top");
const panel = $("map-panel");
const toggle = $("map-toggle");
let mapOpen = window.innerWidth > 700; // with a station shown; phones start with it folded
let pendingDay = null; // the day the diary opens on, from a click on the measured map
let lastLanding = null; // the measured map's view the station was opened from (the way back)

/** Open a station; `day` (from the measured map) is the day its diary opens on. */
function openStation(id, day = null, event = null) {
  event?.preventDefault();
  if (mode === "measured" && landing) lastLanding = { ...landing };
  const url = new URL(window.location.href);
  url.searchParams.delete("view");
  if (day) url.searchParams.set("day", day);
  else url.searchParams.delete("day");
  url.hash = id;
  window.history.pushState(null, "", url);
  pendingDay = day;
  show();
}

// --- the kinds-of-station map: "Kinds of station", and compact beside a station ----------
function describe(station) {
  const { kind, automatic } = classifyStation(station);
  const parts = [];
  if (station.elevation != null) parts.push(`${formatNumber(Math.round(station.elevation))} m`);
  parts.push(t(`map.one.${kind}`));
  // the manual kinds say "daily" already
  if (!automatic && !["precipitation", "climate_manual"].includes(kind)) parts.push(t("map.daily"));
  return parts.join(" · ");
}

let stationMap = null;
/** The kinds map, made the first time it is shown (one map less on the landing). */
function kindsMap() {
  if (stationMap) return stationMap;
  stationMap = createStationMap({
    container: $("station-map"),
    t,
    describe,
    extraFor: (station) => (kindsErr ? errorText(station, kindsErr) : null),
    onPick: (station) => {
      if (mode === "kinds") {
        openStationPanel(station.id);
        return;
      }
      const measure = $("map-measure").value;
      const element = measure ? elementFor(station, measure) : null;
      window.location.hash = element ? `${station.id}/${element}` : station.id;
    },
  });
  fillMapTools();
  return stationMap;
}

// the Stations view's panel: the Weather view's panel (#okres-panel's look), the map stays put
const stationPanel = $("station-panel");
keepRoomForPanels($("station-map-wrap"), $("station-map"), [stationPanel]);

/** The station's own block at the top of its panel: kind, facts and the link to its page. */
function stationInfo(station) {
  const measure = $("map-measure").value;
  const element = measure ? elementFor(station, measure) : null;
  const open = el("a", t("map.openStation"));
  open.href = `#${station.id}${element ? `/${element}` : ""}`;
  const box = el("div", null, "station-info");
  box.append(el("strong", `${t("map.stationLabel")}: ${station.name ?? station.id}`), el("p", describe(station), "when"), el("p", facts(station), "model-note"), open);
  return box;
}

let stationPanelToken = 0;
let stationPanelState = null; // {id, day, part, okres}: what the panel shows

/** Open (or, with null, close) a station's panel in the Stations view; the hash follows ("#kinds/<id>"). The
 * panel is the Weather view's okres panel (the okres the station is in), with the station's own block in it. */
async function openStationPanel(id, change = null) {
  const station = id && placed.find((s) => s.id === id);
  const token = ++stationPanelToken;
  window.history.replaceState(null, "", hashWith(station ? `${KINDS_HASH}/${encodeURIComponent(id)}` : KINDS_HASH));
  kindsMap().select(station ? id : null, { move: false });
  if (!station) {
    stationPanelState = null;
    stationPanel.replaceChildren();
    kindsMap().fitBeside(false);
    return;
  }
  const start = startView();
  const okresy = await loadOkresy();
  const okres = okresy.find((o) => displayName(o.name) === displayName(station.okres ?? ""))?.code ?? null;
  const day = start.day;
  const part = stationPanelState?.id === id && change?.part ? change.part : stationPanelState?.id === id ? stationPanelState.part : start.part;
  stationPanelState = { id, day, part, okres };
  const data = okres && day ? await dayData("okresy", day) : null;
  if (token !== stationPanelToken || mode !== "kinds") return;
  if (data) {
    stationOkresPanel.render(data, { day, part, okres });
    stationPanel.querySelector(".when")?.after(stationInfo(station));
    stationPanel.querySelector(".station-info")?.after(models.stationSection(station.id));
  } else {
    const close = el("button", "×", "close");
    close.type = "button";
    close.setAttribute("aria-label", t("map.closePanel"));
    close.addEventListener("click", () => openStationPanel(null));
    stationPanel.replaceChildren(close, el("h2", station.name ?? station.id), stationInfo(station), models.stationSection(station.id));
  }
  kindsMap().fitBeside(true);
  // phones: the panel is under the map; bring it into view
  if (window.innerWidth <= 700) stationPanel.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function legendItem(swatch, label) {
  const item = el("span", null, "station-map-legend-item");
  item.append(swatch, el("span", label));
  return item;
}

function dot(color, hollow) {
  const d = el("span", null, `dot${hollow ? " hollow" : ""}`);
  d.style.setProperty("--dot", color);
  d.setAttribute("aria-hidden", "true");
  return d;
}

let kindsErr = null; // the error view of the Stations map's dots (buildErrView), or null

/** What the error colours mean on the Stations map, and where they are missing. */
function kindsErrNote(v) {
  const value = t(`fc.var.${v.key}`).toLowerCase();
  if (v.noFile) return t("measured.err.noFile");
  if (models.state.model === AI) return t("fc.noAi");
  if (!v.hasModel) return t("fc.noModelValue", { model: v.name, value });
  const have = placed.filter((s) => v.byId.get(s.id) != null).length;
  return `${t("measured.err.note", { model: v.name, lead: models.state.lead, value, unit: v.unit, n: formatNumber(have), of: formatNumber(placed.length) })} ${t("map.err.day", { day: v.day })}`;
}

function renderLegend(shown) {
  const items = [];
  if (kindsErr) {
    const box = el("div", null, "station-map-error-scale");
    renderScale(box, kindsErr.ramp, t(`measured.scale.${kindsErr.ramp}`));
    const note = el("p", kindsErrNote(kindsErr), "muted small");
    note.classList.toggle("missing", kindsErr.noFile || !kindsErr.hasModel);
    items.push(box, note);
  } else if ($("map-colour").value === "elevation") {
    const bar = el("span", null, "station-map-ramp");
    bar.style.background = elevationGradient();
    bar.setAttribute("aria-hidden", "true");
    const item = el("span", null, "station-map-legend-item");
    item.append(
      el("span", t("map.elevation")),
      el("span", formatNumber(ELEVATION_STOPS[0][0])),
      bar,
      el("span", formatNumber(ELEVATION_STOPS.at(-1)[0])),
    );
    items.push(item);
  } else {
    for (const [kind, count] of kindCounts(shown)) {
      items.push(legendItem(dot(KIND_COLORS[kind]), `${t(`map.kind.${kind}`)} (${formatNumber(count)})`));
    }
  }
  const neutral = "#5b6670";
  items.push(legendItem(dot(neutral), t("map.automatic")), legendItem(dot(neutral, true), t("map.manual")));
  $("map-legend").replaceChildren(...items);
}

let plainColour = "kind"; // the colour choice when not coloured by error

/** The Stations map's dot colours from the colour select and the shared model choice: by kind,
 * by elevation, or by the error (model − measured) of the newest measured day. */
let kindsColourToken = 0;
async function applyKindsColour() {
  const token = ++kindsColourToken;
  const select = $("map-colour");
  select.value = models.state.err ?? plainColour;
  const err = models.state.err;
  const day = startView().day ?? (await models.loadIndex())?.to;
  const next = err && day ? await buildErrView(day) : null;
  if (token !== kindsColourToken) return;
  kindsErr = next;
  stationMap.setColour(next ? "error" : plainColour, next ? { errors: next.byId, ramp: next.ramp } : {});
  renderLegend(filterStations(placed, $("map-measure").value));
}

function applyFilter() {
  const measure = $("map-measure").value;
  const shown = filterStations(placed, measure);
  stationMap.setStations(placed, shown);
  $("map-count").textContent = measure
    ? t("map.count", { shown: formatNumber(shown.length), all: formatNumber(placed.length) })
    : "";
  renderLegend(shown);
}

function fillMapTools() {
  const box = $("map-measure-box");
  box.hidden = !hasElements(placed);
  if (!box.hidden) {
    const select = $("map-measure");
    const all = el("option", t("map.measure.all"));
    all.value = "";
    select.replaceChildren(
      all,
      ...measureCounts(placed).map(([m, n]) => {
        const option = el("option", `${t(`map.measure.${m}`)} (${formatNumber(n)})`);
        option.value = m;
        return option;
      }),
    );
    select.addEventListener("change", applyFilter);
  }
  $("map-colour").addEventListener("change", () => {
    const value = $("map-colour").value;
    models.state.err = ERROR_VARS.includes(value) ? value : null;
    if (!models.state.err) plainColour = value;
    syncModelHash();
    applyKindsColour();
  });
  applyKindsColour();
  applyFilter();
}

toggle.addEventListener("click", () => {
  mapOpen = !mapOpen;
  setMode("station");
  if (mapOpen) kindsMap().select(doc?.station.id ?? null, { animate: false });
});

/** Show the parts of the page of a view: the measured map, the kinds map, or a station. */
function setMode(next) {
  mode = next;
  const station = next === "station";
  $("measured").hidden = station;
  $("measured-panel").hidden = next !== "measured";
  $("measured-intro").textContent = t(next === "kinds" ? "measured.introKinds" : "measured.intro");
  for (const button of document.querySelectorAll("#mode [data-mode]")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === next));
  }
  $("station-head").hidden = !station;
  top.hidden = next === "measured";
  top.classList.toggle("browse", next === "kinds");
  toggle.hidden = !station;
  $("map-all").hidden = !station;
  $("map-hint").hidden = true; // the intro says it
  $("note").hidden = !station;
  panel.hidden = station && !mapOpen;
  toggle.textContent = t(mapOpen ? "map.hide" : "map.show");
  toggle.setAttribute("aria-expanded", String(!panel.hidden));
  if (next !== "kinds") stationPanel.replaceChildren();
  if (!station) {
    doc = null;
    $("pick").hidden = true;
    $("charts").replaceChildren();
    $("elements").replaceChildren();
    $("elements-title").hidden = true;
    $("detail-title").hidden = true;
    diary.hide();
    $("search").value = "";
  }
}

for (const button of document.querySelectorAll("#mode [data-mode]")) {
  button.addEventListener("click", () => {
    window.location.hash = hashWith(button.dataset.mode === "kinds" ? KINDS_HASH : landingHash(landing ?? startView()));
  });
}

// --- the measured map (the landing) ---------------------------------------------------------
const HOURS = { night: "0–6", morning: "6–12", afternoon: "12–18", evening: "18–24", day: "0–24" };
const PARTS = ["night", "morning", "afternoon", "evening", "day"];
let observedIndex = parseObservedIndex(null);
let landing = null; // {day, part, colour, shown, layer, okres}
let landingToken = 0;
const loaded = new Map(); // "kind|day" → the loaded value (null: failed)
const loading = new Map(); // "kind|day" → its promise
let okresyList = null; // promise of the okresy (outlook.json: code, name, point)

const todayIso = () => today(Date.now());
const fmt = (v, digits = 0) => (v == null ? "–" : v.toFixed(digits));
const fmt1 = (v) => (v == null ? "–" : v.toLocaleString(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }));

const loadOkresy = () => (okresyList ??= getJson("data/scores/outlook.json").then((d) => d?.okresy ?? []));

/** A file of a day, loaded once ("stations": the stations' values; "okresy": the parsed
 * okres view). */
function dayData(kind, day) {
  const key = `${kind}|${day}`;
  if (!loading.has(key)) {
    let promise;
    if (kind === "stations") promise = getJson(`${OBSERVED}/${day}-stations.json`);
    else {
      promise = Promise.all([getJson(`${OBSERVED}/${day}.json`), loadOkresy()]).then(([d, okresy]) => parseObservedDay(d, okresy));
    }
    loading.set(key, promise.then((value) => {
      loaded.set(key, value ?? null);
      return value ?? null;
    }));
  }
  return loading.get(key);
}

/** The view a plain link opens: the newest measured day, the whole day, stations. */
function startView() {
  const day = defaultDay(observedIndex, todayIso());
  return { day, part: "day", colour: "temperature", shown: DEFAULT_SHOWN, layer: DEFAULT_LAYER, okres: null };
}

const isDaily = (day) => observedIndex.byDay.get(day)?.source === "daily";

function dayName(day) {
  const label = dayLabel(day, todayIso(), language);
  return label.key ? t(label.key) : label.name;
}
const dayText = (day) => `${dayName(day)} ${dayLabel(day, todayIso(), language).short}`;

const okresPanel = createOkresPanel({
  panel: $("okres-panel"),
  t,
  language,
  dayText,
  update: (change) => updateLanding(change),
  stationHref: (id) => stationHref(id, landing?.day),
  openStation: (id, event) => openStation(id, landing?.day, event),
  stationIndex: async () => stationIndexDoc,
  // the selected model at the okres's own stations (not at the okres point)
  modelSection: (view, state) => {
    const row = view.rows.get(`${state.okres}|${state.day}|day`);
    const where = new Map(placed.map((s) => [s.id, s]));
    const ids = [...(row?.stations ?? []), ...(row?.high ?? []).map((h) => h.id)];
    const stations = [...new Set(ids)].map((id) => where.get(id)).filter(Boolean);
    return models.okresSection(stations, state.day, (id, event) => openStationFromOkres(id, event));
  },
});

/** One line of a station's (or okres's) values, for its tooltip and its label's name. */
function describeRow(row, part) {
  const parts = [];
  if (errView) parts.push(errorText(row));
  if (row.symbol) parts.push(t(`diary.symbol.${row.symbol}`));
  if (row.tmax != null || row.tmin != null) {
    parts.push(part === "night" ? `min ${fmt(row.tmin)} °C` : `max ${fmt(row.tmax)} °C, min ${fmt(row.tmin)} °C`);
  }
  for (const layer of ["precipitation", "wind", "gust", "sunshine", "cloud"]) {
    if (valueFor(row, layer, part) != null) parts.push(`${t(`layer.${layer}`).toLowerCase()} ${labelFor(row, layer, part)}`);
  }
  return parts.join(" · ");
}

// --- the dots coloured by a model's error (models.state.err) --------------------------------
let errView = null; // {key, ramp, byId, hasModel, noFile, name, day} for the day shown, or null

/** "Model error: +1.2 °C" for a station in the tooltip, or why it has none. */
function errorText(row, v = errView) {
  const e = v.byId.get(row.id);
  if (e != null) return t("measured.err.tip", { model: v.name, lead: models.state.lead, value: v.label(e) });
  if (v.noFile || !v.hasModel) return t("measured.err.tipNone");
  return t(v.byId.has(row.id) ? "measured.err.tipGap" : "measured.err.tipOutside");
}

/** The error view for a day, from the per-day error file: null when the colour is the measured values. */
async function buildErrView(day) {
  const key = models.state.err;
  if (!key) return null;
  const [doc, index] = await Promise.all([models.loadErrors(day), models.loadIndex()]);
  const { model, lead } = models.state;
  const lookup = errorLookup(doc, model, lead, key);
  const name = modelOptions(index, t).find((o) => o.id === model)?.name ?? model;
  const variable = key === "r" ? "mm" : key === "wind" ? "m/s" : "°C";
  const label = (e) => `${e > 0 ? "+" : e < 0 ? "−" : ""}${fmt1(Math.abs(e))} ${variable}`;
  return { key, ramp: errorRampKey(key), unit: variable, name, noFile: !doc, day, label, ...lookup };
}

/** The note under the colour choices: what the colours mean, and where they are missing. */
function renderErrNote(rows) {
  const note = $("err-note");
  const v = errView;
  note.hidden = !models.state.err;
  if (!v) return;
  const value = t(`fc.var.${v.key}`).toLowerCase();
  const text = [];
  if (v.noFile) text.push(t("measured.err.noFile"));
  else if (models.state.model === AI) text.push(t("fc.noAi"));
  else if (!v.hasModel) text.push(t("fc.noModelValue", { model: v.name, value }));
  else {
    const have = rows.filter((r) => v.byId.get(r.id) != null).length;
    text.push(t("measured.err.note", { model: v.name, lead: models.state.lead, value, unit: v.unit, n: formatNumber(have), of: formatNumber(rows.length) }));
  }
  if (landing.layer === "okresy") text.push(t("measured.err.okresy"));
  if (landing.part !== "day" && !isDaily(landing.day)) text.push(t("measured.err.wholeDay"));
  note.classList.toggle("missing", v.noFile || !v.hasModel);
  note.textContent = text.join(" ");
}

const measuredMap = createMeasuredMap({
  container: $("measured-map"),
  t,
  describe: describeRow,
  onPick: (row) => {
    if (row.okresCode) openOkres(row.okresCode);
    else openStation(row.id, landing.day);
  },
  onOkres: (code) => openOkres(code),
});
// a long okres panel reaches below the map instead of resizing it
keepRoomForPanels($("measured-map").parentElement, $("measured-map"), [$("okres-panel")]);


// the same panel in the Stations view (#station-panel), for the okres of the clicked station
const stationOkresPanel = createOkresPanel({
  panel: stationPanel,
  t,
  language,
  dayText,
  update: (change) => openStationPanel(change.okres === null ? null : stationPanelState?.id, change),
  stationHref: (id) => stationHref(id, stationPanelState?.day),
  openStation: (id, event) => openStation(id, stationPanelState?.day, event),
  stationIndex: async () => stationIndexDoc,
});

/** From an okres's table of stations: the station's panel (Stations view, with its model chart). */
function openStationFromOkres(id, event) {
  event?.preventDefault();
  window.location.hash = hashWith(`${KINDS_HASH}/${encodeURIComponent(id)}`);
}

/** Open an okres's panel (okres layer); on phones it is under the map: bring it into view. */
async function openOkres(code) {
  await updateLanding({ okres: code });
  if (window.innerWidth <= 700) $("okres-panel").scrollIntoView({ block: "start", behavior: "smooth" });
}

function updateLanding(change) {
  landing = { ...landing, ...change };
  if (isDaily(landing.day)) landing.part = "day";
  if (landing.layer !== "okresy") landing.okres = null;
  window.history.replaceState(null, "", hashWith(landingHash(landing)));
  return renderLanding();
}

// "older": a date field for any measured day (the tabs have the last 30)
function olderControl(past) {
  const box = el("label", null, "daytab past older");
  const input = document.createElement("input");
  input.type = "date";
  input.min = past[0].day;
  input.max = past.at(-1).day;
  input.value = landing.day;
  input.setAttribute("aria-label", t("obs.pickDate"));
  input.addEventListener("change", () => {
    const day = nearestDay({ days: past }, input.value);
    if (day) updateLanding({ day });
  });
  const short = (day) => dayLabel(day, todayIso(), language).short;
  box.title = t("obs.pickHint", { first: short(past[0].day), last: short(past.at(-1).day) });
  box.append(el("strong", t("obs.older")), input);
  return box;
}

let scrolledTo = null;
function renderWhen() {
  const now = todayIso();
  const days = $("days");
  days.setAttribute("aria-label", t("tv.day"));
  const past = observedIndex.days.filter((d) => d.day < now);
  const tabs = dayTabs(observedIndex, now, landing.day).map((day) => {
    const button = el("button", null, "daytab past");
    button.type = "button";
    button.setAttribute("aria-pressed", String(day === landing.day));
    button.append(el("strong", dayName(day)), el("small", t("obs.tabDate", { date: dayLabel(day, now, language).date })));
    button.addEventListener("click", () => updateLanding({ day }));
    return button;
  });
  // time runs left to right as on the forecast: the date picker for older days first, then
  // the older days, yesterday last (next to where the forecast's "today" would be)
  days.replaceChildren(olderControl(past), ...tabs.reverse());
  const pressed = days.querySelector('.daytab[aria-pressed="true"]');
  if (pressed && scrolledTo !== landing.day) {
    scrolledTo = landing.day;
    // the chosen tab in view (the newest are on the right)
    pressed.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  const daily = isDaily(landing.day);
  const parts = $("parts");
  parts.setAttribute("aria-label", t("tv.part"));
  parts.replaceChildren(
    ...PARTS.map((part) => {
      const button = el("button", null);
      button.type = "button";
      button.setAttribute("aria-pressed", String(part === landing.part));
      // an older day has the whole day only (ČHMÚ's daily values)
      button.disabled = daily && part !== "day";
      if (button.disabled) button.title = t("obs.dayOnly");
      button.append(el("span", t(`part.${part}`)), el("small", HOURS[part]));
      button.addEventListener("click", () => updateLanding({ part }));
      return button;
    }),
  );
  // phones: "on the map" starts folded so the map stays in view
if (window.innerWidth <= 700) $("show").open = false;

for (const button of document.querySelectorAll("#layer [data-layer]")) {
    button.setAttribute("aria-pressed", String(button.dataset.layer === landing.layer));
  }
}

function renderShow() {
  const okresy = landing.layer === "okresy";
  $("values-legend").textContent = t(okresy ? "measured.valuesOkresy" : "measured.values");
  $("colours-legend").textContent = t(okresy ? "tv.colour" : "measured.colour");
  $("measured-hint").textContent = t(okresy ? "measured.hintOkresy" : "measured.hint");
  $("values").replaceChildren(
    ...OBSERVED_LAYERS.map((layer) => {
      const label = el("label", null, "check");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = landing.shown.includes(layer);
      box.addEventListener("change", () => {
        const shown = box.checked ? [...landing.shown, layer] : landing.shown.filter((l) => l !== layer);
        updateLanding({ shown: OBSERVED_LAYERS.filter((l) => shown.includes(l)) });
      });
      label.append(box, glyph(layer), el("span", t(`layer.${layer}`)));
      return label;
    }),
  );
  const err = models.state.err;
  const radioFor = (checked, text, change) => {
    const label = el("label", null, "check");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "colour";
    radio.checked = checked;
    radio.addEventListener("change", change);
    label.append(radio, el("span", text));
    return label;
  };
  $("colours").replaceChildren(
    ...OBSERVED_LAYERS.map((colour) =>
      radioFor(!err && colour === landing.colour, t(`layer.${colour}`), () => {
        models.state.err = null;
        updateLanding({ colour });
      }),
    ),
    // the chosen model's error (model minus measured) at the stations that have stored forecasts
    ...ERROR_VARS.map((value) =>
      radioFor(err === value, t(`measured.err.${value}`), () => {
        models.state.err = value;
        syncModelHash();
        renderLanding();
      }),
    ),
  );
  // the forecast map's scales and legend (palette.js); rain in mm
  if (err) renderScale($("scale"), errorRampKey(err), t(`measured.scale.${errorRampKey(err)}`));
  else {
    const key = rampKey(landing.colour, true);
    renderScale($("scale"), key, t(`${okresy ? "obs" : "measured"}.scale.${key}`));
  }
}

function headlineStart() {
  const box = $("headline");
  const banner = el("p", null, "past-banner");
  banner.append(el("strong", t("obs.badge")), el("span", t(isDaily(landing.day) ? "obs.bannerDaily" : "obs.bannerHourly")));
  return [box, [banner, el("h2", `${dayText(landing.day)}, ${t(`part.${landing.part}`).toLowerCase()}`)]];
}

const line = (layer, ...content) => {
  const p = el("p", null, "line");
  p.append(glyph(layer), el("span", null));
  p.lastChild.append(...content);
  return p;
};

/** A station's name in the headline, linked to its page on that day. */
function stationName(hit) {
  const a = el("a", hit.name);
  a.href = stationHref(hit.id, landing.day);
  a.addEventListener("click", (event) => openStation(hit.id, landing.day, event));
  return a;
}

/** "Nejtepleji: {okres} 17 °C": the text around a name, with the name as a link. */
function withName(key, hit, params) {
  const marker = "\u0000";
  const [before, after = ""] = t(key, { ...params, okres: marker, station: marker }).split(marker);
  return [before, stationName(hit), after];
}

function renderStationHeadline(rows, failed) {
  const [box, children] = headlineStart();
  if (failed || !rows.length) {
    children.push(el("p", t(failed ? "obs.failed" : "obs.noPart")));
    box.replaceChildren(...children);
    return;
  }
  const s = stationSummary(rows, landing.part);
  const shown = (l) => landing.shown.includes(l) || landing.colour === l;
  if (shown("temperature") || !OBSERVED_LAYERS.some(shown)) {
    const warm = s.warmest && line("temperature", ...withName(landing.part === "night" ? "obs.warmestNight" : "obs.warmest", s.warmest, { value: fmt(s.warmest.value) }));
    const cold = s.coldest && line("temperature", ...withName("obs.coldest", s.coldest, { value: fmt(s.coldest.value) }));
    children.push(...(landing.part === "night" ? [cold, warm] : [warm, cold]).filter(Boolean));
  }
  if (shown("precipitation") && s.wettest) {
    if (s.wettest.value >= 0.1) {
      children.push(line("precipitation", ...withName("measured.wettest", s.wettest, { value: fmt1(s.wettest.value) })));
      children.push(line("precipitation", t("measured.wet", { n: formatNumber(s.wet), of: formatNumber(s.rainStations) })));
    } else children.push(line("precipitation", t("measured.dry")));
  }
  if ((shown("wind") || shown("gust")) && s.gust) children.push(line("gust", ...withName("obs.gust", s.gust, { value: fmt(s.gust.value) })));
  if (shown("sunshine") && s.sunniest) children.push(line("sunshine", ...withName("obs.sunniest", s.sunniest, { value: fmt1(s.sunniest.value) })));
  children.push(el("p", t("measured.from", { n: formatNumber(s.stations) }), "source"));
  box.replaceChildren(...children);
}

function renderOkresHeadline(view) {
  const [box, children] = headlineStart();
  const s = view ? observedSummary(view, landing.part) : null;
  if (!s?.okresy) {
    children.push(el("p", t(view ? "obs.noPart" : "obs.failed")));
    box.replaceChildren(...children);
    return;
  }
  const shown = (l) => landing.shown.includes(l) || landing.colour === l;
  const name = (hit) => displayName(hit.name);
  if (shown("temperature") || !OBSERVED_LAYERS.some(shown)) {
    const warm = s.warmest && line("temperature", t(landing.part === "night" ? "obs.warmestNight" : "obs.warmest", { okres: name(s.warmest), value: fmt(s.warmest.value) }));
    const cold = s.coldest && line("temperature", t("obs.coldest", { okres: name(s.coldest), value: fmt(s.coldest.value) }));
    children.push(...(landing.part === "night" ? [cold, warm] : [warm, cold]).filter(Boolean));
  }
  if (shown("precipitation") && s.wettest) {
    const rained = s.wettest.value >= 0.1;
    children.push(line("precipitation", rained
      ? t("obs.wettest", { okres: name(s.wettest), value: fmt1(s.wettest.value), station: fmt1(s.wettestStation?.value) })
      : t("obs.dry")));
    if (rained) children.push(line("precipitation", t("obs.wetOkresy", { n: s.wet, of: s.rainOkresy })));
  }
  if ((shown("wind") || shown("gust")) && s.gust) children.push(line("gust", t("obs.gust", { okres: name(s.gust), value: fmt(s.gust.value) })));
  if (shown("sunshine") && s.sunniest) children.push(line("sunshine", t("obs.sunniest", { okres: name(s.sunniest), value: fmt1(s.sunniest.value) })));
  children.push(el("p", t("obs.from", { n: s.stations }), "source"));
  box.replaceChildren(...children);
}

async function renderLanding() {
  const token = ++landingToken;
  renderWhen();
  renderShow();
  const { day, part, layer } = landing;
  const key = `${layer}|${day}`;
  if (!loaded.has(key)) {
    const [box, children] = headlineStart();
    box.replaceChildren(...children, el("p", t("obs.loading")));
  }
  const data = await dayData(layer, day);
  if (token !== landingToken || mode !== "measured") return;
  const view = { part, shown: landing.shown, colour: landing.colour, layer, okres: landing.okres, fill: null, err: null };
  const nextErr = await buildErrView(day);
  if (token !== landingToken || mode !== "measured") return;
  errView = nextErr;
  view.err = errView;
  if (layer === "stations") {
    const rows = stationRows(data, stationIndexDoc, part);
    renderErrNote(rows);
    measuredMap.set(rows, view);
    renderStationHeadline(rows, !data);
    okresPanel.render(null, landing);
  } else {
    const rows = okresRows(data, part);
    // the okres colours are of the measured values: with the model's error on, the dots (zoomed in) carry it
    view.fill = data && !errView ? okresColours(data, day, part, landing.colour) : null;
    // zoomed in, the map shows the stations themselves (their measured values at real places)
    const stationData = await dayData("stations", day);
    if (token !== landingToken || mode !== "measured") return;
    const stationList = stationRows(stationData, stationIndexDoc, part);
    renderErrNote(stationList);
    measuredMap.set(rows, view, stationList);
    renderOkresHeadline(data);
    okresPanel.render(data, landing);
  }
  $("measured-panel").classList.toggle("with-panel", Boolean(landing.okres));
  // as on the forecast map: Czechia moves beside the open okres panel
  measuredMap.fitBeside(landing.layer === "okresy" && landing.okres ? $("okres-panel") : null);
}

for (const button of document.querySelectorAll("#layer [data-layer]")) {
  button.addEventListener("click", () => updateLanding({ layer: button.dataset.layer, okres: null }));
}

function browseMeasured() {
  setMode("measured");
  document.title = `MeteoVerdict: ${t("measured.heading")}`;
  const start = startView();
  if (!start.day) {
    $("measured-panel").hidden = true;
    $("measured-intro").textContent = t("measured.noDays");
    return;
  }
  const past = observedIndex.days.map((d) => d.day).filter((d) => d < todayIso());
  landing = parseLanding(cleanHash(), past, start);
  if (isDaily(landing.day)) landing.part = "day";
  measuredMap.resize();
  renderLanding();
}

function browseKinds() {
  setMode("kinds");
  document.title = `MeteoVerdict: ${t("measured.mode.kinds")}`;
  const map = kindsMap();
  map.fitAll();
  openStationPanel(kindsStation(cleanHash()));
}

// --- one station ----------------------------------------------------------------------------
function backLink() {
  const query = parseDiaryQuery(window.location.search);
  const view = lastLanding ?? { ...startView(), ...(query.day && observedIndex.byDay.has(query.day) ? { day: query.day } : {}) };
  const link = $("back-link");
  link.href = view.day ? hashWith(landingHash(view)) : "#";
  link.textContent = view.day ? t("measured.back", { day: dayText(view.day) }) : t("measured.backPlain");
  $("back").hidden = false;
}

// --- the model selector (both views) ------------------------------------------------------------
const modelSelect = $("model");
const leadSelect = $("lead");

async function fillModelPick() {
  cleanHash(); // a choice in the address
  const options = await models.options();
  if (!options.some((o) => o.id === models.state.model)) models.state.model = DEFAULT_MODEL;
  modelSelect.replaceChildren(
    ...options.map((o) => {
      const option = el("option", o.name);
      option.value = o.id;
      option.selected = o.id === models.state.model;
      return option;
    }),
  );
  leadSelect.replaceChildren(
    ...LEADS.map((n) => {
      const option = el("option", t(`fc.lead.${n}`));
      option.value = String(n);
      option.selected = n === models.state.lead;
      return option;
    }),
  );
}

/** Keep the model choice in the address (nothing for the defaults). */
function syncModelHash() {
  const base = splitModelHash(window.location.hash).hash;
  const next = hashWith(base);
  if (next !== window.location.hash) window.history.replaceState(null, "", `${window.location.search}${next}`);
}

function modelChanged() {
  models.state.model = modelSelect.value;
  models.state.lead = Number(leadSelect.value);
  syncModelHash();
  if (mode === "measured") renderLanding();
  else if (mode === "kinds") {
    if (stationMap) applyKindsColour();
    if (stationPanelState?.id) openStationPanel(stationPanelState.id);
  }
}
modelSelect.addEventListener("change", modelChanged);
leadSelect.addEventListener("change", modelChanged);
$("model-pick").addEventListener("submit", (event) => event.preventDefault());

// only the latest navigation renders: a slow station file must not overwrite a newer one
let showToken = 0;
async function show() {
  const token = ++showToken;
  const hashNow = cleanHash();
  const next = pageMode(hashNow);
  if (next !== "station") syncModelHash();
  if (next === "measured") {
    browseMeasured();
    return;
  }
  if (next === "kinds") {
    browseKinds();
    return;
  }
  const hash = parseStationHash(hashNow);
  const id = hash.id;
  const was = mode;
  setMode("station");
  backLink();
  window.scrollTo({ top: 0 });
  const day = pendingDay;
  pendingDay = null;
  if (day) diary.setDay(day);
  if (doc?.station.id !== id) {
    if (!panel.hidden) kindsMap().select(id, { animate: was === "station" });
    $("search").value = index.find((s) => s.id === id)?.name ?? "";
    $("message").textContent = t("station.loading");
    const loadedDoc = await getJson(`${DATA}/${id}.json`);
    if (token !== showToken) return;
    doc = loadedDoc?.station ? { ...loadedDoc, elements: loadedDoc.elements ?? {} } : null;
    if (!doc) {
      $("title").textContent = id;
      document.title = "MeteoVerdict";
      $("facts").textContent = "";
      $("message").textContent = t("station.notFound", { id });
      $("charts").replaceChildren();
      $("elements").replaceChildren();
      $("elements-title").hidden = true;
      $("detail-title").hidden = true;
      $("pick").hidden = true;
      diary.hide();
      return;
    }
    const name = doc.station.name ?? id;
    $("title").textContent = name;
    document.title = `MeteoVerdict: ${name}`;
    $("facts").textContent = facts(doc.station);
    $("status").textContent = updated(doc.generated);
    $("detail-title").hidden = false;
    diary.show(doc);
    renderElements();
  } else if (day) {
    diary.show(doc);
  }
  const element = hash.element && doc.elements[hash.element] ? hash.element : defaultElement(doc);
  $("message").textContent = element ? "" : t("station.noData");
  fillElements(element);
  if (element) renderCharts(element);
}

$("element").addEventListener("change", (event) => {
  if (doc) window.location.hash = `${doc.station.id}/${event.target.value}`;
});
window.addEventListener("hashchange", show);
window.addEventListener("popstate", show);

Promise.all([getJson(`${DATA}/index.json`), getJson(`${OBSERVED}/index.json`)]).then(async ([loadedIndex, observedDoc]) => {
  stationIndexDoc = loadedIndex;
  observedIndex = parseObservedIndex(observedDoc);
  index = loadedIndex?.stations ?? [];
  if (loadedIndex?.generated) $("status").textContent = updated(loadedIndex.generated);
  // an index from before it carried coordinates: take them from the score map's table
  const table = index.some((s) => s.lat == null) ? await getJson("data/scores/stations.json") : null;
  placed = withCoordinates(index, table);
  if (table) stationIndexDoc = { ...loadedIndex, stations: placed };
  fillSearch();
  await fillModelPick();
  show();
});
