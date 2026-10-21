// The measured-weather page (measured.html, "Naměřeno / Measured"): the Weather tab, the map
// of what ČHMÚ's stations measured per okres, by day and part of day (measured.js,
// data/scores/observed/ from `mvd observed-map`); and the Stations tab, the map of the
// network, where a station opens a panel (with the model's forecast at it). Old links to a
// station's own page (#WSI) open the Stations tab on that station.
import "./style.css";

import { setUpLanguage } from "./i18n.js";
import { formatNumber, searchStations } from "./station.js";
import {
  KIND_COLORS, classifyStation, elevationGradient, ELEVATION_STOPS, filterStations, hasElements,
  kindCounts, measureCounts, withCoordinates,
} from "./station-map.js";
import { createStationMap } from "./station-map-view.js";
import { glyph } from "./icons.js";
import {
  KINDS_HASH, dayTabs, defaultDay, kindsStation, landingHash, okresRows, pageMode, parseLanding, stationHref,
} from "./measured.js";
import { createMeasuredMap } from "./measured-map-view.js";
import { BEYOND, colorFor, errorRampKey, renderScale } from "./palette.js";
import { createOkresPanel } from "./measured-okres.js";
import { OBSERVED_LAYERS, nearestDay, observedSummary, parseObservedDay, parseObservedIndex } from "./observed.js";
import {
  DEFAULT_SHOWN, dayLabel, displayName, labelFor, okresColours, rampKey, today, valueFor,
} from "./tv.js";
import { keepRoomForPanels } from "./panel-room.js";
import {
  DEFAULT_ERR, DEFAULT_MODEL, DEFAULT_WX, ERROR_VARS, LEADS, AI, WX_MODES, createModelCompare, errorKeyFor, errorLookup, modelOptions,
  okresErrors, splitModelHash, withModelHash,
} from "./station-model.js";

const t = setUpLanguage();
const language = document.documentElement.lang;
const DATA = "data/scores/station"; // only index.json: the stations' names and places
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

const DATE_TIME = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Prague",
});
const updated = (generated) => {
  const time = generated ? new Date(generated) : null;
  return time && !Number.isNaN(time.getTime()) ? t("station.updated", { time: DATE_TIME.format(time) }) : "";
};

const models = createModelCompare({ getJson, t, language });

/** The hash of the page without the model choice (";m=…;l=…", station-model.js); a choice in it
 * becomes the page's. */
function cleanHash() {
  const { hash, model, lead, err, wx } = splitModelHash(window.location.hash);
  if (model) {
    models.state.model = model;
    models.state.lead = lead;
    models.state.err = err === undefined ? DEFAULT_ERR : err;
    models.state.wx = wx ?? DEFAULT_WX;
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
    if (hit) window.location.hash = hashWith(`${KINDS_HASH}/${encodeURIComponent(hit.id)}`);
  };
  input.addEventListener("change", go);
  $("controls").addEventListener("submit", (event) => {
    event.preventDefault();
    go();
  });
}

// --- one station's facts (the Stations tab's panel) -------------------------------------
function facts(station) {
  const parts = [station.id];
  if (station.elevation != null) parts.push(t("station.elevation", { m: formatNumber(Math.round(station.elevation)) }));
  if (station.lat != null) parts.push(`${station.lat.toFixed(4)}° N, ${station.lon.toFixed(4)}° E`);
  if (station.okres) parts.push(`${t("control.okres")} ${displayName(station.okres)}`);
  if (station.active != null) parts.push(t(station.active ? "station.active" : "station.closed"));
  return parts.join(" · ");
}

// --- the page's three views ---------------------------------------------------------------
let mode = null; // "measured" or "kinds"
let placed = []; // stations of the index with coordinates
let stationIndexDoc = null; // data/scores/station/index.json
const top = $("station-top");
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
    onPick: (station) => openStationPanel(station.id),
  });
  fillMapTools();
  return stationMap;
}

// the Stations view's panel: the Weather view's panel (#okres-panel's look), the map stays put
const stationPanel = $("station-panel");
keepRoomForPanels($("station-map-wrap"), $("station-map"), [stationPanel]);

