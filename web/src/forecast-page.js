import * as Plot from "@observablehq/plot";

import "./style.css";

import { modelColors, records } from "./data.js";
import {
  COMBINED, MAX_LEAD_DAY, VARIABLES, bestPerLeadDay, dailySummary, nightBands, weightTable, winnersByLeadDay,
} from "./forecast.js";
import { setUpLanguage } from "./i18n.js";
import { glyph } from "./icons.js";
import { asForecast, modelHorizon, modelPeriods, parseModels } from "./models.js";
import { fillPicker, issuedText } from "./picker.js";
import { statusText } from "./status.js";
import { dayLabel, parseOutlook, rowFor, sunFor, today } from "./tv.js";

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

// sunrise and sunset as on the forecast map: the glyphs with the local times
function sunCell(sun) {
  const td = document.createElement("td");
  if (!sun) {
    td.textContent = "–";
    return td;
  }
  const line = cell("span", null, "sun");
  line.append(glyph("sunrise", 13), cell("span", sun.sunrise), glyph("sunset", 13), cell("span", sun.sunset));
  line.title = t("tv.sun", { rise: sun.sunrise, set: sun.sunset });
  td.append(line);
  return td;
}

function renderDays(days, sunOf, gustOf) {
  const table = document.getElementById("days");
  const head = document.createElement("tr");
  // older outlook files have no sun times or gusts: then no column at all
  const withSun = days.some((d) => sunOf(d.day));
  const withGust = days.some((d) => gustOf(d.day)?.gust != null);
  const columns = ["day", "tmin", "tmax", "precipitation", "wind", ...(withGust ? ["gust"] : []), ...(withSun ? ["sun"] : [])];
  for (const key of columns) {
    head.append(cell("th", t(`forecast.col.${key}`), key === "day" || key === "sun" ? "" : "num"));
  }
  // "Today 10/12", "Tomorrow 10/13", "Wednesday 10/14", as on the forecast map
  const language = document.documentElement.lang;
  const dayText = (day) => {
    const label = dayLabel(day, today(Date.now()), language);
    return `${label.key ? t(label.key) : label.name} ${label.short}`;
  };
  const rows = days.map((d) => {
    const tr = document.createElement("tr");
    tr.append(
      cell("td", dayText(d.day)),
      cell("td", fmt(d.tmin), "num"),
      cell("td", fmt(d.tmax), "num"),
      cell("td", fmt(d.precipitation), "num"),
      cell("td", fmt(d.wind), "num"),
    );
    if (withGust) {
      // from outlook.json (the single runs, corrected): null beyond the newest run
      const gust = gustOf(d.day);
      const td = cell("td", fmt(gust?.gust), gust?.gust_warning ? "num gust-warning" : "num");
      if (gust?.gust_warning) td.title = t("tv.gustWarning");
      tr.append(td);
    }
    if (withSun) tr.append(sunCell(sunOf(d.day)));
    return tr;
  });
  table.replaceChildren(head, ...rows);
}

