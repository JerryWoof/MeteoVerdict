import * as Plot from "@observablehq/plot";
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

import "./style.css";

import {
  biasByElevation, fmt, intervalRows, levelOf, maeByLead, rankingTable, regionList, regionSummary,
} from "./compare.js";
import { NO_DATA, bestByRegion, fillExpression, modelColors, records } from "./data.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";
import { displayName } from "./tv.js";
import { WINDOWS, availableLeadDays, availableVariables, parseHash, windowLabel } from "./view.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const cache = new Map();
function load(view, level) {
  const path = `data/scores/${view.window}/${level}/${view.variable}.json`;
  if (!cache.has(path)) cache.set(path, getJson(path).then(records));
  return cache.get(path);
}

function fillSelect(id, options, current) {
  const select = document.getElementById(id);
  select.replaceChildren(
    ...options.map(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = String(value) === String(current);
      return option;
    }),
  );
}

function cell(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

const pct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Math.round(v * 100)} %`);
const width = () => Math.min(900, document.querySelector(".content").clientWidth);
const PRECIPITATION = new Set(["precipitation_24h", "precipitation_daily"]);

// --- view, kept in the URL: #variable/lead/window/region ---------------------------
function readView() {
  const view = parseHash(window.location.hash);
  view.region = window.location.hash.replace(/^#/, "").split("/")[3] || "cz";
  return view;
}

function writeView(view) {
  window.history.replaceState(null, "", `#${view.variable}/${view.leadDay}/${view.window}/${view.region}`);
}

// --- region picker: Czechia, kraje, okresy -----------------------------------------
function fillRegions(kraje, okresy, current) {
  const select = document.getElementById("region");
  const group = (label, items) => {
    const g = document.createElement("optgroup");
    g.label = label;
    g.append(
      ...items.map(({ code, name }) => {
        const option = document.createElement("option");
        option.value = code;
        option.textContent = displayName(name);
        option.selected = code === current;
        return option;
      }),
    );
    return g;
  };
  const cz = document.createElement("option");
  cz.value = "cz";
  cz.textContent = "Česko";
  cz.selected = current === "cz";
  select.replaceChildren(cz, group(t("compare.kraje"), kraje), group(t("compare.okresy"), okresy));
}

// --- the small map: best model per okres, click to choose ---------------------------
const map = new MapLibreMap({
  container: "mini-map",
  style: {
    version: 8,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": "#f4f1ea" } }],
  },
  bounds: [
    [12.0, 48.5],
    [18.95, 51.1],
  ],
  fitBoundsOptions: { padding: 10 },
  attributionControl: { customAttribution: "ČÚZK (CC BY 4.0)" },
});
map.addControl(new NavigationControl({ showCompass: false }));
const mapLoaded = new Promise((resolve) => map.on("load", resolve));

function addLayers(onPick) {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({ id: "fill", type: "fill", source: "okresy", paint: { "fill-color": NO_DATA, "fill-opacity": 0.8 } });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.5 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1 } });
  for (const [id, source] of [["sel-okres", "okresy"], ["sel-kraj", "kraje"]]) {
    map.addLayer({
      id,
      type: "line",
      source,
      filter: ["==", ["get", "code"], ""],
      paint: { "line-color": "#1d2329", "line-width": 2.5 },
    });
  }
  map.on("click", "fill", (event) => onPick(event.features[0].properties.code));
  map.on("mouseenter", "fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "fill", () => (map.getCanvas().style.cursor = ""));
}

function paintMap(okresRows, view, colors, names) {
  const best = bestByRegion(okresRows, view.leadDay);
  map.setPaintProperty("fill", "fill-color", fillExpression(best, colors));
  // legend: the models that win somewhere, by number of okresy
  const wins = new Map();
  for (const entry of best.values()) if (entry.model) wins.set(entry.model, (wins.get(entry.model) ?? 0) + 1);
  const legend = document.getElementById("mini-legend");
  legend.replaceChildren(
    ...[...wins].sort((a, b) => b[1] - a[1]).map(([model, n]) => {
      const item = cell("span", null, "legend-item");
      const swatch = cell("span", "", "swatch");
      swatch.style.background = colors[model] ?? "#888888";
      item.append(swatch, `${names[model] ?? model} (${n})`);
      return item;
    }),
  );
  const level = levelOf(view.region);
  map.setFilter("sel-okres", ["==", ["get", "code"], level === "okres" ? view.region : ""]);
  map.setFilter("sel-kraj", ["==", ["get", "code"], level === "kraj" ? view.region : ""]);
}

