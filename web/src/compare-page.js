import * as Plot from "@observablehq/plot";
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

import "./style.css";

import {
  BLEND_TEST_SERIES, BLEND_TEST_VARIABLES, HOME_MODEL, biasByElevation, blendTestLines, blendTestRows, blendTestVariable,
  blendVerdict, blendVerdicts, fmt as fmtIn, okresVerdictCounts, intervalRows, isAladin, leadHourBasis, leadHourLines, leadHourRanking, leadHourRunHours,
  leadHourVariable, levelOf, maeByLead, rankingTable, regionList, regionSummary, singleModelVerdicts, unpublishedHours,
  RANK_BY, STATION_SETS, hasValues, sortByEts,
  BAND_RANK_BY, BAND_VARIABLES, BAND_WINDOWS, LEAD_BANDS, LEAD_DAYS, bandBasis, bandRecords, bandSets, bandVariable,
  bandsIn, compareHash, compareIsStep, compareViewFromHash, dayVariable, defaultLead, isBand, krajOf, leadLabel, maeByBand, parseLead,
  numberTick, tipText,
} from "./compare.js";
import { hashHistory } from "./hash-history.js";
import { binLabel, count as countIn, etsColor, etsTextColor, farmChoices, farmGrid, plain, score as scoreIn } from "./farm.js";
import { NO_DATA, bestByRegion, fillExpression, modelColors, records } from "./data.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";
import { cssVar, isDark, onThemeChange } from "./theme.js";
import { setUpTips } from "./tip-popover.js";
import { displayName } from "./tv.js";
import {
  availableLeadDays, availableVariables, availableWindows, dayCount, filesWindow, formatRange, pickWindow, pluralForm,
  stationCount, windowLabel,
} from "./view.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();
// the cells' details (blend test, farm ranking) and the "?": on hover, tap and focus
setUpTips();
// numbers in the page language ("1,18" and "4 574" in Czech)
const LANGUAGE = document.documentElement.lang || "en";
const fmt = (value, signed) => fmtIn(value, signed, LANGUAGE);
const count = (value) => countIn(value, LANGUAGE);
const score = (value) => scoreIn(value, LANGUAGE);
const tickNumber = numberTick(LANGUAGE);

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const cache = new Map();
let scoresMeta = null;
function load(view, level) {
  const path = `data/scores/${filesWindow(view.window, scoresMeta)}/${level}/${view.variable}.json`;
  if (!cache.has(path)) {
    // a failed fetch is not remembered: the next view tries again
    cache.set(path, getJson(path).then((doc) => {
      if (!doc) cache.delete(path);
      return records(doc);
    }));
  }
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

const pct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Math.round(v * 100)} %`.replace("-", "−"));
// the charts fill the text column up to 1200 px (as on forecast-detail); clientWidth
// counts the column's side padding, so that comes off or the chart is wider than the column
const width = () => {
  const column = document.querySelector(".content");
  const style = getComputedStyle(column);
  return Math.min(1200, column.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
};
const PRECIPITATION = new Set(["precipitation_24h", "precipitation_daily"]);

// --- the view, kept in the URL (compare.js compareViewFromHash): another variable or region
// is a step in the browser's history (Back returns to the one before), the other choices
// replace the current entry
const readView = () => compareViewFromHash(window.location.hash);
let address = null; // hashHistory, set up by main()
let written = null; // the view last put in the address (null: the next write replaces)
function writeView(view) {
  address?.write(compareHash(view), compareIsStep(written, view));
  written = { ...view };
}

// --- the ranking by lead band (leads-bands-<window>[-kraj].json; hidden until it exists)
const bandCache = new Map();
/** {doc, rows} of a band file: Czechia and the station kinds, or the kraje. */
function loadBands(window_, kraj = false) {
  const path = `data/scores/leads-bands-${window_}${kraj ? "-kraj" : ""}.json`;
  if (!bandCache.has(path)) {
    bandCache.set(path, getJson(path).then((doc) => {
      if (!doc) bandCache.delete(path);
      return { doc, rows: bandRecords(doc) };
    }));
  }
  return bandCache.get(path);
}

/** The band window for the page's window: 90 days or all (the seasons are D+N only). */
const bandWindow = (window_) => (BAND_WINDOWS.includes(window_) ? window_ : "90d");

/** The lead select: hours ahead (from every run) and days ahead, as two groups. */
function fillLead(bands, days, current) {
  const select = document.getElementById("lead");
  const group = (label, leads) => {
    const g = document.createElement("optgroup");
    g.label = label;
    g.append(...leads.map((lead) => {
      const option = document.createElement("option");
      option.value = String(lead);
      option.textContent = leadLabel(lead);
      option.selected = String(lead) === String(current);
      return option;
    }));
    return g;
  };
  const groups = [];
  if (bands.length) groups.push(group(t("compare.leadBands"), bands));
  groups.push(group(t("compare.leadDays"), days));
  select.replaceChildren(...groups);
}

/** A segmented switch: `options` [[value, label]]; `onPick(value)` when another is chosen. */
function fillSegmented(id, options, current, onPick) {
  document.getElementById(id).replaceChildren(...options.map(([value, label]) => {
    const button = cell("button", label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(value === current));
    button.addEventListener("click", () => {
      if (value !== current) onPick(value);
    });
    return button;
  }));
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
  cz.textContent = t("region.cz");
  cz.selected = current === "cz";
  // sorted by the name shown ("Praha", not "Hlavní město Praha"), in the page language
  const shown = [...okresy].sort((a, b) => displayName(a.name).localeCompare(displayName(b.name), LANGUAGE));
  okresGroup = group(t("compare.okresy"), shown);
  select.replaceChildren(cz, group(t("compare.kraje"), kraje), okresGroup);
}

let okresGroup = null;
/** Region code → name (kraje and okresy), for regions without scores in the view shown. */
const regionNames = new Map();
/** Okresy cannot be chosen for a band of hours (too few run stations): disabled, said so. */
function setOkresChoice(enabled) {
  if (!okresGroup) return;
  okresGroup.disabled = !enabled;
  okresGroup.label = enabled ? t("compare.okresy") : t("compare.okresyDaysOnly");
}

// --- the small map: best model per okres, click to choose ---------------------------
const map = new MapLibreMap({
  container: "mini-map",
  style: {
    version: 8,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": cssVar("--paper") } }],
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

/** The map's lines and background in the colours of the current theme. */
function paintMapTheme() {
  const set = (layer, prop, value) => map.getLayer(layer) && map.setPaintProperty(layer, prop, value);
  set("background", "background-color", cssVar("--paper"));
  set("okresy-line", "line-color", cssVar("--surface"));
  set("kraje-line", "line-color", cssVar("--muted-strong"));
  set("sel-okres", "line-color", cssVar("--ink"));
  set("sel-kraj", "line-color", cssVar("--ink"));
}

function addLayers(onPick) {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({ id: "fill", type: "fill", source: "okresy", paint: { "fill-color": NO_DATA, "fill-opacity": 0.8 } });
  // bands of hours: the best model per kraj (no okres level)
  map.addLayer({
    id: "kraj-fill", type: "fill", source: "kraje", layout: { visibility: "none" },
    paint: { "fill-color": NO_DATA, "fill-opacity": 0.8 },
  });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": cssVar("--surface"), "line-width": 0.5 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": cssVar("--muted-strong"), "line-width": 1 } });
  for (const [id, source] of [["sel-okres", "okresy"], ["sel-kraj", "kraje"]]) {
    map.addLayer({
      id,
      type: "line",
      source,
      filter: ["==", ["get", "code"], ""],
      paint: { "line-color": cssVar("--ink"), "line-width": 2.5 },
    });
  }
  for (const layer of ["fill", "kraj-fill"]) {
    map.on("click", layer, (event) => onPick(event.features[0].properties.code));
    map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }
}

/** The map: best model per okres (lead days) or per kraj (bands of hours). */
function paintMap(areaRows, view, colors, names) {
  const band = isBand(view.leadDay);
  const best = bestByRegion(areaRows, view.leadDay);
  const layer = band ? "kraj-fill" : "fill";
  map.setLayoutProperty("fill", "visibility", band ? "none" : "visible");
  map.setLayoutProperty("kraj-fill", "visibility", band ? "visible" : "none");
  map.setPaintProperty(layer, "fill-color", fillExpression(best, colors));
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
  const name = view.region === "cz" ? t("region.cz") : displayName(s?.name ?? regionNames.get(view.region) ?? view.region);
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
  const band = isBand(view.leadDay);
  const variable = band ? t(`bandVariable.${bandVariable(view.variable)}`) : t(`variable.${view.variable}`);
  const windowName = t(`window.${band ? bandWindow(view.window) : view.window}`).toLowerCase();
  const basis = band ? bandBasis(rows, view.leadDay, view.region) : null;
  const lines = [
    `${variable}, ${leadLabel(view.leadDay)}${band ? ` (${t("compare.fromRuns")})` : ""}, ${windowName}`,
    s.clear ? t("compare.clear") : t(`compare.notClear.${pluralForm(s.tied)}`, { n: s.tied }),
    basis
      ? t("compare.bandBasisShort", basis)
      : t("compare.basis", { stations: stationCount(s.stations, t), days: dayCount(s.days, t) }) +
        (s.borrowed ? ` ${t("compare.borrowed", { n: s.borrowed })}` : ""),
  ];
  const children = [heading, cell("p", lines[0], "note"), best, cell("p", lines[1]), cell("p", lines[2], "note")];
  if (basis?.preliminary) children.push(cell("p", t("compare.preliminary", { days: basis.days }), "note preliminary"));
  if (levelOf(view.region) === "okres") {
    const blend = cell("p", null, "note");
    children.push(blend);
    summaryBlend(blend, view);
    const link = document.createElement("a");
    link.href = `forecast-detail.html#${view.region}`;
    link.textContent = t("forecast.link");
    children.push(link);
  }
  box.replaceChildren(...children);
}

