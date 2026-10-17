// The station page: every element one ČHMÚ station measures, with its history
// (site/data/station/<WSI>.json from `mvd station-pages`).
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
import { displayName } from "./tv.js";

const t = setUpLanguage();
const language = document.documentElement.lang;
const DATA = "data/scores/station";
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
    if (hit) window.location.hash = hit.id;
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

// --- the station map ---------------------------------------------------------------------
let placed = []; // stations of the index with coordinates
const top = $("station-top");
const panel = $("map-panel");
const toggle = $("map-toggle");
let mapOpen = window.innerWidth > 700; // with a station shown; phones start with it folded

function describe(station) {
  const { kind, automatic } = classifyStation(station);
  const parts = [];
  if (station.elevation != null) parts.push(`${formatNumber(Math.round(station.elevation))} m`);
  parts.push(t(`map.one.${kind}`));
  // the manual kinds say "daily" already
  if (!automatic && !["precipitation", "climate_manual"].includes(kind)) parts.push(t("map.daily"));
  return parts.join(" · ");
}

const stationMap = createStationMap({
  container: $("station-map"),
  t,
  describe,
  onPick: (station) => {
    const measure = $("map-measure").value;
    const element = measure ? elementFor(station, measure) : null;
    window.location.hash = element ? `${station.id}/${element}` : station.id;
  },
});

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

function renderLegend(shown) {
  const items = [];
  if ($("map-colour").value === "elevation") {
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
  $("map-colour").addEventListener("change", (event) => {
    stationMap.setColour(event.target.value);
    renderLegend(filterStations(placed, $("map-measure").value));
  });
  applyFilter();
}

/** Large map and no station (empty hash), or a station with the map compact beside it. */
function setMode(browsing) {
  top.classList.toggle("browse", browsing);
  toggle.hidden = browsing;
  $("map-all").hidden = browsing;
  $("map-hint").hidden = !browsing;
  $("note").hidden = browsing;
  panel.hidden = !browsing && !mapOpen;
  toggle.textContent = t(mapOpen ? "map.hide" : "map.show");
  toggle.setAttribute("aria-expanded", String(!panel.hidden));
}

toggle.addEventListener("click", () => {
  mapOpen = !mapOpen;
  setMode(false);
  if (mapOpen) stationMap.select(doc?.station.id ?? null, { animate: false });
});

function browse() {
  doc = null;
  setMode(true);
  $("title").textContent = t("map.heading");
  document.title = `MeteoVerdict: ${t("map.heading")}`;
  $("facts").textContent = index.length ? t("map.browse", { n: formatNumber(index.length) }) : "";
  $("message").textContent = index.length ? "" : t("station.pick");
  $("pick").hidden = true;
  $("charts").replaceChildren();
  $("elements").replaceChildren();
  $("elements-title").hidden = true;
  $("detail-title").hidden = true;
  diary.hide();
  $("search").value = "";
  stationMap.select(null);
  stationMap.fitAll();
}

// only the latest navigation renders: a slow station file must not overwrite a newer one
let showToken = 0;
async function show() {
  const token = ++showToken;
  const hash = parseStationHash(window.location.hash);
  const id = hash.id;
  if (!id) {
    browse();
    return;
  }
  const wasBrowsing = top.classList.contains("browse");
  setMode(false);
  if (doc?.station.id !== id) {
    stationMap.select(id, { animate: !wasBrowsing });
    $("search").value = index.find((s) => s.id === id)?.name ?? "";
    $("message").textContent = t("station.loading");
    const loaded = await getJson(`${DATA}/${id}.json`);
    if (token !== showToken) return;
    doc = loaded?.station ? { ...loaded, elements: loaded.elements ?? {} } : null;
    if (!doc) {
      $("title").textContent = id;
      document.title = "MeteoVerdict";
      $("facts").textContent = "";
      $("status").textContent = "";
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

getJson(`${DATA}/index.json`).then(async (loaded) => {
  index = loaded?.stations ?? [];
  if (loaded?.generated) $("status").textContent = updated(loaded.generated);
  // an index from before it carried coordinates: take them from the score map's table
  const table = index.some((s) => s.lat == null) ? await getJson("data/scores/stations.json") : null;
  placed = withCoordinates(index, table);
  fillSearch();
  fillMapTools();
  show();
});
