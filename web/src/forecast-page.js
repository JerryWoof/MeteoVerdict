import * as Plot from "@observablehq/plot";

import "./style.css";

import { modelColors, records } from "./data.js";
import {
  VARIABLES, bestModel, combine, dailySummary, forecastUrl, parseForecast, weightTable,
  weightedModels, weightsAt,
} from "./forecast.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";

const t = setUpLanguage();
const TIME_ZONE = "Europe/Prague";
const UNITS = { temperature_2m: "°C", precipitation: "mm", wind_speed_10m: "m/s" };

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function cell(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

// axis labels in the page's language and Prague time: the day at midnight, else the hour
const pragueHour = (date) =>
  Number.parseInt(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: TIME_ZONE }).format(date),
    10,
  );

function timeTick(date) {
  const language = document.documentElement.lang;
  const hour = pragueHour(date);
  if (hour !== 0) return `${hour}:00`;
  return new Intl.DateTimeFormat(language, { weekday: "short", day: "numeric", month: "numeric", timeZone: TIME_ZONE }).format(date);
}

const fmt = (v, digits = 1) => (v == null ? "–" : v.toFixed(digits));

function renderDays(days) {
  const table = document.getElementById("days");
  const head = document.createElement("tr");
  for (const key of ["day", "tmin", "tmax", "precipitation", "wind"]) {
    head.append(cell("th", t(`forecast.col.${key}`), key === "day" ? "" : "num"));
  }
  const dateFormat = new Intl.DateTimeFormat(document.documentElement.lang, {
    weekday: "short", day: "numeric", month: "numeric", timeZone: "UTC",
  });
  const rows = days.map((d) => {
    const tr = document.createElement("tr");
    tr.append(
      cell("td", dateFormat.format(Date.parse(`${d.day}T12:00Z`))),
      cell("td", fmt(d.tmin), "num"),
      cell("td", fmt(d.tmax), "num"),
      cell("td", fmt(d.precipitation), "num"),
      cell("td", fmt(d.wind), "num"),
    );
    return tr;
  });
  table.replaceChildren(head, ...rows);
}

function chart(forecast, combined, best, variable, colors, names) {
  const rows = [];
  for (const [model, values] of Object.entries(forecast.values[variable])) {
    values.forEach((v, i) => {
      if (v != null) rows.push({ time: new Date(forecast.times[i]), value: v, model });
    });
  }
  const ours = combined
    .map((v, i) => ({ time: new Date(forecast.times[i]), value: v }))
    .filter((r) => r.value != null);
  const bestRows = rows.filter((r) => r.model === best);
  const others = rows.filter((r) => r.model !== best);
  const figure = document.createElement("figure");
  figure.append(cell("figcaption", `${t(`forecast.${variable}`)} (${UNITS[variable]})`));
  const step = variable === "precipitation";
  figure.append(
    Plot.plot({
      width: Math.min(900, document.body.clientWidth - 32),
      height: 220,
      marginLeft: 40,
      x: {
        label: null,
        type: "time",
        ticks: forecast.times.map((time) => new Date(time)).filter((d) => pragueHour(d) % 12 === 0),
        tickFormat: timeTick,
      },
      y: { label: null, grid: true, zero: step },
      marks: [
        Plot.lineY(others, { x: "time", y: "value", z: "model", stroke: "#b7bec4", strokeWidth: 0.8, curve: step ? "step-before" : "linear" }),
        Plot.lineY(bestRows, { x: "time", y: "value", stroke: colors[best] ?? "#1f78b4", strokeWidth: 1.5, curve: step ? "step-before" : "linear" }),
        Plot.lineY(ours, { x: "time", y: "value", stroke: "#1d2329", strokeWidth: 2.5, curve: step ? "step-before" : "linear", tip: true }),
        Plot.ruleX([new Date()], { stroke: "#c0392b", strokeDasharray: "3,3" }),
      ],
    }),
  );
  const legend = document.createElement("p");
  legend.className = "note";
  legend.textContent = t("forecast.legend", { best: names[best] ?? best ?? "–" });
  figure.append(legend);
  return figure;
}

function renderWeights(table, names) {
  const target = document.getElementById("weights");
  const head = document.createElement("tr");
  head.append(cell("th", t("forecast.variable")), cell("th", t("forecast.top")));
  const rows = VARIABLES.map((variable) => {
    const tr = document.createElement("tr");
    const top = weightsAt(table, variable, 1)
      .slice()
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 4)
      .map((r) => `${names[r.model] ?? r.model} ${Math.round(r.weight * 100)} %`);
    tr.append(cell("td", t(`forecast.${variable}`)), cell("td", top.join(" · ") || "–"));
    return tr;
  });
  target.replaceChildren(head, ...rows);
}

async function show(point, names, colors) {
  const message = document.getElementById("message");
  document.getElementById("title").textContent = t("forecast.titleFor", { okres: point.name });
  for (const id of ["days", "charts", "weights"]) document.getElementById(id).replaceChildren();
  if (!point.weights) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  message.textContent = t("forecast.loading");
  const table = weightTable(await getJson(`data/scores/forecast/${point.code}.json`));
  const models = weightedModels(table);
  if (models.length === 0) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  const doc = await getJson(forecastUrl(point, models));
  if (!doc?.hourly) {
    message.textContent = t("forecast.unavailable");
    return;
  }
  const forecast = parseForecast(doc, models);
  const now = Date.now();
  const combined = Object.fromEntries(VARIABLES.map((v) => [v, combine(forecast, table, v, now)]));
  renderDays(dailySummary(forecast.times, combined, TIME_ZONE));
  document.getElementById("charts").replaceChildren(
    ...VARIABLES.map((v) => chart(forecast, combined[v], bestModel(table, v, 1), v, colors, names)),
  );
  renderWeights(table, names);
  message.textContent = "";
}

async function main() {
  const [meta, index] = await Promise.all([
    getJson("data/scores/meta.json"),
    getJson("data/scores/forecast/okresy.json"),
  ]);
  document.getElementById("status").textContent = statusText(meta, t);
  const names = { ...meta?.models };
  const colors = modelColors(names);
  const points = records(index).sort((a, b) => a.name.localeCompare(b.name, "cs"));
  if (points.length === 0) {
    document.getElementById("message").textContent = t("forecast.noWeights");
    return;
  }
  const wanted = window.location.hash.slice(1);
  const current = points.find((p) => p.code === wanted) ?? points.find((p) => p.code === "CZ0100") ?? points[0];
  const select = document.getElementById("okres");
  select.replaceChildren(
    ...points.map((p) => {
      const option = document.createElement("option");
      option.value = p.code;
      option.textContent = p.name;
      option.selected = p.code === current.code;
      return option;
    }),
  );
  select.addEventListener("change", () => {
    const point = points.find((p) => p.code === select.value);
    window.history.replaceState(null, "", `#${point.code}`);
    show(point, names, colors);
  });
  window.history.replaceState(null, "", `#${current.code}`);
  await show(current, names, colors);
}

main();