// `selected`: COMBINED (our forecast highlighted, with the best model per lead day) or a
// model id (that model's raw forecast highlighted, ours thin for reference)
// `issued`: when the forecast was made (ms): the lead days count from it, as in the outlook
function chart(forecast, combined, table, variable, colors, names, nights, selected, issued) {
  const single = selected !== COMBINED;
  const points = (values) => values
    .map((v, i) => ({ time: new Date(forecast.times[i]), value: v }))
    .filter((r) => r.value != null);
  const rows = [];
  for (const [model, values] of Object.entries(forecast.values[variable])) {
    if (single && model === selected) continue;
    values.forEach((v, i) => {
      if (v != null) rows.push({ time: new Date(forecast.times[i]), value: v, model });
    });
  }
  const ours = points(combined);
  const picked = single ? points(forecast.values[variable][selected] ?? []) : [];
  // the best model of each lead day, as segments coloured by model
  let segment = 0;
  let previous = null;
  const best = [];
  bestPerLeadDay(forecast, table, variable, issued).forEach(({ value, model }, i) => {
    if (value == null) return;
    if (model !== previous) {
      // repeat the boundary point so the segments join
      if (previous != null) best.push({ time: new Date(forecast.times[i]), value, model: previous, segment });
      segment += 1;
      previous = model;
    }
    best.push({ time: new Date(forecast.times[i]), value, model, segment });
  });
  const figure = document.createElement("figure");
  figure.append(cell("figcaption", `${t(`forecast.${variable}`)} (${UNITS[variable]})`));
  const step = variable === "precipitation";
  const curve = step ? "step-before" : "linear";
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
        // night, sunset to sunrise, behind everything; the full height of the chart
        Plot.rectX(nights, {
          x1: (n) => new Date(n.start), x2: (n) => new Date(n.end), fill: "#1d2329", fillOpacity: 0.06,
        }),
        Plot.lineY(rows, { x: "time", y: "value", z: "model", stroke: "#b7bec4", strokeWidth: 0.8, curve }),
        ...(single
          ? [
            Plot.lineY(ours, { x: "time", y: "value", stroke: "#1d2329", strokeWidth: 1, curve }),
            Plot.lineY(picked, {
              x: "time", y: "value", stroke: colors[selected] ?? "#1f78b4", strokeWidth: 2.5, curve, tip: true,
            }),
          ]
          : [
            Plot.lineY(best, {
              x: "time", y: "value", z: "segment", stroke: (r) => colors[r.model] ?? "#1f78b4", strokeWidth: 1.6, curve,
            }),
            Plot.lineY(ours, { x: "time", y: "value", stroke: "#1d2329", strokeWidth: 2.5, curve, tip: true }),
          ]),
        Plot.ruleX([new Date()], { stroke: "#c0392b", strokeDasharray: "3,3" }),
      ],
    }),
  );
  const winners = winnersByLeadDay(table, variable)
    .map(({ lead, model }) => `D+${lead}: ${names[model] ?? model ?? "–"}`)
    .join(" · ");
  const legend = document.createElement("p");
  legend.className = "note";
  const text = single
    ? t("forecast.legendModel", { model: names[selected] ?? selected })
    : t("forecast.legend", { best: winners || "–" });
  legend.textContent = text + (nights.length ? ` ${t("forecast.night")}` : "");
  figure.append(legend);
  return figure;
}

function renderWeights(table, names) {
  const target = document.getElementById("weights");
  const leads = Array.from({ length: MAX_LEAD_DAY }, (_, i) => i + 1);
  const head = document.createElement("tr");
  head.append(cell("th", t("forecast.variable")), ...leads.map((d) => cell("th", `D+${d}`)));
  const rows = VARIABLES.map((variable) => {
    const tr = document.createElement("tr");
    tr.append(cell("td", t(`forecast.${variable}`)));
    for (const lead of leads) {
      const td = document.createElement("td");
      const top = (table.get(`${variable}|${lead}`) ?? [])
        .slice()
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 3);
      for (const r of top) {
        const line = cell("div", `${names[r.model] ?? r.model} ${Math.round(r.weight * 100)}\u00a0%`);
        if (r.rank === 1) line.className = "winner";
        td.append(line);
      }
      if (top.length === 0) td.textContent = "–";
      tr.append(td);
    }
    return tr;
  });
  target.replaceChildren(head, ...rows);
}

// which forecast is shown: our combination on every page load (not remembered, not in
// the link, so a shared link always opens on the combination); kept while the okres changes
let selected = COMBINED;
// the okres on screen: {point, table, parsed, forecast, combined, periods, days, sunOf, gustOf}
let state = null;

const dayRow = (d) => ({ day: d.day, tmin: d.tmin, tmax: d.tmax, precipitation: d.precipitation, wind: d.wind });

