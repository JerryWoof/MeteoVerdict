import * as Plot from "@observablehq/plot";

import "./style.css";

import { modelColors, records } from "./data.js";
import {
  COMBINED, MAX_LEAD_DAY, VARIABLES, bestPerLeadDay, combine, dailySummary, forecastUrl, mergeForecast, modelDays,
  modelEnd, modelOptions, nightBands, parseForecast, weightTable, weightedModels, winnersByLeadDay,
} from "./forecast.js";
import { setUpLanguage } from "./i18n.js";
import { glyph } from "./icons.js";
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
function chart(forecast, combined, table, variable, colors, names, nights, selected) {
  const now = Date.now();
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
  bestPerLeadDay(forecast, table, variable, now).forEach(({ value, model }, i) => {
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
// the okres on screen: {point, table, forecast, combined, sunOf, gustOf, fetched}
let state = null;

function optionText(o, names) {
  if (o.model === COMBINED) return t("forecast.pickCombined");
  const model = names[o.model] ?? o.model;
  if (!o.scored) return model;
  const rank = o.rank == null
    ? "–"
    : o.rank.toLocaleString(document.documentElement.lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return t("forecast.pickOption", { position: o.position, model, rank });
}

function renderPicker(table, names) {
  const select = document.getElementById("model");
  const options = modelOptions(table, names);
  if (!options.some((o) => o.model === selected)) selected = COMBINED;
  const option = (o) => {
    const element = document.createElement("option");
    element.value = o.model;
    element.textContent = optionText(o, names);
    element.selected = o.model === selected;
    return element;
  };
  const group = (key, list) => {
    const element = document.createElement("optgroup");
    element.label = t(key);
    element.append(...list.map(option));
    return element;
  };
  const scored = options.filter((o) => o.scored);
  const unscored = options.filter((o) => !o.scored && o.model !== COMBINED);
  select.replaceChildren(
    option(options[0]),
    ...(scored.length ? [group("forecast.pickScored", scored)] : []),
    ...(unscored.length ? [group("forecast.pickUnscored", unscored)] : []),
  );
}

// the day table, the charts and the notes for the selected forecast
function render(names, colors) {
  const { forecast, combined, table, sunOf, gustOf } = state;
  const single = selected !== COMBINED;
  const ourDays = dailySummary(forecast.times, combined, TIME_ZONE);
  const modelNote = document.getElementById("model-note");
  document.getElementById("combined-note").hidden = single;
  modelNote.hidden = !single;
  if (single) {
    const name = names[selected] ?? selected;
    const days = modelDays(forecast, selected, ourDays.map((d) => d.day), TIME_ZONE);
    const end = modelEnd(forecast, selected);
    let note = t("forecast.modelNote", { model: name });
    if (end != null && days.some((d) => d.beyond)) {
      const when = new Intl.DateTimeFormat(document.documentElement.lang, {
        weekday: "short", day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", timeZone: TIME_ZONE,
      }).format(end);
      note += ` ${t("forecast.modelHorizon", { end: when })}`;
    }
    modelNote.textContent = note;
    // the gusts come from our corrected outlook: not shown for a single model
    renderDays(days, sunOf, () => null);
  } else {
    modelNote.textContent = "";
    renderDays(ourDays, sunOf, gustOf);
  }
  const nights = nightBands(sunOf, forecast.times[0], forecast.times.at(-1), TIME_ZONE);
  document.getElementById("charts").replaceChildren(
    ...VARIABLES.map((v) => chart(forecast, combined[v], table, v, colors, names, nights, selected)),
  );
}

// a model outside the okres weights is fetched when it is first picked (the visitor's
// own Open-Meteo call, one model)
async function pick(model, names, colors) {
  selected = model;
  if (!state) return;
  const message = document.getElementById("message");
  const current = state;
  const has = () => VARIABLES.some((v) => current.forecast.values[v][model]);
  if (model !== COMBINED && !has() && !current.fetched.has(model)) {
    message.textContent = t("forecast.pickLoading", { model: names[model] ?? model });
    const doc = await getJson(forecastUrl(current.point, [model]));
    current.fetched.add(model);
    if (doc?.hourly) mergeForecast(current.forecast, parseForecast(doc, [model]));
    if (state !== current || selected !== model) return;
  }
  message.textContent = model !== COMBINED && !has() ? t("forecast.pickUnavailable", { model: names[model] ?? model }) : "";
  render(names, colors);
}

// only the latest okres renders: a slow fetch must not overwrite a newer choice
let showToken = 0;
async function show(point, names, colors, outlook) {
  const token = ++showToken;
  const message = document.getElementById("message");
  document.getElementById("title").textContent = t("forecast.titleFor", { okres: point.name });
  state = null;
  for (const id of ["days", "charts", "weights"]) document.getElementById(id).replaceChildren();
  document.getElementById("model-note").hidden = true;
  document.getElementById("combined-note").hidden = false;
  if (!point.weights) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  message.textContent = t("forecast.loading");
  const table = weightTable(await getJson(`data/scores/forecast/${point.code}.json`));
  if (token !== showToken) return;
  const models = weightedModels(table);
  if (models.length === 0) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  renderPicker(table, names);
  const doc = await getJson(forecastUrl(point, models));
  if (token !== showToken) return;
  if (!doc?.hourly) {
    message.textContent = t("forecast.unavailable");
    return;
  }
  const forecast = parseForecast(doc, models);
  const now = Date.now();
  const combined = Object.fromEntries(VARIABLES.map((v) => [v, combine(forecast, table, v, now)]));
  const sunOf = (day) => sunFor(outlook, point.code, day);
  const gustOf = (day) => rowFor(outlook, point.code, day, "day");
  state = { point, table, forecast, combined, sunOf, gustOf, fetched: new Set(models) };
  renderWeights(table, names);
  message.textContent = "";
  await pick(selected, names, colors);
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