/** The station's own block at the top of its panel: kind and facts. */
function stationInfo(station) {
  const box = el("div", null, "station-info");
  box.append(el("strong", `${t("map.stationLabel")}: ${station.name ?? station.id}`), el("p", describe(station), "when"), el("p", facts(station), "model-note"));
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
  const data = okres && day ? await dayData(day) : null;
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
  return t("map.err.note", { model: v.name, lead: models.state.lead, value, unit: v.unit, day: v.day, n: formatNumber(have), of: formatNumber(placed.length) });
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
  applyFilter();
}

function applyFilter() {
  const measure = $("map-measure").value;
  let shown = filterStations(placed, measure);
  // coloured by error: only the stations the model can be compared at (with a value that day)
  const compared = kindsErr?.hasModel && !kindsErr.noFile;
  if (compared) shown = shown.filter((s) => kindsErr.byId.get(s.id) != null);
  stationMap.setStations(placed, shown);
  $("map-count").textContent =
    measure || compared ? t("map.count", { shown: formatNumber(shown.length), all: formatNumber(placed.length) }) : "";
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
  // coloured by error: the map waits for the error file instead of drawing every station first
  // (they would blink away when the filter applies)
  applyKindsColour();
  if (!models.state.err) applyFilter();
}

/** Show the parts of the page of a view: the measured map or the kinds map. */
function setMode(next) {
  mode = next;
  $("measured-panel").hidden = next !== "measured";
  $("measured-intro").textContent = t(next === "kinds" ? "measured.introKinds" : "measured.intro");
  for (const button of document.querySelectorAll("#mode [data-mode]")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === next));
  }
  top.hidden = next === "measured";
  $("map-hint").hidden = true; // the intro says it
  if (next !== "kinds") stationPanel.replaceChildren();
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
let landing = null; // {day, part, colour, shown, okres}
let landingToken = 0;
const loaded = new Map(); // day → the loaded value (null: failed)
const loading = new Map(); // day → its promise
let okresyList = null; // promise of the okresy (outlook.json: code, name, point)

const todayIso = () => today(Date.now());
const fmt = (v, digits = 0) => (v == null ? "–" : v.toFixed(digits));
const fmt1 = (v) => (v == null ? "–" : v.toLocaleString(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }));

const loadOkresy = () => (okresyList ??= getJson("data/scores/outlook.json").then((d) => d?.okresy ?? []));

/** The parsed okres view of a day, loaded once. */
function dayData(day) {
  const key = day;
  if (!loading.has(key)) {
    const promise = Promise.all([getJson(`${OBSERVED}/${day}.json`), loadOkresy()]).then(([d, okresy]) => parseObservedDay(d, okresy));
    loading.set(key, promise.then((value) => {
      loaded.set(key, value ?? null);
      return value ?? null;
    }));
  }
  return loading.get(key);
}

/** The view a plain link opens: the newest measured day, the whole day. */
function startView() {
  const day = defaultDay(observedIndex, todayIso());
  return { day, part: "day", colour: "temperature", shown: DEFAULT_SHOWN, okres: null };
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
  stationHref: (id) => stationHref(id, hashWith),
  openStation: (id, event) => openStationFromOkres(id, event),
  stationIndex: async () => stationIndexDoc,
  // the selected model at the okres's own stations (not at the okres point)
  modelSection: (view, state) => {
    const row = view.rows.get(`${state.okres}|${state.day}|day`);
    const where = new Map(placed.map((s) => [s.id, s]));
    const ids = [...(row?.stations ?? []), ...(row?.high ?? []).map((h) => h.id)];
    const stations = [...new Set(ids)].map((id) => where.get(id)).filter(Boolean);
    const section = models.okresSection(stations, state.day, (id, event) => openStationFromOkres(id, event));
    const mine = wxView && wxErrorBlock(state.okres);
    if (!mine) return section;
    const box = el("div");
    box.append(mine, ...(section ? [section] : []));
    return box;
  },
});

/** The model's error in the okres (Weather map's error colours): its mean, size and number of stations. */
function wxErrorBlock(code) {
  const w = wxView;
  const e = w.by.get(code);
  const box = el("div", null, "model-note wx-error");
  const what = t(`fc.var.${w.key}`).toLowerCase();
  box.append(el("strong", t("measured.wx.panelTitle", { model: w.view.name, lead: models.state.lead, what })));
  box.append(el("p", e
    ? t("measured.wx.panelLine", { bias: signedText(e.bias, w.view), mae: w.view.label(e.mae).replace(/^[+−]?/, ""), n: e.n })
    : t(w.view.noFile ? "measured.wx.noFile" : "measured.wx.panelNone")));
  return box;
}

