import * as Plot from "@observablehq/plot";
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre's ES module build loads its worker from a separate file
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import {
  NO_DATA, P_BEST_MIN, TOO_FEW, bestByRegion, fillExpression, modelColors, records,
  regionColor, smallSampleCodes, stationFeatures, stationsIn, withKrajFallback,
} from "./data.js";
import { HOURS, explainRegion, reasons } from "./explain.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";
import { displayName } from "./tv.js";
import { availableLeadDays, availableVariables, availableWindows, filesWindow, parseHash, pickWindow, windowLabel } from "./view.js";
import { keepRoomForPanels, panelRoom, userMoved } from "./panel-room.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();

// Czechia, with a little margin
const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
const UNITS = { temperature: "°C", wind: "m/s", precipitation: "mm" };
const unitOf = (variable) => UNITS[variable.split("_")[0]] ?? "";
const isTemperature = (variable) => variable.startsWith("temperature_2m");

// No third-party tiles: the map is the region boundaries on a plain background.
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
// the map grows with a long okres panel (it shares a grid cell with it): keep it drawn
new ResizeObserver(() => map.resize()).observe(map.getContainer());
keepRoomForPanels(map.getContainer().parentElement, map.getContainer(), [document.getElementById("detail")]);
map.addControl(new NavigationControl({ showCompass: false }));

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const cache = new Map();
function scores(view, level, variable = view.variable) {
  const path = `data/scores/${filesWindow(view.window, current.meta)}/${level}/${variable}.json`;
  if (!cache.has(path)) {
    // a failed fetch is not remembered: the next view tries again
    cache.set(path, getJson(path).then((doc) => {
      if (!doc) cache.delete(path);
      return records(doc);
    }));
  }
  return cache.get(path);
}

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

function swatch(color) {
  const s = element("span", "", "swatch");
  s.style.background = color;
  return s;
}

/** Fill a <select> with [value, label] pairs and select `current`. */
function fillSelect(id, options, current) {
  const select = document.getElementById(id);
  select.replaceChildren(
    ...options.map(([value, label]) => {
      const option = element("option", label);
      option.value = value;
      option.selected = String(value) === String(current);
      return option;
    }),
  );
  return select;
}

// --- state: the view (variable, lead day, window) and the chosen region, in the URL ----
const current = {
  view: null, level: "okres", rows: [], regions: new Map(), stations: new Map(),
  names: {}, colors: {}, stationTable: null, highlight: null, pBestMin: P_BEST_MIN,
};