/** The station sets offered for the ranking table (all, main, other) and the one shown. */
function stationChoice(view, networkRows) {
  const sets = STATION_SETS.filter((set) => set === "all" || networkRows.some((r) => r.region === set));
  const shown = view.region === "cz" && sets.includes(view.stations) ? view.stations : "all";
  return { sets, shown };
}

/** The station switch above the ranking table: Czechia only, when the scores have it. */
function renderStations(view, choice, rows, onChange) {
  const block = document.getElementById("stations-block");
  block.hidden = view.region !== "cz" || choice.sets.length < 2;
  const note = document.getElementById("stations-note");
  note.hidden = block.hidden || choice.shown === "all";
  if (block.hidden) return;
  fillSegmented("stations", choice.sets.map((set) => [set, t(`compare.stations.${set}`)]), choice.shown, (set) => {
    view.stations = set;
    onChange();
  });
  if (!note.hidden) {
    const best = rankingTable(rows, view.leadDay, choice.shown).find((r) => r.stations != null);
    note.textContent = t(`compare.stationsNote.${choice.shown}`, { n: best?.stations ?? "–" });
  }
}

/** The sort switch above the table (precipitation with event scores only): MAE or ETS. */
function rankByChoice(view, data) {
  const band = isBand(view.leadDay);
  if (band ? bandVariable(view.variable) !== "precipitation" : !PRECIPITATION.has(view.variable)) {
    return { options: [], shown: "mae" };
  }
  const options = (band ? BAND_RANK_BY : RANK_BY).filter((key) => key === "mae" || hasValues(data, key));
  return { options, shown: options.includes(view.rankBy) ? view.rankBy : "mae" };
}