// --- summary, table and charts ------------------------------------------------------
function renderSummary(rows, view, names, colors) {
  const box = document.getElementById("summary");
  const s = regionSummary(rows, view.leadDay, view.region);
  const name = view.region === "cz" ? "Česko" : displayName(s?.name ?? view.region);
  const heading = cell("h2", name);
  if (!s) {
    box.replaceChildren(heading, cell("p", t("compare.empty")));
    return;
  }
  const best = document.createElement("p");
  best.className = "best";
  const swatch = cell("span", "", "swatch");
  swatch.style.background = colors[s.model] ?? "#888888";
  best.append(swatch, cell("strong", names[s.model] ?? s.model), ` · MAE ${fmt(s.mae)}`);
  const lines = [
    t(`variable.${view.variable}`) + `, D+${view.leadDay}, ` + t(`window.${view.window}`).toLowerCase(),
    s.clear ? t("compare.clear") : t("compare.notClear", { n: s.tied }),
    t("compare.basis", { stations: s.stations, days: s.days }) +
      (s.borrowed ? ` ${t("compare.borrowed", { n: s.borrowed })}` : ""),
  ];
  const children = [heading, cell("p", lines[0], "note"), best, cell("p", lines[1]), cell("p", lines[2], "note")];
  if (levelOf(view.region) === "okres") {
    const link = document.createElement("a");
    link.href = `forecast.html#${view.region}`;
    link.textContent = t("forecast.link");
    children.push(link);
  }
  box.replaceChildren(...children);
}

function renderTable(rows, view, names) {
  const table = document.getElementById("ranking");
  const rain = PRECIPITATION.has(view.variable);
  const keys = ["rank", "model", "mae", "diff", "skill", "bias", "rmse", ...(rain ? ["ets", "pod", "far"] : []), "stations", "days"];
  const head = document.createElement("tr");
  for (const key of keys) head.append(cell("th", t(`table.${key}`), ["rank", "model"].includes(key) ? "" : "num"));
  const data = rankingTable(rows, view.leadDay, view.region);
  const body = data.map((r) => {
    const tr = document.createElement("tr");
    if (r.rank == null) tr.className = "baseline";
    else if (r.rank === 1) tr.className = "winner";
    const ci = r.ci && r.rank !== 1 ? ` ${t("compare.interval", { low: fmt(r.ci[0], true), high: fmt(r.ci[1], true) })}` : "";
    const values = {
      rank: r.rank == null ? "–" : `${r.tied ? "≈" : ""}${r.rank}`,
      model: r.model === "blend" ? t("model.blend") : (names[r.model] ?? r.model),
      mae: fmt(r.mae),
      diff: r.rank === 1 ? t("compare.best") : r.diff == null ? "–" : `${fmt(r.diff, true)}${ci}`,
      skill: pct(r.skill),
      bias: fmt(r.bias, true),
      rmse: fmt(r.rmse),
      ets: fmt(r.ets),
      pod: fmt(r.pod),
      far: fmt(r.far),
      stations: r.borrowed ? `${r.stations} (${r.borrowed})` : (r.stations ?? "–"),
      days: r.days ?? "–",
    };
    for (const key of keys) tr.append(cell("td", String(values[key]), ["rank", "model"].includes(key) ? "" : "num"));
    return tr;
  });
  if (body.length === 0) {
    const tr = document.createElement("tr");
    tr.append(cell("td", t("compare.empty")));
    body.push(tr);
  }
  table.replaceChildren(head, ...body);
}

function renderIntervals(rows, view, names, colors) {
  const target = document.getElementById("intervals");
  const data = intervalRows(rankingTable(rows, view.leadDay, view.region));
  if (data.length < 2) {
    target.replaceChildren(cell("p", t("compare.empty")));
    return;
  }
  const label = (m) => names[m] ?? m;
  target.replaceChildren(
    Plot.plot({
      width: width(),
      height: 40 + 24 * data.length,
      marginLeft: 210,
      x: { label: t("compare.diffAxis"), grid: true },
      y: { label: null, domain: data.map((r) => label(r.model)) },
      marks: [
        Plot.ruleX([0], { stroke: "#1d2329" }),
        Plot.ruleY(data, { y: (r) => label(r.model), x1: "low", x2: "high", stroke: (r) => (r.tied ? "#9aa7b1" : "#c0392b"), strokeWidth: 3 }),
        Plot.dot(data, { y: (r) => label(r.model), x: "diff", fill: (r) => colors[r.model] ?? "#888888", r: 5, tip: true }),
      ],
    }),
  );
}