function readView() {
  const view = parseHash(window.location.hash);
  view.region = window.location.hash.replace(/^#/, "").split("/")[3] || null;
  return view;
}

function writeView() {
  const v = current.view;
  const parts = [v.variable, v.leadDay, v.window, v.region].filter((p) => p != null && p !== "");
  window.history.replaceState(null, "", `#${parts.join("/")}`);
}

const nameOf = (model) => current.names[model] ?? model;
const percent = (p) => Math.round(p * 100);

// --- legend: models with the number of regions they win; click to highlight ---------
function renderLegend() {
  const wins = new Map();
  for (const entry of current.regions.values()) {
    if (entry.model && entry.enough) wins.set(entry.model, (wins.get(entry.model) ?? 0) + 1);
  }
  const box = document.getElementById("legend");
  const title = element("div", t("legend.title"), "legend-title");
  const items = [...wins]
    .sort((a, b) => b[1] - a[1])
    .map(([model, n]) => {
      const button = element("button", null, "legend-item");
      button.type = "button";
      button.setAttribute("aria-pressed", String(current.highlight === model));
      button.append(swatch(current.colors[model] ?? "#888888"), element("span", nameOf(model)), element("span", String(n), "count"));
      button.addEventListener("click", () => {
        current.highlight = current.highlight === model ? null : model;
        paintHighlight();
        renderLegend();
      });
      return button;
    });
  const rest = [[t("legend.tooFew"), TOO_FEW], [t("legend.noData"), NO_DATA]].map(([label, color]) => {
    const row = element("div", null, "legend-item static");
    row.append(swatch(color), element("span", label));
    return row;
  });
  const small = element("div", null, "legend-item static");
  small.append(element("span", "", "swatch small-sample"), element("span", t("legend.small")));
  rest.push(small);
  const hint = element("div", t("legend.hint"), "legend-hint");
  box.replaceChildren(title, ...items, ...rest, hint);
}

/** Dim the regions and stations the highlighted model does not win. */
function paintHighlight() {
  const model = current.highlight;
  if (!model) {
    map.setPaintProperty("regions-fill", "fill-opacity", 0.78);
    map.setPaintProperty("stations", "circle-opacity", 1);
    map.setPaintProperty("stations", "circle-stroke-opacity", 1);
    return;
  }
  const codes = [...current.regions].filter(([, e]) => e.model === model && e.enough).map(([c]) => c);
  map.setPaintProperty("regions-fill", "fill-opacity", codes.length ? ["match", ["get", "code"], codes, 0.9, 0.12] : 0.12);
  const stations = [...current.stations].filter(([, e]) => e.model === model).map(([c]) => c);
  const dim = stations.length ? ["match", ["get", "code"], stations, 1, 0.15] : 0.15;
  map.setPaintProperty("stations", "circle-opacity", dim);
  map.setPaintProperty("stations", "circle-stroke-opacity", dim);
}

/** "A, B" (at most three) of the models statistically as good as the region's best. */
function closeList(entry) {
  const names = entry.tied.slice(0, 3).map(nameOf).join(", ");
  return names || "–";
}

// --- hover: a light tooltip instead of a click ----------------------------------------
function showHover(event, entry, name) {
  const box = document.getElementById("hover");
  const title = element("strong", displayName(name));
  const line = element("div");
  if (!entry || entry.model == null) line.textContent = t("describe.noData");
  else if (!entry.enough) line.textContent = t("describe.tooFew");
  else {
    if (entry.fallback) line.append(element("div", t("hover.fallback", { kraj: displayName(entry.krajName ?? "") }), "muted"));
    line.append(swatch(current.colors[entry.model] ?? "#888888"), `${nameOf(entry.model)} · MAE ${entry.mae.toFixed(2)} ${unitOf(current.view.variable)}`);
    if (!entry.clear) line.append(element("div", t("hover.close", { others: closeList(entry) }), "muted"));
    if (entry.pBest != null) line.append(element("div", t("hover.pBest", { pct: percent(entry.pBest) }), "muted"));
    if (entry.tied.length && entry.clear) line.append(element("div", t("hover.tied", { n: entry.tied.length }), "muted"));
    if (entry.small) line.append(element("div", t("legend.small"), "muted"));
  }
  box.replaceChildren(title, line, element("div", t("hover.click"), "muted"));
  box.hidden = false;
  const { x, y } = event.point;
  box.style.left = `${x + 14}px`;
  box.style.top = `${y + 14}px`;
}

// --- the detail panel: why a model is best in the region -------------------------------
const panel = () => document.getElementById("detail");

function closeButton(onClose) {
  const b = element("button", "×", "close");
  b.type = "button";
  b.setAttribute("aria-label", t("chart.close"));
  b.addEventListener("click", onClose);
  return b;
}

function intervalChart(facts) {
  const best = facts.table.find((r) => r.rank === 1);
  const data = facts.table
    .filter((r) => r.mae != null && !r.short)
    .map((r) => ({
      label: r.model === "blend" ? t("model.blend") : nameOf(r.model),
      model: r.model,
      mae: r.mae,
      low: r.rank === 1 || !r.ci ? null : best.mae + r.ci[0],
      high: r.rank === 1 || !r.ci ? null : best.mae + r.ci[1],
      tied: r.tied || r.rank === 1,
    }));
  // as wide as the panel's content, and a left margin that fits the longest model name
  const wrapWidth = document.getElementById("map").parentElement.clientWidth;
  const rem = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const panelWidth = window.innerWidth <= 700 ? wrapWidth : window.innerWidth <= 900 ? 21 * rem : wrapWidth * 0.5;
  const chartWidth = Math.max(280, Math.round(panelWidth - 2 * 0.9 * rem - 6));
  const longest = Math.max(...data.map((d) => d.label.length));
  const nameMargin = Math.min(Math.round(chartWidth * 0.6), Math.round(longest * 5.6 + 14));
  return Plot.plot({
    width: chartWidth,
    height: 28 + 19 * data.length,
    marginLeft: nameMargin,
    marginRight: 10,
    style: { fontSize: "10px" },
    x: { label: `MAE (${unitOf(current.view.variable)}) →`, grid: true, zero: true },
    y: { label: null, domain: data.map((d) => d.label) },
    marks: [
      Plot.ruleX([best.mae], { stroke: "#1d2329", strokeDasharray: "3,3" }),
      Plot.ruleY(data.filter((d) => d.low != null), {
        y: "label", x1: "low", x2: "high", stroke: (d) => (d.tied ? "#9aa7b1" : "#e0a19a"), strokeWidth: 3,
      }),
      Plot.dot(data, {
        y: "label", x: "mae", r: 4.5,
        fill: (d) => (d.model === "blend" ? "#ffffff" : (current.colors[d.model] ?? "#888888")),
        stroke: (d) => (d.model === best.model ? "#1d2329" : "#ffffff"),
        strokeWidth: (d) => (d.model === best.model ? 2 : 1),
        tip: true,
      }),
    ],
  });
}

function chips(items, label) {
  const box = element("div", null, "chips");
  for (const { title, model } of items) {
    const chip = element("span", null, "chip");
    chip.append(element("b", title), swatch(current.colors[model] ?? "#888888"), element("span", nameOf(model)));
    chip.title = nameOf(model);
    box.append(chip);
  }
  const wrap = element("div", null, "detail-block");
  wrap.append(element("h3", label), box);
  return wrap;
}

/** Under the okres name: links to all its stations in the Stations tab of measured.html. */
function stationPages(region) {
  const all = stationsIn(current.stationTable, region);
  if (all.length === 0) return null;
  const line = element("p", null, "station-pages");
  line.append(element("span", `${t(all.length === 1 ? "detail.stationPage" : "detail.stationPages")}: `, "muted"));
  all.forEach((s, i) => {
    if (i > 0) line.append(" · ");
    const a = element("a", s.name);
    a.href = `measured.html#kinds/${encodeURIComponent(s.id)}`;
    line.append(a);
    if (s.high) line.append(element("span", ` (${t("detail.highSite")})`, "muted"));
  });
  return line;
}

function stationList(region) {
  const table = records(current.stationTable);
  const own = table.filter((s) => s.okres_code === region || s.kraj_code === region);
  const scored = own.filter((s) => current.stations.has(s.id));
  if (scored.length === 0) return null;
  const wrap = element("div", null, "detail-block");
  wrap.append(element("h3", t("detail.stations", { n: scored.length })));
  const list = element("div", null, "station-list");
  for (const s of scored.sort((a, b) => a.name.localeCompare(b.name, "cs"))) {
    const entry = current.stations.get(s.id);
    const b = element("button", null, "station");
    b.type = "button";
    b.append(swatch(regionColor(entry, current.colors)), element("span", s.name));
    b.addEventListener("click", () => showStation(s.id, s.name, region));
    list.append(b);
  }
  wrap.append(list);
  return wrap;
}

async function showRegion(region) {
  const view = current.view;
  const box = panel();
  if (!region) {
    box.replaceChildren();
    return;
  }
  box.scrollTop = 0;
  const hourRows = isTemperature(view.variable)
    ? Object.fromEntries(
        await Promise.all(HOURS.map(async (h) => [h, await scores(view, current.level, `temperature_2m_${h}utc`)])),
      )
    : null;
  const facts = explainRegion(current.rows, region, view.leadDay, hourRows);
  const entry = current.regions.get(region);
  const name = displayName(facts?.name ?? entry?.name ?? region);
  const close = closeButton(() => select(null));
  const heading = element("h2", name);
  const sub = element("p", `${t(`variable.${view.variable}`)} · D+${view.leadDay} · ${t(`window.${view.window}`).toLowerCase()}`, "muted");
  const pages = stationPages(region);
  const top = pages ? [close, heading, pages, sub] : [close, heading, sub];
  if (!facts) {
    box.replaceChildren(...top, element("p", t(entry && !entry.enough ? "describe.tooFew" : "detail.noRanking")));
    return;
  }
  const unit = unitOf(view.variable);
  const fmt = (v) => `${v.toFixed(2)} ${unit}`;
  const verdict = element("div", null, "verdict");
  verdict.append(
    swatch(current.colors[facts.winner.model] ?? "#888888"),
    element("strong", nameOf(facts.winner.model)),
    element("span", t("detail.mae", { mae: fmt(facts.winner.mae) }), "muted"),
  );
  const why = element("ul", null, "why");
  for (const { key, params } of reasons(facts, fmt)) why.append(element("li", t(key, params)));
  const blocks = [...top, verdict];
  const pBest = entry?.pBest;
  if (entry?.fallback) blocks.push(element("p", t("detail.fallback", { kraj: displayName(entry.krajName ?? "") }), "muted"));
  if (pBest != null) {
    const key = entry.clear ? "detail.pBest" : "detail.close";
    blocks.push(element("p", t(key, { pct: percent(pBest), min: percent(current.pBestMin), others: closeList(entry) }), "muted"));
  }
  if (facts.preliminary) blocks.push(element("p", t("detail.preliminary", { days: facts.basis.days }), "warning"));
  blocks.push(element("h3", t("detail.why")), why);
  const chartBlock = element("div", null, "detail-block");
  chartBlock.append(element("h3", t("detail.chart")), intervalChart(facts), element("p", t("detail.chartNote"), "muted small"));
  blocks.push(chartBlock);
  if (facts.byLead.length > 1) {
    blocks.push(chips(facts.byLead.map((l) => ({ title: `D+${l.lead}`, model: l.model })), t("detail.byLead")));
  }
  if (facts.byHour.length) {
    blocks.push(chips(facts.byHour.map((h) => ({ title: t(`hour.${h.hour}`), model: h.model })), t("detail.byHour")));
  }
  blocks.push(
    element(
      "p",
      t("detail.basis", { stations: facts.basis.stations, days: facts.basis.days }) +
        (facts.basis.borrowed ? ` ${t("compare.borrowed", { n: facts.basis.borrowed })}` : ""),
      "muted small",
    ),
  );
  const stations = stationList(region);
  if (stations) blocks.push(stations);
  const links = element("p", null, "links");
  const compare = element("a", t("detail.compare"));
  compare.href = `compare-models.html#${view.variable}/${view.leadDay}/${view.window}/${region}`;
  links.append(compare);
  if (current.level === "okres") {
    const forecast = element("a", t("detail.forecast"));
    forecast.href = `forecast.html#${region}/`;
    links.append(forecast);
  }
  blocks.push(links);
  box.replaceChildren(...blocks);
}

async function showStation(code, title, backTo) {
  const box = panel();
  const back = element("button", `← ${t("detail.back")}`, "back");
  back.type = "button";
  back.addEventListener("click", () => showRegion(backTo));
  const close = closeButton(() => select(null));
  // Observable Plot is loaded only when a chart is opened
  const [{ stationChart }, doc] = await Promise.all([import("./chart.js"), getJson(`data/scores/series/${code}.json`)]);
  const children = [close];
  if (backTo) children.push(back);
  children.push(element("h2", title), stationChart(doc, current.view, current.colors, current.names, t));
  // the station on the Stations tab of measured.html
  const all = element("a", t("station.link"));
  all.href = `measured.html#kinds/${encodeURIComponent(code)}`;
  const links = element("p", null, "links");
  links.append(all);
  children.push(links);
  box.replaceChildren(...children);
  fitView();
}

let padding = null;
const movedByUser = userMoved(map);

/** Fit Czechia beside the detail panel on wide screens, and back when it closes; never
 * once someone has moved the map themselves. */
function fitView() {
  const open = Boolean(panel().childElementCount) && window.innerWidth > 900;
  const right = open ? panelRoom(21, 0.5, map.getContainer().parentElement.clientWidth) : 20;
  if (padding && padding.right === right) return;
  if (padding && movedByUser()) return;
  const first = padding === null;
  padding = { top: 20, bottom: 20, left: 20, right };
  map.fitBounds(BOUNDS, { padding, duration: first ? 0 : 400 });
}

function select(region) {
  current.view.region = region;
  map.setFilter("selected", ["==", ["get", "code"], region ?? ""]);
  document.getElementById("find").value = region ?? "";
  writeView();
  showRegion(region).then(fitView);
}

// --- map layers -------------------------------------------------------------------
function addLayers(filled) {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addSource("stations", { type: "geojson", data: stationFeatures(null, new Map(), current.colors) });
  map.addLayer({ id: "regions-fill", type: "fill", source: filled, paint: { "fill-color": NO_DATA, "fill-opacity": 0.78 } });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.2 } });
  // rankings on fewer than 30 days (small_sample): a dashed outline
  map.addLayer({
    id: "small-sample", type: "line", source: filled, filter: ["in", ["get", "code"], ["literal", []]],
    paint: { "line-color": "#1d2329", "line-width": 1.2, "line-dasharray": [2, 2] },
  });
  map.addLayer({
    id: "selected", type: "line", source: filled, filter: ["==", ["get", "code"], ""],
    paint: { "line-color": "#1d2329", "line-width": 3 },
  });
  map.addLayer({
    id: "hovered", type: "line", source: filled, filter: ["==", ["get", "code"], ""],
    paint: { "line-color": "#1d2329", "line-width": 1.5, "line-opacity": 0.6 },
  });
  map.addLayer({
    id: "stations", type: "circle", source: "stations",
    paint: { "circle-radius": 3.5, "circle-color": ["get", "color"], "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 },
  });

  map.on("mousemove", "regions-fill", (event) => {
    const code = event.features[0].properties.code;
    map.setFilter("hovered", ["==", ["get", "code"], code]);
    map.getCanvas().style.cursor = "pointer";
    showHover(event, current.regions.get(code), event.features[0].properties.name);
  });
  map.on("mouseleave", "regions-fill", () => {
    map.setFilter("hovered", ["==", ["get", "code"], ""]);
    map.getCanvas().style.cursor = "";
    document.getElementById("hover").hidden = true;
  });
  map.on("click", (event) => {
    const station = map.queryRenderedFeatures(event.point, { layers: ["stations"] })[0];
    if (station) {
      showStation(station.properties.code, station.properties.name, current.view.region);
      return;
    }
    const region = map.queryRenderedFeatures(event.point, { layers: ["regions-fill"] })[0];
    const code = region?.properties.code ?? null;
    select(code === current.view.region ? null : code);
  });
  map.on("mouseenter", "stations", () => (map.getCanvas().style.cursor = "pointer"));
}

