import * as Plot from "@observablehq/plot";

import "./style.css";

import { modelColors, records } from "./data.js";
import { INK, pick as themed } from "./map-theme.js";
import { onThemeChange } from "./theme.js";
import {
  COMBINED, VARIABLES, bestPerLeadDay, dailySummary, nightBands, weightTable, winnersByLeadDay,
} from "./forecast.js";
import { setUpLanguage } from "./i18n.js";
import { glyph } from "./icons.js";
import { GUST_THRESHOLD, asForecast, modelHorizon, modelPeriods, parseModels } from "./models.js";
import { fillPicker, issuedText } from "./picker.js";
import { SEAT_OKRES, seatName, seatOkres } from "./seats.js";
import { statusText } from "./status.js";
import { chmiNotice, dayLabel, gustOver, gustOverText, parseOutlook, rowFor, sunFor, today } from "./tv.js";
import { AI_FILES, aiPath, aiText } from "./ai-source.js";
import { AI_MODEL, loadAi, withAi } from "./ai-model.js";
import { dayWindDirection, extraDisplay, extraFor } from "./ai-extra.js";

// ?source=ai: MeteoVerdict AI's forecast (the AI forecast tab's detail, ai-source.js): its
// own outlook.json and obce files, "MeteoVerdict AI" wherever ours is named, no weights
const AI = new URLSearchParams(window.location.search).get("source") === "ai";
const t = AI ? aiText(setUpLanguage()) : setUpLanguage();
const TIME_ZONE = "Europe/Prague";
const UNITS = { temperature_2m: "°C", precipitation: "mm", wind_speed_10m: "m/s" };

async function fetchJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const getJson = AI ? (path) => fetchJson(AI_FILES.test(path) ? aiPath(path) : path) : fetchJson;

if (AI) {
  // the AI tab's colours and menu entry; the texts the page sets once
  document.body.classList.replace("theme-forecast", "theme-ai");
  document.querySelector('.site-nav a[href="forecast.html"]')?.classList.remove("current-section");
  document.querySelector("#combined-note span").textContent = t("forecast.note");
  document.title = "MeteoVerdict: AI forecast by okres";
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

function timeTick(date, narrow = false) {
  const language = document.documentElement.lang;
  const hour = pragueHour(date);
  if (hour !== 0) return `${hour}:00`;
  // a phone: the date alone, so that seven days fit
  const weekday = narrow ? {} : { weekday: "short" };
  return new Intl.DateTimeFormat(language, { ...weekday, day: "numeric", month: "numeric", timeZone: TIME_ZONE }).format(date);
}

// in the page language: "7,4" in Czech
const fmt = (v, digits = 1) =>
  v == null ? "–" : v.toLocaleString(document.documentElement.lang || "en", { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false });

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

// the max wind with a small arrow for where it blows from (extra variables, when the file has them)
function windCell(wind, direction) {
  const td = cell("td", fmt(wind), "num");
  if (direction != null && wind != null) {
    const arrow = cell("span", "↓", "wind-dir");
    arrow.style.transform = `rotate(${Math.round(direction)}deg)`;
    arrow.title = `${t("forecast.extra.windDir")}: ${Math.round(direction)}°`;
    arrow.setAttribute("aria-label", arrow.title);
    td.append(" ", arrow);
  }
  return td;
}

function renderDays(days, sunOf, gustOf, dirOf = () => null) {
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
      windCell(d.wind, dirOf(d.day)),
    );
    if (withGust) {
      // from outlook.json (the single runs, corrected): null beyond the newest run
      const gust = gustOf(d.day);
      const td = cell("td", fmt(gust?.gust), gustOver(gust) ? "num gust-over-threshold" : "num");
      if (gustOver(gust)) td.title = gustOverText(t, document.documentElement.lang);
      tr.append(td);
    }
    if (withSun) tr.append(sunCell(sunOf(d.day)));
    return tr;
  });
  table.replaceChildren(head, ...rows);
  document.getElementById("gust-notice").replaceChildren(chmiNotice(t));
}