function renderTable(rows, view, names, region, onChange) {
  const table = document.getElementById("ranking");
  const band = isBand(view.leadDay);
  const rain = band ? bandVariable(view.variable) === "precipitation" : PRECIPITATION.has(view.variable);
  const data = rankingTable(rows, view.leadDay, region);
  const choice = rankByChoice(view, data);
  const block = document.getElementById("rank-by-block");
  block.hidden = choice.options.length < 2;
  document.getElementById("rank-by-note").hidden = !rain;
  document.getElementById("rank-by-note").textContent = rain ? t(band ? "compare.rankByNoteBand" : "compare.rankByNote") : "";
  if (!block.hidden) {
    const rankLabel = (key) => t(band && key !== "mae" ? `compare.rankByBand.${key}` : `compare.rankBy.${key}`);
    fillSegmented("rank-by", choice.options.map((key) => [key, rankLabel(key)]), choice.shown, (key) => {
      view.rankBy = key;
      onChange();
    });
  }
  const byEts = choice.shown !== "mae";
  const shown = byEts ? sortByEts(data, choice.shown) : data;
  // POD and FAR at the threshold sorted by, else at 1 mm (0.1 mm in older files)
  const at = choice.shown === "ets10" ? "10" : hasValues(data, "ets1") ? "1" : "0p1";
  const pod = { 10: "pod10", 1: "pod1", "0p1": "pod" }[at];
  const far = { 10: "far10", 1: "far1", "0p1": "far" }[at];
  const mm = { 10: "10", 1: "1", "0p1": fmtMm(0.1) }[at];
  const events = [
    "ets", ...(hasValues(data, "ets1") ? ["ets1"] : []), ...(hasValues(data, "ets10") ? ["ets10"] : []), pod, far,
  ];
  const bc = hasValues(data, "maeBc") ? ["maeBc"] : [];
  const keys = byEts
    ? ["rank", "model", choice.shown, ...events.filter((k) => k !== choice.shown), "mae", "bias", "stations", "days"]
    : ["rank", "model", "mae", ...bc, "diff", ...(hasValues(data, "pBest") ? ["pbest"] : []), ...(band ? [] : ["skill"]), "bias", "rmse", ...(rain ? events : []),
      "stations", "days"];
  const label = (key) => {
    if (key === pod || key === far) return t(`table.${key.slice(0, 3)}At`, { mm });
    return t(`table.${key}`);
  };
  const head = document.createElement("tr");
  for (const key of keys) head.append(cell("th", label(key), ["rank", "model"].includes(key) ? "" : "num"));
  const body = shown.map((r) => {
    const tr = document.createElement("tr");
    const position = byEts ? r.etsRank : r.rank;
    if (r.short) tr.className = "short";
    else if (position == null) tr.className = "baseline";
    else if (position === 1) tr.className = "winner";
    const ci = r.ci && r.rank !== 1 ? ` ${t("compare.interval", { low: fmt(r.ci[0], true), high: fmt(r.ci[1], true) })}` : "";
    const values = {
      rank: byEts ? (r.etsRank ?? "–") : r.rank == null ? "–" : `${r.tied ? "≈" : ""}${r.rank}`,
      model: r.model === "blend" ? t("model.blend") : (names[r.model] ?? r.model) + (r.short ? ` (${t("compare.shortRecord")})` : ""),
      mae: fmt(r.mae),
      diff: r.rank === 1 ? t("compare.best") : r.diff == null || r.short ? "–" : `${fmt(r.diff, true)}${ci}`,
      pbest: r.pBest == null || r.short ? "–" : `${Math.round(r.pBest * 100)} %`,
      skill: r.short ? "–" : pct(r.skill),
      bias: fmt(r.bias, true),
      rmse: fmt(r.rmse),
      maeBc: fmt(r.maeBc),
      ets: fmt(r.ets),
      ets1: fmt(r.ets1),
      ets10: fmt(r.ets10),
      pod: fmt(r.pod),
      far: fmt(r.far),
      pod1: fmt(r.pod1),
      far1: fmt(r.far1),
      pod10: fmt(r.pod10),
      far10: fmt(r.far10),
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
  const bcNote = document.getElementById("bc-note");
  bcNote.hidden = bc.length === 0 || byEts;
  bcNote.textContent = bcNote.hidden ? "" : t(band ? "compare.bcNoteBand" : "compare.bcNote");
  const aladinNote = document.getElementById("aladin-note");
  aladinNote.hidden = !data.some((r) => isAladin(r.model));
  aladinNote.textContent = aladinNote.hidden ? "" : t("compare.aladinNote");
}

/** "0,1" or "0.1" in the page's language. */
function fmtMm(value) {
  return value.toLocaleString(document.documentElement.lang === "cs" ? "cs-CZ" : "en-US");
}

function renderIntervals(rows, view, names, colors, region = view.region) {
  const target = document.getElementById("intervals");
  const data = intervalRows(rankingTable(rows, view.leadDay, region));
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
      x: { label: t("compare.diffAxis"), grid: true, tickFormat: tickNumber },
      y: { label: null, domain: data.map((r) => label(r.model)) },
      marks: [
        Plot.ruleX([0], { stroke: "var(--ink)" }),
        Plot.ruleY(data, { y: (r) => label(r.model), x1: "low", x2: "high", stroke: (r) => (r.tied ? "var(--line-strong)" : "var(--accent)"), strokeWidth: 3 }),
        Plot.dot(data, {
          y: (r) => label(r.model), x: "diff", fill: (r) => colors[r.model] ?? "#888888", r: 5, tip: true,
          title: (r) => tipText(label(r.model), t("compare.tipDiff", {
            diff: fmt(r.diff, true), interval: r.low === r.high ? "" : t("compare.interval", { low: fmt(r.low, true), high: fmt(r.high, true) }),
          })),
        }),
      ],
    }),
  );
}

function renderByLead(rows, view, names, colors, region = view.region) {
  const target = document.getElementById("by-lead");
  const band = isBand(view.leadDay);
  document.getElementById("by-lead-note").textContent = t(band ? "compare.byBandNote" : "compare.byLeadNote");
  const data = band ? maeByBand(rows, region) : maeByLead(rows, region);
  if (data.length === 0) {
    target.replaceChildren(cell("p", t("compare.empty")));
    return;
  }
  const models = [...new Set(data.map((r) => r.model))];
  const label = (m) => (m === "blend" ? t("model.blend") : (names[m] ?? m));
  const leadTip = (r) => tipText(label(r.model), band ? leadLabel(LEAD_BANDS[r.lead_day - 1]) : `D+${r.lead_day}`, `MAE ${fmt(r.mae)}`);
  target.replaceChildren(
    Plot.plot({
      width: width(),
      height: 300,
      marginLeft: 50,
      marginRight: band ? 36 : 20,
      x: {
        label: band ? t("compare.leadBands") : t("control.lead"), ticks: [1, 2, 3, 4, 5],
        tickFormat: (d) => (band ? leadLabel(LEAD_BANDS[d - 1]) : `D+${d}`),
        // room at both ends, so the grey column of the first or last lead is drawn whole
        inset: 12,
      },
      y: { label: "MAE", grid: true, zero: true, tickFormat: tickNumber },
      color: {
        domain: models.map(label),
        range: models.map((m) => (m === "blend" ? "var(--ink)" : (colors[m] ?? "#888888"))),
        legend: true,
      },
      marks: [
        Plot.ruleX([band ? LEAD_BANDS.indexOf(view.leadDay) + 1 : view.leadDay], { stroke: "var(--line)", strokeWidth: 8 }),
        Plot.lineY(
          data.filter((r) => r.model !== "blend"),
          { x: "lead_day", y: "mae", stroke: (r) => label(r.model), strokeWidth: 1.5, marker: "circle", tip: true, title: leadTip },
        ),
        Plot.lineY(
          data.filter((r) => r.model === "blend"),
          { x: "lead_day", y: "mae", stroke: (r) => label(r.model), strokeWidth: 2.5, strokeDasharray: "5,4", tip: true, title: leadTip },
        ),
      ],
    }),
  );
}