// --- loading ------------------------------------------------------------------------
map.on("load", async () => {
  const meta = await getJson("data/scores/meta.json");
  current.meta = meta;
  document.getElementById("status").textContent = statusText(meta, t);
  current.names = { ...meta?.models, blend: t("model.blend") };
  current.pBestMin = meta?.p_best_min ?? P_BEST_MIN;
  current.colors = modelColors(current.names);
  current.stationTable = await getJson("data/scores/stations.json");

  const view = readView();
  // only periods with scored days: an empty one is never offered nor kept from a link
  const windows = availableWindows(meta?.windows);
  view.window = pickWindow(view.window, windows);
  current.view = view;
  // okres choropleth where the okres level is published, kraj otherwise
  current.level = (await scores(view, "okres")).length ? "okres" : "kraj";
  addLayers(current.level === "okres" ? "okresy" : "kraje");

  // only the latest render applies: quick changes of the selects must not mix their data
  let renderToken = 0;
  async function render() {
    const token = ++renderToken;
    const rows = await scores(view, current.level);
    if (token !== renderToken) return;
    current.rows = rows;
    const leadDays = availableLeadDays(current.rows);
    if (!leadDays.includes(view.leadDay)) view.leadDay = leadDays[0];
    fillSelect("lead", leadDays.map((d) => [d, `D+${d}`]), view.leadDay);
    current.regions = bestByRegion(current.rows, view.leadDay, current.pBestMin);
    if (current.level === "okres") {
      const krajRows = await scores(view, "kraj");
      if (token !== renderToken) return;
      current.regions = withKrajFallback(current.regions, bestByRegion(krajRows, view.leadDay, current.pBestMin));
    }
    const stationRows = await scores(view, "station");
    if (token !== renderToken) return;
    current.stations = bestByRegion(stationRows, view.leadDay, current.pBestMin);
    map.setPaintProperty("regions-fill", "fill-color", fillExpression(current.regions, current.colors));
    map.setFilter("small-sample", ["in", ["get", "code"], ["literal", smallSampleCodes(current.regions)]]);
    map.getSource("stations").setData(stationFeatures(current.stationTable, current.stations, current.colors));
    if (current.highlight && ![...current.regions.values()].some((e) => e.model === current.highlight)) current.highlight = null;
    renderLegend();
    paintHighlight();
    select(view.region && current.regions.has(view.region) ? view.region : null);
  }

  fillSelect("variable", availableVariables(meta).map((v) => [v, t(`variable.${v}`)]), view.variable);
  // each period with its real dates and days, so a short history explains itself
  const language = document.documentElement.lang;
  fillSelect("window", windows.map((w) => [w, windowLabel(w, meta?.windows, t, language)]), view.window);
  for (const [id, key, parse] of [
    ["variable", "variable", String],
    ["lead", "leadDay", Number],
    ["window", "window", String],
  ]) {
    document.getElementById(id).addEventListener("change", (event) => {
      view[key] = parse(event.target.value);
      render();
    });
  }
  await render();
  // the okres finder: every region of the map, by name
  const found = [...current.regions].map(([code, e]) => [code, displayName(e.name)]).sort((a, b) => a[1].localeCompare(b[1], "cs"));
  fillSelect("find", [["", t("find.placeholder")], ...found], view.region ?? "");
  document.getElementById("find").addEventListener("change", (event) => select(event.target.value || null));
});
