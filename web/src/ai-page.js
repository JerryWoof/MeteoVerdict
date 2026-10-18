import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import * as Plot from "@observablehq/plot";

import { setUpLanguage } from "./i18n.js";
import { colorFor, renderScale } from "./palette.js";
import { displayName } from "./tv.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();
const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
// AI minus combined: blue where the AI is colder / calmer, red where warmer / windier
const DIFF_RAMP = [[-2, [33, 102, 172]], [-0.5, [146, 197, 222]], [0, [247, 247, 247]], [0.5, [244, 165, 130]], [2, [178, 24, 43]]];
const DIFF_GRADIENT = "linear-gradient(to right, #2166ac, #92c5de 37.5%, #f7f7f7 50%, #f4a582 62.5%, #b2182b)";
const UNITS = { temperature_2m: "°C", wind_speed_10m: "m/s", precipitation_daily: "mm" };

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function fmt(value, digits = 2) {
  return value == null ? "–" : value.toLocaleString(document.documentElement.lang, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function dateText(iso) {
  return new Intl.DateTimeFormat(document.documentElement.lang, { day: "numeric", month: "numeric", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
}

/** "better" only when the whole interval of AI minus combined is below zero. */
export function verdict(row) {
  if (row.high != null && row.high < 0) return "better";
  if (row.low != null && row.low > 0) return "worse";
  return "same";
}

function cell(tag, text, className) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function verdictCell(row, v) {
  const td = cell("td", "", `ai-verdict ${v}`);
  td.append(cell("b", fmt(row.diff)), " ", cell("span", t(`ai.${v}`)), cell("small", `[${fmt(row.low)}; ${fmt(row.high)}]`));
  return td;
}

function renderScores(doc) {
  const box = document.getElementById("ai-scores");
  const parts = [];
  for (const variable of [...new Set(doc.scores.map((r) => r.variable))]) {
    const unit = UNITS[variable] ?? "";
    const table = document.createElement("table");
    table.className = "doc-table data-table ai-score-table";
    const head = document.createElement("tr");
    head.append(
      cell("th", t("ai.colLead")),
      cell("th", `${t("ai.colAi")} (${unit})`, "num"),
      cell("th", `${t("ai.colCombined")} (${unit})`, "num"),
      cell("th", `${t("ai.colBest")} (${unit})`, "num"),
      cell("th", t("ai.colVerdict")),
    );
    const rows = [head];
    for (const row of doc.scores.filter((r) => r.variable === variable)) {
      const v = verdict(row);
      const tr = document.createElement("tr");
      tr.append(
        cell("td", `D+${row.lead_day}`),
        cell("td", fmt(row.mae_ai), "num"),
        cell("td", fmt(row.mae_combined), "num"),
        cell("td", fmt(row.mae_best), "num"),
        verdictCell(row, v),
      );
      rows.push(tr);
    }
    table.replaceChildren(...rows);
    parts.push(cell("h4", t(`variable.${variable}`)), table);
  }
  box.replaceChildren(...parts);
}

/** An experiment's own result table ({columns: [{key, cs, en}], rows}). */
function resultTable(table, lang) {
  const el = document.createElement("table");
  el.className = "doc-table data-table ai-result-table";
  const head = document.createElement("tr");
  head.append(...table.columns.map((c) => cell("th", c[lang] ?? c.en ?? c.key)));
  const rows = table.rows.map((row) => {
    const tr = document.createElement("tr");
    const values = Array.isArray(row) ? row : table.columns.map((c) => row[c.key]);
    tr.append(...values.map((v) => cell("td", typeof v === "number" ? fmt(v) : String(v ?? "–"))));
    return tr;
  });
  el.replaceChildren(head, ...rows);
  return el;
}

function renderExperiments(doc) {
  const box = document.getElementById("ai-experiments");
  box.replaceChildren(
    ...doc.experiments.map((e) => {
      const card = document.createElement("article");
      card.className = `ai-card ${e.status}`;
      const title = document.createElement("h3");
      title.append(cell("span", t(`ai.exp.${e.id}.name`)), " ", cell("span", t(`ai.status.${e.status}`), `ai-status ${e.status}`));
      card.append(title, cell("p", t(`ai.exp.${e.id}.what`)));
      const lang = document.documentElement.lang;
      if (e.headline?.[lang]) card.append(cell("p", e.headline[lang], "ai-result"));
      else if (e.result) card.append(cell("p", t(`ai.exp.${e.id}.result`, e.result), "ai-result"));
      if (e.table?.columns && e.table.rows?.length) {
        card.append(resultTable(e.table, lang));
        card.classList.add("wide");
      }
      card.append(cell("p", t("ai.tech", { tech: e.tech }), "ai-tech"));
      return card;
    }),
  );
}

const AI_COLOR = "#6a4fb3";
const COMBINED_COLOR = "#8a949c";

function chartWidth(el) {
  return Math.max(300, Math.min(900, el.clientWidth || 640));
}

function renderForecast(okres, entry) {
  for (const variable of ["temperature_2m", "wind_speed_10m"]) {
    const target = document.getElementById(`ai-chart-${variable}`);
    const series = entry[variable];
    if (!series) {
      target.replaceChildren();
      continue;
    }
    const rows = [];
    entry.time.forEach((time, i) => {
      const date = new Date(time.replace("Z", ":00Z"));
      if (series.ai[i] != null) rows.push({ date, value: series.ai[i], line: t("ai.fcAi") });
      if (series.combined[i] != null) rows.push({ date, value: series.combined[i], line: t("ai.fcCombined") });
    });
    target.replaceChildren(
      Plot.plot({
        width: chartWidth(target),
        height: 220,
        marginLeft: 40,
        x: {
          type: "time", label: null, ticks: "day",
          tickFormat: (d) => new Intl.DateTimeFormat(document.documentElement.lang, { weekday: "short", day: "numeric", timeZone: "Europe/Prague" }).format(d),
        },
        y: { label: UNITS[variable], grid: true, zero: variable === "wind_speed_10m" },
        color: { domain: [t("ai.fcAi"), t("ai.fcCombined")], range: [AI_COLOR, COMBINED_COLOR], legend: true },
        marks: [
          Plot.line(rows, { x: "date", y: "value", stroke: "line", strokeWidth: (r) => (r.line === t("ai.fcAi") ? 2.5 : 1.5) }),
          Plot.tip(rows, Plot.pointerX({ x: "date", y: "value", stroke: "line", title: (r) => `${r.line}: ${fmt(r.value, 1)} ${UNITS[variable]}` })),
        ],
      }),
    );
  }
  window.history.replaceState(null, "", `#${okres}`);
}

function diffColor(v) {
  if (v == null) return "#ececec";
  const r = DIFF_RAMP;
  if (v <= r[0][0]) return `rgb(${r[0][1]})`;
  for (let i = 1; i < r.length; i += 1) {
    if (v <= r[i][0]) {
      const f = (v - r[i - 1][0]) / (r[i][0] - r[i - 1][0]);
      return `rgb(${r[i - 1][1].map((c, k) => Math.round(c + f * (r[i][1][k] - c)))})`;
    }
  }
  return `rgb(${r.at(-1)[1]})`;
}

/** The value an okres shows on the map: the AI's, or AI minus combined. */
export function mapValue(entry, layer, index) {
  const diff = layer.startsWith("diff_");
  const series = entry[diff ? layer.slice(5) : layer];
  const ai = series?.ai[index];
  if (ai == null) return null;
  if (!diff) return ai;
  const combined = series.combined[index];
  return combined == null ? null : Math.round((ai - combined) * 10) / 10;
}

function setUpMap(fc, onPick, overlay = null) {
  const codes = Object.keys(fc.okresy);
  const first = fc.okresy[codes[0]];
  // every 6 hours (00, 06, 12, 18 UTC) of the forecast
  const times = first.time.map((time, i) => ({ time, i })).filter(({ time }) => /T(00|06|12|18):/.test(time));
  const layerSelect = document.getElementById("ai-map-layer");
  const timeSelect = document.getElementById("ai-map-time");
  const layers = ["temperature_2m", "wind_speed_10m", "diff_temperature_2m", "diff_wind_speed_10m"];
  if (overlay) layers.push("temp100m");
  layerSelect.replaceChildren(...layers.map((l) => Object.assign(document.createElement("option"), { value: l, textContent: t(`ai.layer.${l}`) })));
  const when = new Intl.DateTimeFormat(document.documentElement.lang, { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Prague" });
  timeSelect.replaceChildren(...times.map(({ time, i }) => Object.assign(document.createElement("option"), { value: String(i), textContent: when.format(new Date(time.replace("Z", ":00Z"))) })));
  const map = new MapLibreMap({
    container: "ai-map",
    style: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#f4f1ea" } }] },
    bounds: BOUNDS,
    fitBoundsOptions: { padding: 20 },
    attributionControl: { customAttribution: "Boundaries: ČÚZK (CC BY 4.0)" },
  });
  map.addControl(new NavigationControl({ showCompass: false }));
  new ResizeObserver(() => map.resize()).observe(map.getContainer());
  const paint = () => {
    if (!map.getLayer("okresy-fill")) return;
    const layer = layerSelect.value;
    const index = Number(timeSelect.value);
    const fine = layer === "temp100m";
    timeSelect.disabled = fine;
    if (map.getLayer("temp100m")) map.setLayoutProperty("temp100m", "visibility", fine ? "visible" : "none");
    map.setLayoutProperty("okresy-fill", "visibility", fine ? "none" : "visible");
    if (fine) {
      const box = document.getElementById("ai-scale");
      const { min, max, unit } = overlay.meta.legend ?? {};
      const bar = cell("div", null, "bar");
      bar.style.background = overlay.meta.gradient ?? "linear-gradient(to right, #313695, #abd9e9, #fee090, #f46d43, #a50026)";
      const at = overlay.meta.time ? when.format(new Date(overlay.meta.time)) : "";
      box.replaceChildren(cell("div", `${t("ai.layer.temp100m")} ${at}`, "scale-title"), bar, cell("div", `${min ?? ""} … ${max ?? ""} ${unit ?? ""}`, "scale-ends"));
      return;
    }
    const pairs = [];
    for (const code of codes) {
      const v = mapValue(fc.okresy[code], layer, index);
      const color = layer.startsWith("diff_") ? diffColor(v) : colorFor(v, layer === "temperature_2m" ? "temperature" : "wind");
      pairs.push(code, color);
    }
    map.setPaintProperty("okresy-fill", "fill-color", ["match", ["get", "code"], ...pairs, "#ececec"]);
    const box = document.getElementById("ai-scale");
    if (layer.startsWith("diff_")) {
      const unit = UNITS[layer.slice(5)];
      const bar = cell("div", null, "bar");
      bar.style.background = DIFF_GRADIENT;
      box.replaceChildren(cell("div", t(`ai.layer.${layer}`), "scale-title"), bar, cell("div", `−2 ${unit} … +2 ${unit}`, "scale-ends"));
    } else {
      renderScale(box, layer === "temperature_2m" ? "temperature" : "wind", t(`ai.layer.${layer}`));
    }
  };
  map.on("load", () => {
    map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
    map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
    map.addLayer({ id: "okresy-fill", type: "fill", source: "okresy", paint: { "fill-color": "#ececec", "fill-opacity": 0.9 } });
    if (overlay) {
      const [w, so, e, n] = overlay.meta.bounds;
      map.addSource("temp100m", { type: "image", url: overlay.png, coordinates: [[w, n], [e, n], [e, so], [w, so]] });
      map.addLayer({ id: "temp100m", type: "raster", source: "temp100m", layout: { visibility: "none" }, paint: { "raster-opacity": 0.95, "raster-resampling": "nearest" } });
    }
    map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
    map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.2 } });
    map.addLayer({ id: "okres-selected", type: "line", source: "okresy", filter: ["==", ["get", "code"], ""], paint: { "line-color": "#1d2329", "line-width": 2.5 } });
    map.on("click", "okresy-fill", (event) => onPick(event.features[0].properties.code));
    map.on("mouseenter", "okresy-fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "okresy-fill", () => (map.getCanvas().style.cursor = ""));
    paint();
  });
  layerSelect.addEventListener("change", paint);
  timeSelect.addEventListener("change", paint);
  return {
    select(code) {
      if (map.getLayer("okres-selected")) map.setFilter("okres-selected", ["==", ["get", "code"], code]);
      else map.once("load", () => map.setFilter("okres-selected", ["==", ["get", "code"], code]));
    },
  };
}

function setUpForecast(fc, overlay) {
  const name = ([code, o]) => displayName(o.name ?? code);
  const okresy = Object.entries(fc.okresy).sort((a, b) => name(a).localeCompare(name(b), "cs"));
  if (okresy.length === 0) return;
  const select = document.getElementById("ai-okres");
  select.replaceChildren(...okresy.map((entry) => Object.assign(document.createElement("option"), { value: entry[0], textContent: name(entry) })));
  const wanted = window.location.hash.slice(1);
  select.value = fc.okresy[wanted] ? wanted : fc.okresy.CZ0100 ? "CZ0100" : okresy[0][0];
  document.getElementById("ai-fc-intro").textContent = t("ai.fcIntro", {
    time: new Intl.DateTimeFormat(document.documentElement.lang, { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague" }).format(new Date(fc.issued)),
  });
  document.getElementById("ai-forecast").hidden = false;
  let map = null;
  const show = () => {
    renderForecast(select.value, fc.okresy[select.value]);
    map?.select(select.value);
  };
  map = setUpMap(fc, (code) => {
    select.value = code;
    show();
  }, overlay);
  select.addEventListener("change", show);
  show();
}

async function main() {
  const status = document.getElementById("status");
  const [doc, fc] = await Promise.all([getJson("data/scores/ai/ai.json"), getJson("data/scores/ai/ai-forecast.json")]);
  // the 100 m temperature of the downscaling experiment, when it has made one
  const fine = doc?.experiments?.find((e) => e.map?.png && e.map?.meta);
  const meta = fine ? await getJson(`data/scores/ai/${fine.map.meta}`) : null;
  const overlay = meta?.bounds ? { png: `data/scores/ai/${fine.map.png}`, meta } : null;
  if (fc) setUpForecast(fc, overlay);
  if (!doc) {
    status.textContent = t("ai.none");
    return;
  }
  status.textContent = t("ai.updated", {
    time: new Intl.DateTimeFormat(document.documentElement.lang, { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague" }).format(new Date(doc.generated)),
  });
  if (doc.scores?.length) {
    document.getElementById("ai-model-intro").textContent = t("ai.modelIntro", { models: doc.model.models });
    document.getElementById("ai-score-intro").textContent = t("ai.scoreIntro", {
      range: `${dateText(doc.test.from)}–${dateText(doc.test.to)}`, days: doc.test.days,
    });
    renderScores(doc);
    document.getElementById("ai-model").hidden = false;
  }
  renderExperiments(doc);
}

main();