/** The chosen okres in the blend test, at the ranking's variable and lead day (its own dates). */
async function summaryBlend(target, view) {
  const doc = await blendTestDoc;
  const variable = blendTestVariable(view.variable);
  const row = blendTestRows(doc, view.region).find((r) => r.variable === variable && r.lead_day === view.leadDay);
  const verdict = row && blendVerdict(row);
  if (!verdict) return target.remove();
  target.textContent = t("compare.blendHere", {
    range: formatRange(doc.from, doc.to, document.documentElement.lang),
    variable: t(`variable.${variable}`).toLowerCase(), lead: view.leadDay,
    verdict: verdictText(verdict, doc.units?.[variable] ?? "", true),
  });
}

// --- does our forecast beat one model? (blend-test.json; hidden until it exists) -----
const blendTestDoc = getJson("data/scores/blend-test.json");
const SERIES_COLORS = {
  combined: "var(--accent)", best_cz_oos: "#1f78b4", best_oos: "#6a3d9a", blend: "var(--ink)", best_hindsight: "#7f8c8d",
};
// the blue and the purple on the dark surface (same hues as the dark model palette)
const SERIES_COLORS_DARK = { best_cz_oos: "#3586bc", best_oos: "#9473b6" };
const seriesColor = (s) => (isDark() && SERIES_COLORS_DARK[s]) || SERIES_COLORS[s];
// [series, stroke width, dash]: ours on top
const SERIES_STYLE = [
  ["best_hindsight", 1.5, "4,3"], ["blend", 1.5, null], ["best_oos", 1.5, "2,2"], ["best_cz_oos", 2.2, null],
  ["combined", 3, null],
];
const MARK = { better: "✓", same: "≈", worse: "✗" };
/** The blend test's variable (from the URL); `onChange` keeps the URL in step. */
const blendView = { variable: "temperature_2m", onChange: null };

/** Long or short words for a verdict; `model`: against that model used everywhere. */
function verdictText(v, unit, long = false, model = null) {
  const values = { amount: fmt(v.amount), unit, low: fmt(v.low), high: fmt(v.high), model };
  if (v.verdict === "same") {
    values.amount = fmt(v.amount, true);
    values.low = fmt(v.low, true);
    values.high = fmt(v.high, true);
  }
  return t(`blendTest.${v.verdict}${long ? "Long" : ""}${long && model ? "Cz" : ""}`, values);
}

/**
 * A table of verdicts for the section's chosen variable (the switch above it): a column
 * per lead day, or on a phone (where five lead-day columns do not fit) a row per lead day.
 */
function verdictTable(id, verdicts, leads, unit, modelName, against) {
  const variables = BLEND_TEST_VARIABLES.filter((variable) => verdicts.some((v) => v.variable === variable));
  const verdictCell = (variable, lead) => {
    const v = verdicts.find((x) => x.variable === variable && x.lead_day === lead);
    if (!v) return cell("td", "–");
    const td = cell("td", null, `verdict ${v.verdict}`);
    const model = against === "cz" ? modelName(v.best) : null;
    td.dataset.tip = `${verdictText(v, unit(variable), true, model)} · ${v.days} d`;
    td.tabIndex = 0;
    td.append(cell("strong", `${MARK[v.verdict]} ${verdictText(v, unit(variable))}`), document.createElement("br"));
    const range = v.verdict === "same"
      ? t("blendTest.sameInterval", { amount: fmt(v.amount, true), unit: unit(variable), low: fmt(v.low, true), high: fmt(v.high, true) })
      : t("blendTest.interval", { low: fmt(v.low), high: fmt(v.high) });
    td.append(cell("small", range));
    if (model) td.append(document.createElement("br"), cell("small", t("blendTest.vsModel", { model }), "model"));
    return td;
  };
  const head = document.createElement("tr");
  let body;
  const shown = variables.includes(blendView.variable) ? [blendView.variable] : variables;
  if (window.matchMedia("(max-width: 700px)").matches) {
    // phones: a row per lead day (two columns always fit)
    head.append(cell("th", t("control.lead")), cell("th", t("blendTest.verdict")));
    body = shown.flatMap((variable) => {
      const group = document.createElement("tr");
      group.className = "group";
      const name = cell("th", t(`variable.${variable}`));
      name.colSpan = 2;
      group.append(name);
      return [group, ...leads.map((lead) => {
        const tr = document.createElement("tr");
        tr.append(cell("th", `D+${lead}`), verdictCell(variable, lead));
        return tr;
      })];
    });
  } else {
    head.append(cell("th", t("blendTest.variable")), ...leads.map((d) => cell("th", `D+${d}`)));
    body = shown.map((variable) => {
      const tr = document.createElement("tr");
      tr.append(cell("th", t(`variable.${variable}`)), ...leads.map((lead) => verdictCell(variable, lead)));
      return tr;
    });
  }
  document.getElementById(id).replaceChildren(head, ...body);
}