/** One line of an okres's values, for its tooltip and its label's name. */
function describeRow(row, part) {
  const parts = [];
  if (row.symbol) parts.push(t(`diary.symbol.${row.symbol}`));
  if (row.tmax != null || row.tmin != null) {
    parts.push(part === "night" ? `min ${fmt(row.tmin)} °C` : `max ${fmt(row.tmax)} °C, min ${fmt(row.tmin)} °C`);
  }
  for (const layer of ["precipitation", "wind", "gust", "sunshine", "cloud"]) {
    if (valueFor(row, layer, part) != null) parts.push(`${t(`layer.${layer}`).toLowerCase()} ${labelFor(row, layer, part)}`);
  }
  return parts.join(" · ");
}

// --- the Stations map's dots coloured by a model's error (models.state.err) --------------------------------

/** "Model error: +1.2 °C" for a station in the tooltip, or why it has none. */
function errorText(row, v) {
  const e = v.byId.get(row.id);
  if (e != null) return t("measured.err.tip", { model: v.name, lead: models.state.lead, value: v.label(e) });
  if (v.noFile || !v.hasModel) return t("measured.err.tipNone");
  return t(v.byId.has(row.id) ? "measured.err.tipGap" : "measured.err.tipOutside");
}

/** The error view for a day, from the per-day error file: null when the colour is the measured values. */
async function buildErrView(day, forKey = models.state.err, abs = false) {
  const key = forKey;
  if (!key) return null;
  const [doc, index] = await Promise.all([models.loadErrors(day), models.loadIndex()]);
  const { model, lead } = models.state;
  const lookup = errorLookup(doc, model, lead, key);
  const name = modelOptions(index, t).find((o) => o.id === model)?.name ?? model;
  const variable = key === "r" ? "mm" : key === "wind" ? "m/s" : "°C";
  const label = (e) => `${e > 0 ? "+" : e < 0 ? "−" : ""}${fmt1(Math.abs(e))} ${variable}`;
  return { key, ramp: errorRampKey(key, abs), unit: variable, name, noFile: !doc, day, label, ...lookup };
}