function renderByLead(rows, view, names, colors) {
  const target = document.getElementById("by-lead");
  const data = maeByLead(rows, view.region);
  if (data.length === 0) {
    target.replaceChildren(cell("p", t("compare.empty")));
    return;
  }
  const models = [...new Set(data.map((r) => r.model))];
  const label = (m) => (m === "blend" ? t("model.blend") : (names[m] ?? m));
  target.replaceChildren(
    Plot.plot({
      width: width(),
      height: 300,
      marginLeft: 50,
      x: { label: t("control.lead"), ticks: [1, 2, 3, 4, 5], tickFormat: (d) => `D+${d}` },
      y: { label: "MAE", grid: true, zero: true },
      color: {
        domain: models.map(label),
        range: models.map((m) => (m === "blend" ? "#1d2329" : (colors[m] ?? "#888888"))),
        legend: true,
      },
      marks: [
        Plot.ruleX([view.leadDay], { stroke: "#ddd8cc", strokeWidth: 8 }),
        Plot.lineY(
          data.filter((r) => r.model !== "blend"),
          { x: "lead_day", y: "mae", stroke: (r) => label(r.model), strokeWidth: 1.5, marker: "circle", tip: true },
        ),
        Plot.lineY(
          data.filter((r) => r.model === "blend"),
          { x: "lead_day", y: "mae", stroke: (r) => label(r.model), strokeWidth: 2.5, strokeDasharray: "5,4", tip: true },
        ),
      ],
    }),
  );
}

function renderBias(rows, view, names, colors) {
  const section = document.getElementById("elevation-section");
  section.hidden = view.region !== "cz";
  if (section.hidden) return;
  const target = document.getElementById("bias");
  const data = biasByElevation(rows, view.leadDay);
  if (data.length === 0) {
    target.replaceChildren(cell("p", t("compare.empty")));
    return;
  }
  const models = [...new Set(data.map((r) => r.model))];
  target.replaceChildren(
    Plot.plot({
      width: width(),
      marginLeft: 210,
      marginRight: 130,
      x: { label: "Bias", grid: true },
      y: { label: null, tickFormat: (m) => names[m] ?? m },
      fy: { label: null, domain: ["lowland", "upland", "mountain"], tickFormat: (e) => t(`elevation.${e}`) },
      color: { domain: models, range: models.map((m) => colors[m] ?? "#888888") },
      marks: [Plot.barX(data, { x: "bias", y: "model", fy: "elevation", fill: "model", tip: true }), Plot.ruleX([0])],
    }),
  );
}

async function main() {
  const meta = await getJson("data/scores/meta.json");
  document.getElementById("status").textContent = statusText(meta, t);
  const names = { ...meta?.models, blend: t("model.blend") };
  const colors = modelColors(names);
  const view = readView();

  async function render() {
    const level = levelOf(view.region);
    const [rows, okresRows] = await Promise.all([load(view, level), load(view, "okres")]);
    const leadDays = availableLeadDays(rows);
    if (!leadDays.includes(view.leadDay)) view.leadDay = leadDays[0];
    fillSelect("lead", leadDays.map((d) => [d, `D+${d}`]), view.leadDay);
    document.getElementById("region").value = view.region;
    document.getElementById("ranking-title").textContent = t("compare.rankingIn", {
      region: view.region === "cz" ? "Česko" : displayName(regionList(rows).find((r) => r.code === view.region)?.name ?? view.region),
    });
    renderSummary(rows, view, names, colors);
    renderTable(rows, view, names);
    renderIntervals(rows, view, names, colors);
    renderByLead(rows, view, names, colors);
    renderBias(view.region === "cz" ? await load(view, "elevation") : [], view, names, colors);
    if (map.getLayer("fill")) paintMap(okresRows, view, colors, names);
    writeView(view);
  }

  const [kraje, okresy] = await Promise.all([load(view, "kraj"), load(view, "okres")]);
  const known = new Set(["cz", ...regionList(kraje).map((r) => r.code), ...regionList(okresy).map((r) => r.code)]);
  if (!known.has(view.region)) view.region = "cz";
  fillRegions(regionList(kraje), regionList(okresy), view.region);
  fillSelect("variable", availableVariables(meta).map((v) => [v, t(`variable.${v}`)]), view.variable);
  // each period with its real dates and days, so a short history explains itself
  const language = document.documentElement.lang;
  fillSelect("window", WINDOWS.map((w) => [w, windowLabel(w, meta?.windows, t, language)]), view.window);
  for (const [id, key, parse] of [
    ["region", "region", String],
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
  await mapLoaded;
  addLayers((code) => {
    view.region = view.region === code ? "cz" : code;
    render();
  });
  render();
}

main();