// `selected`: COMBINED (our forecast highlighted, with the best model per lead day) or a
// model id (that model's raw forecast highlighted, ours thin for reference)
// `issued`: when the forecast was made (ms): the lead days count from it, as in the outlook
function chart(forecast, combined, table, variable, colors, names, nights, selected, issued, range) {
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
  // the 80 % range of our temperature (outlook-hourly): a band behind
  // the line and, in its tooltip, how far it reaches
  const band = [];
  if (variable === "temperature_2m" && range) {
    combined.forEach((v, i) => {
      const lo = range.lo[i];
      const hi = range.hi[i];
      if (v == null || lo == null || hi == null) return;
      band.push({ time: new Date(forecast.times[i]), lo, hi });
    });
  }
  const byTime = new Map(band.map((b) => [b.time.getTime(), b]));
  const withRange = ours.map((o) => {
    const b = byTime.get(o.time.getTime());
    return { ...o, range: b ? offsetText(b.lo - o.value, b.hi - o.value) : "" };
  });
  const picked = single ? points(forecast.values[variable][selected] ?? []) : [];
  // the best model of each lead day, as segments coloured by model
  let segment = 0;
  let previous = null;
  const best = [];
  // MeteoVerdict AI: only its own line over the public models
  (AI ? [] : bestPerLeadDay(forecast, table, variable, issued)).forEach(({ value, model }, i) => {
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
  figure.className = "forecast-chart";
  // "Teplota (2 m), °C": the name has its own parentheses
  figure.append(cell("figcaption", `${t(`forecast.${variable}`)}, ${UNITS[variable]}`));
  const step = variable === "precipitation";
  const curve = step ? "step-before" : "linear";
  // the width of the text column (the figure has no indent, forecast-chart in style.css)
  const width = Math.min(1200, document.body.clientWidth - 32);
  figure.append(
    Plot.plot({
      width,
      height: 220,
      marginLeft: 40,
      // room for the last day's label at the right edge
      marginRight: 28,
      x: {
        label: null,
        type: "time",
        // noon and midnight; on a phone only midnight (the day), or the labels overlap
        ticks: forecast.times.map((time) => new Date(time)).filter((d) => pragueHour(d) % (width < 600 ? 24 : 12) === 0),
        tickFormat: (date) => timeTick(date, width < 600),
      },
      y: { label: null, grid: true, zero: step },
      marks: [
        // night, sunset to sunrise, behind everything; the full height of the chart
        Plot.rectX(nights, {
          x1: (n) => new Date(n.start), x2: (n) => new Date(n.end), fill: themed(INK), fillOpacity: 0.06,
        }),
        ...(band.length
          ? [Plot.areaY(band, { x: "time", y1: "lo", y2: "hi", fill: themed(INK), fillOpacity: 0.12, curve })]
          : []),
        Plot.lineY(rows, { x: "time", y: "value", z: "model", stroke: themed(["#b7bec4", "#4a443d"]), strokeWidth: 0.8, curve }),
        ...(single
          ? [
            Plot.lineY(ours, { x: "time", y: "value", stroke: themed(INK), strokeWidth: 1, curve }),
            Plot.lineY(picked, {
              x: "time", y: "value", stroke: colors[selected] ?? "#1f78b4", strokeWidth: 2.5, curve, tip: true,
            }),
          ]
          : [
            Plot.lineY(best, {
              x: "time", y: "value", z: "segment", stroke: (r) => colors[r.model] ?? "#1f78b4", strokeWidth: 1.6, curve,
            }),
            Plot.lineY(withRange, {
              x: "time", y: "value", stroke: themed(INK), strokeWidth: 2.5, curve, tip: true,
              channels: band.length ? { range: { value: "range", label: "±" } } : {},
            }),
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
    : t(AI && ours.length === 0 ? "ai.legendOkres" : "forecast.legend", { best: winners || "–" });
  legend.textContent = text + (nights.length ? ` ${t("forecast.night")}` : "")
    + (band.length ? ` ${t("forecast.range")}` : "");
  figure.append(legend);
  return figure;
}

// "−1,4 / +1,2 °C": the 80 % range as offsets from our forecast
function offsetText(lo, hi) {
  const one = (v) => `${v < 0 ? "−" : "+"}${Math.abs(v).toLocaleString(document.documentElement.lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
  return `${one(lo)} / ${one(hi)} °C (80 %)`;
}

// which forecast is shown: MeteoVerdict AI on every page load where the okres has it, else
// our combination (not remembered, not in the link); `preferred` is the choice kept while the
// okres changes, `selected` what the okres can offer of it (no AI forecast there: the combination)
const defaultModel = () => (AI ? COMBINED : AI_MODEL);
let preferred = defaultModel();
let selected = preferred;
// the okres on screen: {point, table, parsed, forecast, combined, periods, days, sunOf, gustOf}
let state = null;
const dayRow = (d) => ({ day: d.day, tmin: d.tmin, tmax: d.tmax, precipitation: d.precipitation, wind: d.wind });

// the day table, the charts and the notes for the selected forecast
function render(names, colors) {
  const { parsed, forecast, combined, table, days, sunOf, range, ai, point } = state;
  const single = selected !== COMBINED;
  // the further variables of the selected forecast (MeteoVerdict AI's file or the combination's own hours)
  const extra = extraDisplay(extraFor(selected === COMBINED ? "combined" : selected, { ai, code: point.code, parsed }));
  state.extra = extra;
  const wind = selected === AI_MODEL ? ai?.okresy?.[point.code] : { times: parsed.times, wind_speed_10m: parsed.combined.wind_speed_10m };
  const dirOf = (day) => dayWindDirection(extra, wind, day, TIME_ZONE);
  // MeteoVerdict AI's gusts per day from its own sky file; ours from the corrected outlook
  const gustOf = selected === AI_MODEL
    ? (day) => {
      const gust = ai?.sky?.get(point.code)?.get(`${day}|day`)?.gust ?? null;
      return gust == null ? null : { gust, gust_over_threshold: gust >= GUST_THRESHOLD };
    }
    : state.gustOf;
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
    if (selected === AI_MODEL) note = t("ai.modelNote", { time: issuedText(parsed.aiIssued ?? parsed.generated) ?? "–" });
    if (end != null && rows.some((d) => d.beyond)) {
      const when = new Intl.DateTimeFormat(document.documentElement.lang, {
        weekday: "short", day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", timeZone: TIME_ZONE,
      }).format(end);
      note += ` ${t("forecast.modelHorizon", { end: when })}`;
    }
    // MeteoVerdict AI: only its name says "experimental", no note
    modelNote.textContent = selected === AI_MODEL ? "" : note;
    modelNote.hidden = selected === AI_MODEL;
    // the gusts come from our corrected outlook: not shown for a single model
    renderDays(rows.map(dayRow), sunOf, selected === AI_MODEL ? gustOf : () => null, dirOf);
  } else {
    modelNote.textContent = "";
    renderDays(days.map(dayRow), sunOf, gustOf, dirOf);
  }
  const nights = nightBands(sunOf, forecast.times[0], forecast.times.at(-1), TIME_ZONE);
  const issued = Date.parse(parsed.generated ?? "") || Date.now();
  document.getElementById("charts").replaceChildren(
    ...VARIABLES.map((v) => chart(forecast, combined[v], table, v, colors, names, nights, selected, issued, range)),
  );
  renderExtra(nights);
}

// further variables (AI file's `extra` block): one compact chart with a variable selector, only
// for the AI and the combination (a single public model has none), and only where the file has them
let extraVariable = null;
function renderExtra(nights) {
  const box = document.getElementById("extra");
  const items = state.extra.filter((e) => e.series.some((v) => v != null));
  if (!items.length || (selected !== COMBINED && selected !== AI_MODEL)) {
    box.replaceChildren();
    box.hidden = true;
    return;
  }
  const item = items.find((e) => e.variable === extraVariable) ?? items[0];
  extraVariable = item.variable;
  const heading = cell("h3", t("forecast.extra.title"), "extra-title");
  const select = document.createElement("select");
  select.setAttribute("aria-label", t("forecast.extra.pick"));
  select.replaceChildren(...items.map((e) => {
    const option = document.createElement("option");
    option.value = e.variable;
    option.textContent = t(`forecast.extra.${e.variable}`);
    option.selected = e.variable === item.variable;
    return option;
  }));
  select.addEventListener("change", () => {
    extraVariable = select.value;
    renderExtra(nights);
  });
  const head = cell("div", null, "extra-head");
  head.append(heading, select);
  // only a value that is the models' median (no weights of ours) says so
  if (item.source === "reference") head.append(cell("span", t("forecast.extra.reference"), "extra-label"));
  const figure = document.createElement("figure");
  figure.className = "forecast-chart extra-chart";
  figure.append(cell("figcaption", `${t(`forecast.extra.${item.variable}`)}${item.unit ? `, ${item.unit}` : ""}`));
  figure.append(extraPlot(item, nights));
  box.replaceChildren(head, figure);
  box.hidden = false;
}

function extraPlot(item, nights) {
  const width = Math.min(1200, document.body.clientWidth - 32);
  const times = item.times;
  const rows = item.series.map((v, i) => ({ time: new Date(times[i]), value: v })).filter((r) => r.value != null);
  const kind = item.variable === "snowfall" ? "step" : item.variable === "wind_direction_10m" ? "dot" : "line";
  const stroke = themed(INK);
  const mark = kind === "dot"
    ? Plot.dot(rows, { x: "time", y: "value", r: 2, fill: stroke, tip: true })
    : Plot.lineY(rows, { x: "time", y: "value", stroke, strokeWidth: 2, curve: kind === "step" ? "step-before" : "linear", tip: true });
  return Plot.plot({
    width,
    height: 160,
    marginLeft: 40,
    marginRight: 28,
    x: {
      label: null,
      type: "time",
      ticks: times.map((time) => new Date(time)).filter((d) => pragueHour(d) % (width < 600 ? 24 : 12) === 0),
      tickFormat: (date) => timeTick(date, width < 600),
    },
    y: {
      label: null,
      grid: true,
      zero: kind === "step" || ["snow_depth", "snow_depth_water_equivalent", "cape", "visibility", "fog_probability", "wind_gusts_10m", "shortwave_radiation", "sunshine_duration", "cloud_cover_low"].includes(item.variable),
      ...(item.variable === "wind_direction_10m" ? { domain: [0, 360], ticks: [0, 90, 180, 270, 360] } : {}),
    },
    marks: [
      Plot.rectX(nights, { x1: (n) => new Date(n.start), x2: (n) => new Date(n.end), fill: stroke, fillOpacity: 0.06 }),
      mark,
      Plot.ruleX([new Date()], { stroke: "#c0392b", strokeDasharray: "3,3" }),
    ],
  });
}

function pick(model, names, colors) {
  preferred = model;
  selected = model;
  if (state) render(names, colors);
}

// only the latest okres renders: a slow download must not overwrite a newer choice
let showToken = 0;
async function show(point, names, colors, outlook) {
  const token = ++showToken;
  const message = document.getElementById("message");
  const issued = document.getElementById("issued");
  document.getElementById("title").textContent = t("forecast.titleFor", { town: seatName(point.code, point.name) });
  state = null;
  for (const id of ["days", "charts", "extra"]) document.getElementById(id).replaceChildren();
  document.getElementById("extra").hidden = true;
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
  const [weightsDoc, modelsDoc, ai] = await Promise.all([
    getJson(`data/scores/forecast/${point.code}.json`),
    getJson(`data/scores/forecast/models/${point.code}.json`),
    loadAi(getJson),
  ]);
  if (token !== showToken) return;
  const table = weightTable(weightsDoc);
  if (table.size === 0) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  const parsed = withAi(parseModels(modelsDoc), AI ? null : ai, point.code);
  if (!parsed) {
    message.textContent = t("forecast.unavailable");
    return;
  }
  const forecast = asForecast(parsed, VARIABLES);
  // MeteoVerdict AI: no hourly series per okres, so no black line
  const combined = Object.fromEntries(
    VARIABLES.map((v) => [v, (AI ? null : parsed.combined[v]) ?? parsed.times.map(() => null)]),
  );
  const sunOf = (day) => sunFor(outlook, point.code, day);
  const gustOf = (day) => rowFor(outlook, point.code, day, "day");
  // the days of our forecast as on the forecast map (outlook.json); without them (an
  // older or missing file) from the combined hours
  const fromOutlook = outlook.days
    .map((day) => ({ ...rowFor(outlook, point.code, day, "day"), day }))
    .filter((d) => d.tmin != null);
  const days = fromOutlook.length ? fromOutlook : dailySummary(parsed.times, combined, TIME_ZONE);
  // the range around our temperature (not for the AI view, which has no okres series)
  const range = !AI && parsed.combined.temperature_2m_lo && parsed.combined.temperature_2m_hi
    ? { lo: parsed.combined.temperature_2m_lo, hi: parsed.combined.temperature_2m_hi }
    : null;
  state = { point, table, parsed, forecast, combined, days, sunOf, gustOf, range, ai, extra: [] };
  const when = issuedText(state.parsed.generated);
  issued.textContent = when ? t("forecast.issued", { time: when }) : "";
  selected = fillPicker(document.getElementById("model"), {
    table, names, available: new Set(Object.keys(parsed.models)), selected: preferred, t,
  });
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
  const names = { ...meta?.models, [AI_MODEL]: t("ai.modelName") };
  const colors = modelColors(names);
  // lighter model colours in dark: update in place (the page holds this object) and redraw
  onThemeChange(() => {
    Object.assign(colors, modelColors(names));
    if (state) render(names, colors);
  });
  // one entry per okres town; the okresy whose seat is a city elsewhere show that city
  const points = records(index)
    .filter((p) => !(p.code in SEAT_OKRES))
    .map((p) => ({ ...p, town: seatName(p.code, p.name) }))
    .sort((a, b) => a.town.localeCompare(b.town, "cs"));
  if (points.length === 0) {
    document.getElementById("message").textContent = t("forecast.noWeights");
    return;
  }
  // #<okres> (an older #<okres>/<obec> link opens its okres town)
  const wanted = seatOkres(window.location.hash.slice(1).split("/")[0]);
  const link = (point) => `#${point.code}`;
  const current = points.find((p) => p.code === wanted) ?? points.find((p) => p.code === "CZ0100") ?? points[0];
  const select = document.getElementById("okres");
  select.replaceChildren(
    ...points.map((p) => {
      const option = document.createElement("option");
      option.value = p.code;
      option.textContent = p.town;
      option.selected = p.code === current.code;
      return option;
    }),
  );
  const modelSelect = document.getElementById("model");
  modelSelect.addEventListener("change", () => pick(modelSelect.value, names, colors));
  select.addEventListener("change", () => {
    const point = points.find((p) => p.code === select.value);
    window.history.replaceState(null, "", link(point));
    show(point, names, colors, outlook);
  });
  window.history.replaceState(null, "", link(current));
  await show(current, names, colors, outlook);
}

main();