const measuredMap = createMeasuredMap({
  container: $("measured-map"),
  t,
  describe: describeRow,
  onPick: (row) => openOkres(row.okresCode),
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
  stationHref: (id) => stationHref(id, hashWith),
  openStation: (id, event) => openStationFromOkres(id, event),
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
}

function renderShow() {
  $("values-legend").textContent = t("measured.valuesOkresy");
  $("colours-legend").textContent = t("tv.colour");
  $("measured-hint").textContent = t("measured.hintOkresy");
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
  $("colours").replaceChildren(
    ...OBSERVED_LAYERS.map((colour) => {
      const label = el("label", null, "check");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "colour";
      radio.checked = colour === landing.colour;
      radio.addEventListener("change", () => updateLanding({ colour }));
      label.append(radio, el("span", t(`layer.${colour}`)));
      return label;
    }),
  );
  renderWxModes();
  // the forecast map's scales and legend (palette.js); rain in mm; with the error colours the
  // scale is drawn by renderLanding once the errors are loaded
  if (wxKey()) return;
  const key = rampKey(landing.colour, true);
  renderScale($("scale"), key, t(`obs.scale.${key}`));
}

// --- the okresy coloured by the model's error (the default) or by the measured values -----------------
/** The error value coloured now (tmax, tmin, r, wind), or null: the measured values are shown. */
const wxKey = () => (models.state.wx === "none" ? null : errorKeyFor(landing.colour, landing.part));
let wxView = null; // {view (buildErrView), by (okres code → {n, bias, mae}), abs} of the drawn map, or null

function renderWxModes() {
  $("wx-legend").textContent = t("measured.wx.legend");
  $("wx-modes").replaceChildren(
    ...["none", "bias", "abs"].map((mode) => {
      const label = el("label", null, "check");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "wx";
      radio.checked = mode === models.state.wx;
      radio.addEventListener("change", () => {
        models.state.wx = mode;
        syncModelHash();
        renderLanding();
      });
      label.append(radio, el("span", t(`measured.wx.${mode}`)));
      return label;
    }),
  );
}

/** The errors per okres for the drawn day (null: measured values), with the okres code of a station by its name. */
async function buildWxView(day) {
  const key = wxKey();
  if (!key) return null;
  const abs = models.state.wx === "abs";
  const [view, okresy] = await Promise.all([buildErrView(day, key, abs), loadOkresy()]);
  const codes = new Map(okresy.map((o) => [displayName(o.name), o.code]));
  const by = view.hasModel && !view.noFile ? okresErrors(view.byId, placed, (name) => codes.get(displayName(name ?? "")) ?? null) : new Map();
  return { view, by, abs, key, okresy };
}

const signedText = (v, view) => view.label(Math.abs(v) < 0.05 ? 0 : v);

/** The fill (okres → colour) and tooltips of the error view; grey without a value. */
function wxFill(w) {
  const fill = new Map();
  const tips = new Map();
  for (const o of w.okresy) {
    const e = w.by.get(o.code);
    const title = displayName(o.name);
    if (!e) {
      fill.set(o.code, BEYOND);
      tips.set(o.code, { title, text: t(w.view.noFile ? "measured.wx.noFile" : w.view.hasModel ? "measured.wx.tipNone" : "measured.wx.noModel") });
      continue;
    }
    fill.set(o.code, colorFor(w.abs ? e.mae : e.bias, w.view.ramp));
    tips.set(o.code, { title, text: t("measured.wx.tip", { bias: signedText(e.bias, w.view), mae: w.view.label(e.mae).replace(/^[+−]?/, ""), n: e.n }) });
  }
  return { fill, tips };
}

/** The legend under the map and its note for the shown colours. */
function renderWxLegend(w) {
  const box = $("scale");
  if (!w) {
    const key = rampKey(landing.colour, true);
    renderScale(box, key, t(`obs.scale.${key}`));
    if (models.state.wx !== "none") box.append(el("p", t("measured.wx.noVar"), "muted small"));
    return;
  }
  const title = t(w.abs ? "measured.wx.scaleAbs" : "measured.wx.scaleBias", { model: w.view.name, lead: models.state.lead, unit: w.view.unit });
  renderScale(box, w.view.ramp, title);
  const notes = [];
  if (w.view.noFile) notes.push(t("measured.wx.noFile"));
  else if (!w.view.hasModel) notes.push(models.state.model === AI ? t("fc.noAi") : t("measured.wx.noModel"));
  if (landing.part !== "day") notes.push(t("measured.wx.wholeDay"));
  for (const n of notes) box.append(el("p", n, "muted small"));
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
  const { day, part } = landing;
  if (!loaded.has(day)) {
    const [box, children] = headlineStart();
    box.replaceChildren(...children, el("p", t("obs.loading")));
  }
  const data = await dayData(day);
  if (token !== landingToken || mode !== "measured") return;
  const w = data ? await buildWxView(day) : null;
  if (token !== landingToken || mode !== "measured") return;
  wxView = w;
  const wxMap = w ? wxFill(w) : null;
  const view = {
    part, shown: landing.shown, colour: landing.colour, okres: landing.okres,
    fill: wxMap?.fill ?? (data ? okresColours(data, day, part, landing.colour) : null),
    tips: wxMap?.tips ?? null,
  };
  renderWxLegend(w);
  measuredMap.set(okresRows(data, part), view);
  renderOkresHeadline(data);
  okresPanel.render(data, landing);
  $("measured-panel").classList.toggle("with-panel", Boolean(landing.okres));
  // as on the forecast map: Czechia moves beside the open okres panel
  measuredMap.fitBeside(landing.okres ? $("okres-panel") : null);
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

function show() {
  const hashNow = cleanHash();
  const next = pageMode(hashNow);
  if (next === "station") {
    // an old link to a station's own page (#WSI, #WSI/element): the Stations tab on that station
    const id = decodeURIComponent(hashNow.replace(/^#/, "").split("/")[0]);
    window.history.replaceState(null, "", `${window.location.pathname}${hashWith(`${KINDS_HASH}/${encodeURIComponent(id)}`)}`);
    browseKinds();
    return;
  }
  syncModelHash();
  if (next === "measured") browseMeasured();
  else browseKinds();
}

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
