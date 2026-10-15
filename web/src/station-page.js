// The station page: every element one ČHMÚ station measures, with its history
// (site/data/station/<WSI>.json from `mvd station-pages`).
import * as Plot from "@observablehq/plot";

import "./style.css";

import { setUpLanguage } from "./i18n.js";
import {
  VIEWS, defaultElement, elementLabel, elementName, elementOrder, unitOf, formatNumber, isTotal, latestValues,
  parseStationHash, searchStations, seriesPoints, spanLabel, stepTime, viewsWith,
} from "./station.js";
import { displayName } from "./tv.js";

const t = setUpLanguage();
const language = document.documentElement.lang;
const DATA = "data/scores/station";
const DEFAULT_STATION = "0-20000-0-11520"; // Praha-Libuš
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
  dateStyle: "medium", timeStyle: "short",
});

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

async function show() {
  const hash = parseStationHash(window.location.hash);
  const id = hash.id ?? (index.some((s) => s.id === DEFAULT_STATION) ? DEFAULT_STATION : index[0]?.id);
  if (!id) {
    $("message").textContent = t("station.pick");
    return;
  }
  if (doc?.station.id !== id) {
    $("message").textContent = t("station.loading");
    doc = await getJson(`${DATA}/${id}.json`);
    if (!doc) {
      $("message").textContent = t("station.notFound", { id });
      $("charts").replaceChildren();
      $("pick").hidden = true;
      return;
    }
    const name = doc.station.name ?? id;
    $("title").textContent = name;
    document.title = `MeteoVerdict: ${name}`;
    $("facts").textContent = facts(doc.station);
    $("status").textContent = t("station.updated", { time: DATE_TIME.format(new Date(doc.generated)) });
    renderElements();
  }
  const element = hash.element && doc.elements[hash.element] ? hash.element : defaultElement(doc);
  $("message").textContent = element ? "" : t("station.noData");
  fillElements(element);
  if (element) renderCharts(element);
}

$("element").addEventListener("change", (event) => {
  window.location.hash = `${doc.station.id}/${event.target.value}`;
});
window.addEventListener("hashchange", show);

getJson(`${DATA}/index.json`).then((loaded) => {
  index = loaded?.stations ?? [];
  fillSearch();
  show();
});