// the day table, the charts and the notes for the selected forecast
function render(names, colors) {
  const { parsed, forecast, combined, table, days, sunOf, gustOf } = state;
  const single = selected !== COMBINED;
  const modelNote = document.getElementById("model-note");
  document.getElementById("combined-note").hidden = single;
  modelNote.hidden = !single;
  if (single) {
    const name = names[selected] ?? selected;
    // the outlook's rules on the model's own hours (models.js): a day it does not cover
    // whole is "–"
    const periods = modelPeriods(parsed, selected);
    const rows = days.map((d) => {
      const own = periods.get(`${d.day}|day`);
      return own ? { day: d.day, ...own } : { day: d.day, tmin: null, tmax: null, precipitation: null, wind: null, beyond: true };
    });
    const end = modelHorizon(parsed, selected);
    let note = t("forecast.modelNote", { model: name });
    if (end != null && rows.some((d) => d.beyond)) {
      const when = new Intl.DateTimeFormat(document.documentElement.lang, {
        weekday: "short", day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", timeZone: TIME_ZONE,
      }).format(end);
      note += ` ${t("forecast.modelHorizon", { end: when })}`;
    }
    modelNote.textContent = note;
    // the gusts come from our corrected outlook: not shown for a single model
    renderDays(rows.map(dayRow), sunOf, () => null);
  } else {
    modelNote.textContent = "";
    renderDays(days.map(dayRow), sunOf, gustOf);
  }
  const nights = nightBands(sunOf, forecast.times[0], forecast.times.at(-1), TIME_ZONE);
  const issued = Date.parse(parsed.generated ?? "") || Date.now();
  document.getElementById("charts").replaceChildren(
    ...VARIABLES.map((v) => chart(forecast, combined[v], table, v, colors, names, nights, selected, issued)),
  );
}

function pick(model, names, colors) {
  selected = model;
  if (state) render(names, colors);
}

// only the latest okres renders: a slow download must not overwrite a newer choice
let showToken = 0;
async function show(point, names, colors, outlook) {
  const token = ++showToken;
  const message = document.getElementById("message");
  const issued = document.getElementById("issued");
  document.getElementById("title").textContent = t("forecast.titleFor", { okres: point.name });
  state = null;
  for (const id of ["days", "charts", "weights"]) document.getElementById(id).replaceChildren();
  document.getElementById("model-note").hidden = true;
  document.getElementById("combined-note").hidden = false;
  issued.textContent = "";
  if (!point.weights) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  message.textContent = t("forecast.loading");
  // the weights (mvd aggregate) and every model's forecast with our combination (mvd
  // outlook): static files, no request to Open-Meteo
  const [weightsDoc, modelsDoc] = await Promise.all([
    getJson(`data/scores/forecast/${point.code}.json`),
    getJson(`data/scores/forecast/models/${point.code}.json`),
  ]);
  if (token !== showToken) return;
  const table = weightTable(weightsDoc);
  if (table.size === 0) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  const parsed = parseModels(modelsDoc);
  if (!parsed) {
    message.textContent = t("forecast.unavailable");
    return;
  }
  const forecast = asForecast(parsed, VARIABLES);
  const combined = Object.fromEntries(VARIABLES.map((v) => [v, parsed.combined[v] ?? parsed.times.map(() => null)]));
  const sunOf = (day) => sunFor(outlook, point.code, day);
  const gustOf = (day) => rowFor(outlook, point.code, day, "day");
  // the days of our forecast as on the forecast map (outlook.json); without them (an
  // older or missing file) from the combined hours
  const fromOutlook = outlook.days
    .map((day) => ({ ...rowFor(outlook, point.code, day, "day"), day }))
    .filter((d) => d.tmin != null);
  const days = fromOutlook.length ? fromOutlook : dailySummary(parsed.times, combined, TIME_ZONE);
  state = { point, table, parsed, forecast, combined, days, sunOf, gustOf };
  const when = issuedText(parsed.generated);
  issued.textContent = when ? t("forecast.issued", { time: when }) : "";
  selected = fillPicker(document.getElementById("model"), {
    table, names, available: new Set(Object.keys(parsed.models)), selected, t,
  });
  renderWeights(table, names);
  message.textContent = "";
  render(names, colors);
}

async function main() {
  const [meta, index, outlookDoc] = await Promise.all([
    getJson("data/scores/meta.json"),
    getJson("data/scores/forecast/okresy.json"),
    // only for sunrise and sunset and the gusts; without it (or in older files) the page
    // shows none of them
    getJson("data/scores/outlook.json"),
  ]);
  const outlook = parseOutlook(outlookDoc);
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
  const modelSelect = document.getElementById("model");
  modelSelect.addEventListener("change", () => pick(modelSelect.value, names, colors));
  select.addEventListener("change", () => {
    const point = points.find((p) => p.code === select.value);
    window.history.replaceState(null, "", `#${point.code}`);
    show(point, names, colors, outlook);
  });
  window.history.replaceState(null, "", `#${current.code}`);
  await show(current, names, colors, outlook);
}

main();