const signedPct = (x) => (x == null ? "–" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(Math.round(x * 100))}`);

/** Our forecast vs every single model used everywhere, at the page's variable. */
function renderSingleModels(doc, variable, leads, unit, modelName) {
  const block = document.getElementById("blend-test-models-block");
  const data = singleModelVerdicts(doc, variable);
  block.hidden = data.length === 0;
  if (block.hidden) return;
  document.getElementById("blend-test-models-title").textContent =
    t("blendTest.modelsTitle", { variable: t(`variable.${variable}`) });
  const most = Math.max(...data.flatMap((m) => Object.values(m.cells).map((c) => c.days)));
  let few = false;
  const head = document.createElement("tr");
  head.append(cell("th", t("blendTest.model")), ...leads.map((d) => cell("th", `D+${d}`)));
  const body = data.map((m) => {
    const tr = document.createElement("tr");
    if (m.model === HOME_MODEL) tr.className = "home";
    tr.append(cell("th", modelName(m.model)));
    for (const lead of leads) {
      const c = m.cells[lead];
      if (!c) {
        tr.append(cell("td", "–"));
        continue;
      }
      const short = c.days < 0.75 * most;
      few ||= short;
      const td = cell("td", null, `verdict ${c.verdict}`);
      td.append(
        cell("strong", `${MARK[c.verdict]} ${signedPct(c.pct)}${short ? "*" : ""}`),
        document.createElement("br"),
        cell("small", `${signedPct(c.pctLow)}…${signedPct(c.pctHigh)}`),
      );
      const v = c.verdict === "better"
        ? { verdict: "better", amount: -c.diff, low: -c.high, high: -c.low }
        : { verdict: c.verdict, amount: c.diff, low: c.low, high: c.high };
      td.dataset.tip = t("blendTest.modelTip", {
        verdict: verdictText(v, unit(variable), true, modelName(m.model)), ours: fmt(c.maeCombined),
        theirs: fmt(c.mae), model: modelName(m.model), unit: unit(variable), days: c.days,
      });
      td.tabIndex = 0;
      tr.append(td);
    }
    return tr;
  });
  document.getElementById("blend-test-models").replaceChildren(head, ...body);
  document.getElementById("blend-test-models-note").textContent = few ? t("blendTest.fewDays") : "";
}

/** The blend test's own variable switch (temperature, wind, precipitation): never the ranking's. */
function renderBlendSwitch(verdicts, onChange) {
  const present = BLEND_TEST_VARIABLES.filter((variable) => verdicts.some((v) => v.variable === variable));
  if (!present.includes(blendView.variable)) blendView.variable = present[0];
  const group = document.getElementById("blend-test-variable");
  group.replaceChildren(...present.map((variable) => {
    const button = cell("button", t(`blendTest.short.${variable}`));
    button.type = "button";
    button.setAttribute("aria-pressed", String(variable === blendView.variable));
    button.addEventListener("click", () => {
      if (variable === blendView.variable) return;
      blendView.variable = variable;
      blendView.onChange?.();
      onChange();
    });
    return button;
  }));
}

async function renderBlendTest(names) {
  const section = document.getElementById("blend-test-section");
  const doc = await blendTestDoc;
  const czRows = blendTestRows(doc, "cz");
  const verdicts = blendVerdicts(czRows);
  section.hidden = verdicts.length === 0;
  if (section.hidden) return;
  const unit = (variable) => doc.units?.[variable] ?? "";
  const modelName = (m) => (m == null ? "–" : (names[m] ?? doc.models?.[m] ?? m));
  const leads = [...new Set(verdicts.map((v) => v.lead_day))].sort((a, b) => a - b);
  const language = document.documentElement.lang;
  document.getElementById("blend-test-scope").textContent = [
    t("blendTest.scopeCz"),
    doc.test_days && doc.from && doc.to
      ? t("blendTest.scopeDays", { days: dayCount(doc.test_days, t), range: formatRange(doc.from, doc.to, language) })
      : null,
    leads.length > 1 ? t("blendTest.scopeLeads", { first: leads[0], last: leads.at(-1) }) : null,
  ].filter(Boolean).join(" · ");
  // the section's own variable (switch above everything in it): tables, okres counts, chart, per-model table
  renderBlendSwitch(verdicts, () => renderBlendTest(names));
  // headline: one model for the whole of Czechia (files before it: the okres table only)
  const czVerdicts = blendVerdicts(czRows, "cz");
  document.getElementById("blend-test-cz").hidden = czVerdicts.length === 0;
  if (czVerdicts.length) {
    verdictTable("blend-test-table", czVerdicts, leads, unit, modelName, "cz");
    const picks = new Map();
    for (const v of czVerdicts) if (v.best) picks.set(v.best, (picks.get(v.best) ?? 0) + 1);
    document.getElementById("blend-test-cz-note").textContent = t("blendTest.czNote", {
      models: [...picks].sort((a, b) => b[1] - a[1]).map(([m]) => modelName(m)).join(", "),
    });
  }
  verdictTable("blend-test-okres-table", verdicts, leads, unit, modelName, "okres");
  const variable = blendView.variable;
  const counts = leads
    .map((lead) => ({ lead, ...okresVerdictCounts(doc, variable, lead) }))
    .filter((c) => c.better + c.same + c.worse);
  document.getElementById("blend-test-okres").textContent = counts.length
    ? t("blendTest.okresyAll", {
      variable: t(`variable.${variable}`),
      list: counts.map((c) => t("blendTest.okresyLead", c)).join("; "),
    })
    : "";
  // MAE by lead day of the section's variable: ours, one model, the best per okres, ...
  const lines = blendTestLines(czRows, variable);
  const present = BLEND_TEST_SERIES.filter((s) => lines.some((r) => r.series === s));
  const label = (s) => t(`blendTest.series.${s}`);
  const chart = document.getElementById("blend-test-chart");
  chart.replaceChildren(
    cell("h3", t("blendTest.chartTitle", { variable: t(`variable.${variable}`) })),
    Plot.plot({
      width: Math.max(280, Math.min(480, chart.clientWidth || 400)),
      height: 260,
      marginLeft: 45,
      x: { label: t("control.lead"), ticks: leads, tickFormat: (d) => `D+${d}` },
      y: { label: `MAE (${unit(variable)})`, grid: true, tickFormat: tickNumber },
      color: { domain: present.map(label), range: present.map(seriesColor), legend: true },
      marks: SERIES_STYLE.filter(([series]) => present.includes(series)).map(
        ([series, strokeWidth, strokeDasharray]) => Plot.lineY(lines.filter((r) => r.series === series), {
          x: "lead_day", y: "mae", stroke: (r) => label(r.series), marker: "circle", tip: true, strokeWidth,
          title: (r) => tipText(label(r.series), `D+${r.lead_day}`, `MAE ${fmt(r.mae)} ${unit(variable)}`),
          strokeDasharray,
        }),
      ),
    }),
  );
  document.getElementById("blend-test-basis").textContent = t("blendTest.basis", {
    days: doc.test_days, from: doc.from, to: doc.to, warmup: doc.warm_up_days, min: doc.min_training_days,
  });
  renderSingleModels(doc, variable, leads, unit, modelName);
}

// --- run-based errors by lead hour (leads.json; hidden until it exists) -------------
const leadsDoc = getJson("data/scores/leads.json");
const HIGHLIGHT = 3; // the best models over the lead hours get bold lines
const leadHoursView = { runHour: "all" };

async function renderLeadHours(view, names, colors) {
  const chosen = isBand(view.leadDay) ? view.leadDay.slice(1).split("-").map(Number) : null;
  const section = document.getElementById("lead-hours-section");
  const doc = await leadsDoc;
  const variable = leadHourVariable(view.variable);
  const runHours = leadHourRunHours(doc);
  if (!runHours.includes(leadHoursView.runHour)) leadHoursView.runHour = "all";
  const data = leadHourLines(doc, variable, leadHoursView.runHour);
  const basis = leadHourBasis(doc);
  section.hidden = data.length === 0 || basis == null;
  if (section.hidden) return;
  const select = document.getElementById("lead-hours-run");
  fillSelect("lead-hours-run", runHours.map((h) => [h, h === "all" ? t("compare.leadHoursAllRuns") : `${h} UTC`]),
    leadHoursView.runHour);
  select.onchange = (event) => {
    leadHoursView.runHour = event.target.value;
    renderLeadHours(view, names, colors);
  };
  const models = [...new Set(data.map((r) => r.model))];
  const label = (m) => doc.models?.[m]?.name ?? names[m] ?? m;
  const ranking = leadHourRanking(data);
  const best = new Set(ranking.slice(0, HIGHLIGHT).map((r) => r.model));
  const aladin = models.filter(isAladin);
  const lastLead = Math.max(...data.map((r) => r.lead_h));
  const hidden = unpublishedHours(doc);
  const parts = [
    t(`leadHours.${variable}`),
    t("compare.leadHoursBasis", { ...basis, runs: count(basis.runs), days: basis.days.toLocaleString(LANGUAGE) }),
    basis.stations ? t("compare.leadHoursStations", basis) : null,
  ];
  if (ranking.length > 1) {
    parts.push(t("compare.leadHoursBest", { models: ranking.slice(0, HIGHLIGHT).map((r) => label(r.model)).join(", ") }));
  }
  document.getElementById("lead-hours-basis").textContent = parts.filter(Boolean).join(" · ");
  const last = Math.max(lastLead, 72);
  const chartWidth = width();
  // fewer hour ticks on a narrow screen: "H+108" needs about 40 px
  const room = (chartWidth - 70) / 40;
  const ticks = [
    [1, 6, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120], [1, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120],
    [1, 12, 24, 48, 72, 96, 120], [1, 24, 48, 72, 96, 120], [24, 48, 72, 96, 120], [24, 72, 120],
  ].map((list) => list.filter((h) => h <= last)).find((list, i, all) => list.length <= room || i === all.length - 1);
  // bold: the best few; dashed: ALADIN; the others thin and pale
  const lines = (subset, width, opacity, dashed) =>
    Plot.lineY(subset, {
      x: "lead_h", y: "mae", z: "model", stroke: (r) => label(r.model), strokeWidth: width, strokeOpacity: opacity,
      strokeDasharray: dashed ? "5,3" : null,
      tip: true,
      title: (r) => tipText(label(r.model), `H+${r.lead_h}`, `MAE ${fmt(r.mae)}`,
        t("compare.leadHoursTip", { runs: count(r.runs), n: count(r.n) })),
    });
  const pick = (bold, dashed) => data.filter((r) => best.has(r.model) === bold && isAladin(r.model) === dashed);
  const marks = [];
  if (aladin.length) {
    marks.push(Plot.rectX([{ x1: 0, x2: hidden }], { x1: "x1", x2: "x2", fill: "var(--line)", fillOpacity: 0.6 }));
  }
  // the band's words only where the band is wide enough for them (on a phone it is a few
  // pixels, and the text would sit on the y axis; the note below the chart says it too)
  if (aladin.length && (hidden / last) * (chartWidth - 70) >= 14) {
    marks.push(
      Plot.text([{ x: hidden / 2 }], {
        x: "x", frameAnchor: "top", dy: 6, rotate: -90, textAnchor: "end",
        text: () => t("compare.leadHoursUnpublished"), fontSize: 10, fill: "var(--muted-strong)",
      }),
    );
  }
  if (chosen) {
    // the band chosen above: the ranking pools these hours
    marks.push(Plot.rectX([{ x1: chosen[0] - 0.5, x2: chosen[1] + 0.5 }], {
      x1: "x1", x2: "x2", fill: "#1f78b4", fillOpacity: 0.08,
    }));
  }
  marks.push(
    Plot.ruleX([1, 6, 12, 24, 48, 72], { stroke: "var(--line)", strokeDasharray: "2,3" }),
    lines(pick(false, false), 1.2, 0.45, false),
    lines(pick(false, true), 2, 0.9, true),
    lines(pick(true, false), 2.8, 1, false),
    lines(pick(true, true), 2.8, 1, true),
  );
  document.getElementById("lead-hours").replaceChildren(
    Plot.plot({
      width: chartWidth,
      height: 380,
      marginLeft: 50,
      x: { label: t("compare.leadHoursAxis"), domain: [0, last], ticks, tickFormat: (h) => `H+${h}` },
      y: { label: "MAE", grid: true, zero: true, tickFormat: tickNumber },
      color: {
        domain: models.map(label),
        range: models.map((m) => colors[m] ?? "#888888"),
        legend: true,
      },
      marks,
    }),
  );
}

// --- event skill for farmers (farm.json; hidden until it exists) --------------------
const farmDoc = getJson("data/scores/farm.json");
const farmView = { key: null };

function farmEventLabel(choice, doc) {
  const unit = doc.events?.[choice.event];
  // "0,5" and "−2" in Czech
  const value = Number(choice.threshold).toLocaleString(LANGUAGE).replace("-", "−");
  return t(`farm.event.${choice.event}`, { value, op: unit?.op === "<=" ? "≤" : "≥" });
}

function farmTip(row, choice, label) {
  const p = plain(row);
  return [
    `${label(row.model)}, ${binLabel(row.bin)}`,
    t("farm.tipCaught", { caught: count(p.caught), events: count(p.events), what: t(`farm.noun.${choice.event}`) }),
    t("farm.tipFalse", { falseWarnings: count(p.falseWarnings), warnings: count(p.warnings) }),
    `POD ${score(row.pod)} · FAR ${score(row.far)} · CSI ${score(row.csi)} · ETS ${score(row.ets)} · ` +
      `${t("farm.bias")} ${score(row.bias)}`,
    t(`farm.units.${choice.event}`, { units: count(row.units), runs: count(row.runs), stations: count(row.stations) }),
  ].join("\n");
}

async function renderFarm(names) {
  const section = document.getElementById("farm-section");
  const doc = await farmDoc;
  const choices = farmChoices(doc);
  section.hidden = choices.length === 0;
  if (section.hidden) return;
  if (!choices.some((c) => c.key === farmView.key)) farmView.key = choices[0].key;
  const choice = choices.find((c) => c.key === farmView.key);
  fillSelect("farm-event", choices.map((c) => [c.key, farmEventLabel(c, doc)]), farmView.key);
  document.getElementById("farm-event").onchange = (event) => {
    farmView.key = event.target.value;
    renderFarm(names);
  };
  const label = (m) => doc.models?.[m]?.name ?? names[m] ?? m;
  const first = (doc.first_run ?? "").slice(0, 10);
  const last = (doc.last_run ?? "").slice(0, 10);
  document.getElementById("farm-basis").textContent = t("farm.basis", {
    runs: count(doc.runs), stations: count(doc.stations), first, last,
  });
  const grid = farmGrid(doc, choice.event, choice.threshold);
  const table = document.getElementById("farm-table");
  const head = document.createElement("tr");
  head.append(cell("th", t("table.model")), ...grid.bins.map((b) => cell("th", binLabel(b), "num")));
  const body = grid.models.map((model) => {
    const tr = document.createElement("tr");
    tr.append(cell("th", label(model), "model"));
    grid.perBin.forEach((bin) => {
      const row = grid.cells.get(`${model}|${bin.bin}`);
      if (!row) {
        tr.append(cell("td", "", "num empty"));
        return;
      }
      const best = bin.best.includes(model);
      const td = cell("td", `${best ? "★ " : ""}${score(row.ets)}`, `num${best ? " best" : ""}`);
      td.style.background = etsColor(row.ets);
      td.style.color = etsTextColor(row.ets);
      td.dataset.tip = farmTip(row, choice, label);
      td.tabIndex = 0;
      tr.append(td);
    });
    return tr;
  });
  const foot = document.createElement("tr");
  foot.className = "events";
  foot.append(cell("th", t(`farm.observed.${choice.event}`)));
  for (const bin of grid.perBin) {
    foot.append(cell("td", t("farm.eventsOf", { events: count(bin.events), units: count(bin.units) }) +
      (bin.small ? " ⚠" : ""), `num${bin.small ? " small" : ""}`));
  }
  table.replaceChildren(head, ...body, foot);
  // one sentence in plain words: the best model where most events were observed
  const busiest = [...grid.perBin].filter((b) => b.best.length).sort((a, b) => b.events - a.events)[0];
  const reading = document.getElementById("farm-reading");
  if (busiest) {
    const row = grid.cells.get(`${busiest.best[0]}|${busiest.bin}`);
    const p = plain(row);
    reading.textContent = t("farm.reading", {
      bin: binLabel(busiest.bin), model: label(row.model), caught: count(p.caught), events: count(p.events),
      what: t(`farm.noun.${choice.event}`), falseWarnings: count(p.falseWarnings), warnings: count(p.warnings),
    });
  } else {
    reading.textContent = t("farm.noEvents");
  }
  const small = grid.perBin.filter((b) => b.small).map((b) => binLabel(b.bin));
  document.getElementById("farm-small").textContent = small.length
    ? t("farm.small", { n: doc.small_sample ?? 20, bins: small.join(", ") })
    : "";
}

function renderBias(rows, view, names, colors) {
  const section = document.getElementById("elevation-section");
  section.hidden = view.region !== "cz" || isBand(view.leadDay);
  if (section.hidden) return;
  const target = document.getElementById("bias");
  const data = biasByElevation(rows, view.leadDay);
  if (data.length === 0) {
    target.replaceChildren(cell("p", t("compare.empty")));
    return;
  }
  const models = [...new Set(data.map((r) => r.model))];
  const elevations = ["lowland", "upland", "mountain"];
  const chartWidth = width();
  // the longest model names need about 190 px at the axis' font; the rest is for the bars
  const marginLeft = chartWidth < 500 ? 192 : 210;
  target.replaceChildren(
    Plot.plot({
      width: chartWidth,
      marginLeft,
      marginTop: 24,
      marginRight: 12,
      x: { label: "Bias", grid: true, tickFormat: tickNumber },
      y: { label: null, tickFormat: (m) => names[m] ?? m },
      // the elevation names as titles above each group: at the side they took the bars' room
      fy: { label: null, domain: elevations, axis: null, padding: 0.12 },
      color: { domain: models, range: models.map((m) => colors[m] ?? "#888888") },
      marks: [
        Plot.text(elevations, {
          fy: (e) => e, text: (e) => t(`elevation.${e}`), frameAnchor: "top-left", dy: -18, dx: 4 - marginLeft,
          fontWeight: "bold", fontSize: 12,
        }),
        Plot.barX(data, {
          x: "bias", y: "model", fy: "elevation", fill: "model", tip: true,
          title: (r) => tipText(names[r.model] ?? r.model, t(`elevation.${r.elevation}`), `Bias ${fmt(r.bias, true)}`),
        }),
        Plot.ruleX([0]),
      ],
    }),
  );
}

/** The band set switch (temperature and wind): every lead hour of the hourly models, or every model at H+6, H+12, … */
function renderBandSet(view, sets, shown, rows, onChange) {
  const block = document.getElementById("band-set-block");
  const note = document.getElementById("band-set-note");
  block.hidden = !isBand(view.leadDay) || sets.length < 2;
  note.hidden = !isBand(view.leadDay) || sets.length === 0;
  if (note.hidden) return;
  const models = new Set(rows.filter((r) => r.lead_day === view.leadDay).map((r) => r.model)).size;
  const key = sets.length < 2 ? "only" : shown;
  note.textContent = t(`compare.bandSetNote.${key}`, { n: models, band: leadLabel(view.leadDay) });
  if (block.hidden) return;
  fillSegmented("band-set", sets.map((set) => [set, t(`compare.bandSet.${set}`)]), shown, (set) => {
    view.set = set;
    onChange();
  });
}

async function main() {
  const meta = await getJson("data/scores/meta.json");
  scoresMeta = meta;
  document.getElementById("status").textContent = statusText(meta, t);
  const names = { ...meta?.models, blend: t("model.blend") };
  let colors = modelColors(names);
  const view = readView();
  // only periods with scored days: an empty one is never offered nor kept from a link
  const windows = availableWindows(meta?.windows);
  view.window = pickWindow(view.window, windows);
  const variables = availableVariables(meta);
  const language = document.documentElement.lang;
  blendView.variable = view.blendVariable;
  blendView.onChange = () => {
    view.blendVariable = blendView.variable;
    writeView(view);
  };
  renderBlendTest(names).then(() => (view.blendVariable = blendView.variable));
  // bands of hours ahead: offered once the files exist; the page opens at the band the
  // data suggests (enough days, `default_band`) unless the link names a lead
  const bands90 = await loadBands("90d");
  const bandList = bandsIn(bands90.rows);
  if (!view.leadGiven) view.leadDay = defaultLead(bands90.doc);
  if (isBand(view.leadDay) && !bandList.includes(view.leadDay)) view.leadDay = 1;
  let leadDays = LEAD_DAYS;

  /** The D+N view: score files of the variable, okresy on the map. */
  async function dayData() {
    view.variable = dayVariable(view.variable, variables);
    view.window = pickWindow(view.window, windows);
    const level = levelOf(view.region);
    const [rows, okresRows, networkRows] = await Promise.all([
      load(view, level), load(view, "okres"), view.region === "cz" ? load(view, "network") : [],
    ]);
    leadDays = availableLeadDays(rows);
    if (!leadDays.includes(view.leadDay)) view.leadDay = leadDays[0];
    fillSelect("variable", variables.map((v) => [v, t(`variable.${v}`)]), view.variable);
    fillSelect("window", windows.map((w) => [w, windowLabel(w, meta?.windows, t, language)]), view.window);
    return { rows, areaRows: okresRows, networkRows };
  }

  /** The band view: Czechia, station kinds and kraje of one fair set; kraje on the map. */
  async function bandData() {
    const window_ = bandWindow(view.window);
    const [cz, kraj, other] = await Promise.all([
      loadBands(window_), loadBands(window_, true), loadBands(window_ === "90d" ? "all" : "90d"),
    ]);
    const present = BAND_VARIABLES.filter((v) => cz.rows.some((r) => r.variable === v));
    const variable = present.includes(bandVariable(view.variable)) ? bandVariable(view.variable) : present[0];
    const sets = bandSets(cz.rows, variable);
    const set = sets.includes(view.set) ? view.set : sets[0];
    const pick = (rows, level) => rows.filter((r) => r.level === level && r.variable === variable && r.set === set);
    const czRows = pick(cz.rows, "cz");
    const krajRows = pick(kraj.rows, "kraj");
    fillSelect("variable", present.map((v) => [v, t(`bandVariable.${v}`)]), variable);
    // the band windows with their real days (the seasons are for D+N only)
    const spans = Object.fromEntries([[window_, cz.doc], [bandWindow(other.doc?.window), other.doc]]
      .filter(([, doc]) => doc?.first_day)
      .map(([w, doc]) => [w, { from: doc.first_day, to: doc.last_day }]));
    const offered = BAND_WINDOWS.filter((w) => w === window_ || spans[w]);
    fillSelect("window", offered.map((w) => [w, windowLabel(w, spans, t, language)]), window_);
    const rows = view.region === "cz" ? czRows : krajRows;
    return {
      rows, areaRows: krajRows, networkRows: pick(cz.rows, "network"), sets, set,
      setRows: view.region === "cz" ? czRows : krajRows, preliminaryDays: cz.doc?.preliminary_days ?? 30,
    };
  }

  async function render() {
    const band = isBand(view.leadDay);
    if (band) view.region = krajOf(view.region);
    setOkresChoice(!band);
    const data = band ? await bandData() : await dayData();
    const { rows, areaRows, networkRows } = data;
    fillLead(bandList, leadDays, view.leadDay);
    document.getElementById("region").value = view.region;
    document.getElementById("ranking-title").textContent = t("compare.rankingIn", {
      region: view.region === "cz"
        ? t("region.cz")
        : displayName(regionList([...rows, ...areaRows]).find((r) => r.code === view.region)?.name ?? view.region),
    });
    renderSummary(rows, view, names, colors);
    // what a band result rests on, and which models (fair set) it compares
    const basisNote = document.getElementById("band-basis");
    const basis = band ? bandBasis(rows, view.leadDay, view.region, data.preliminaryDays) : null;
    basisNote.hidden = !band;
    basisNote.textContent = !band
      ? ""
      : basis
        ? t("compare.bandBasis", { ...basis, band: leadLabel(view.leadDay) }) +
          (basis.preliminary ? ` ${t("compare.preliminary", { days: basis.days })}` : "")
        : t("compare.bandFewStations");
    renderBandSet(view, band ? data.sets : [], band ? data.set : "hourly", band ? data.setRows : [], render);
    // the station switch (Czechia): the table and the two charts below it
    const stations = stationChoice(view, networkRows);
    const [rankRows, rankRegion] = stations.shown === "all" ? [rows, view.region] : [networkRows, stations.shown];
    renderStations(view, stations, networkRows, render);
    renderTable(rankRows, view, names, rankRegion, render);
    renderIntervals(rankRows, view, names, colors, rankRegion);
    renderByLead(rankRows, view, names, colors, rankRegion);
    renderLeadHours(view, names, colors);
    renderBias(view.region === "cz" && !band ? await load(view, "elevation") : [], view, names, colors);
    document.getElementById("map-note").textContent = t(band ? "compare.mapNoteBand" : "compare.mapNote");
    const bandNote = document.getElementById("map-band-note");
    bandNote.hidden = !band;
    bandNote.textContent = band ? t("compare.mapBandNote") : "";
    if (map.getLayer("fill")) paintMap(areaRows, view, colors, names);
    writeView(view);
  }

  // the region lists come from the D+N files (a band variable such as gusts has none)
  const listView = { ...view, variable: dayVariable(view.variable, variables) };
  const [kraje, okresy] = await Promise.all([load(listView, "kraj"), load(listView, "okres")]);
  const known = new Set(["cz", ...regionList(kraje).map((r) => r.code), ...regionList(okresy).map((r) => r.code)]);
  if (!known.has(view.region)) view.region = "cz";
  fillRegions(regionList(kraje), regionList(okresy), view.region);
  for (const { code, name } of [...regionList(kraje), ...regionList(okresy)]) regionNames.set(code, name);
  for (const [id, key, parse] of [
    ["region", "region", String],
    ["variable", "variable", String],
    ["lead", "leadDay", parseLead],
    ["window", "window", String],
  ]) {
    document.getElementById(id).addEventListener("change", (event) => {
      view[key] = parse(event.target.value);
      render();
    });
  }
  // Back/Forward and a link pasted on the open page: that view, its hash normalised in place
  address = hashHistory(() => {
    const next = readView();
    next.window = pickWindow(next.window, windows);
    if (!next.leadGiven) next.leadDay = defaultLead(bands90.doc);
    if (isBand(next.leadDay) && !bandList.includes(next.leadDay)) next.leadDay = 1;
    if (!known.has(next.region)) next.region = "cz";
    Object.assign(view, next);
    written = null;
    if (blendView.variable !== view.blendVariable) {
      blendView.variable = view.blendVariable;
      renderBlendTest(names).then(() => (view.blendVariable = blendView.variable));
    }
    render();
  });
  // the charts and the map redraw in the colours of the new theme
  onThemeChange(() => {
    colors = modelColors(names);
    paintMapTheme();
    render();
    renderBlendTest(names);
  });
  await render();
  renderFarm(names);
  await mapLoaded;
  addLayers((code) => {
    view.region = view.region === code ? "cz" : code;
    render();
  });
  render();
}

main();
