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
import { SEAT_OKRES, seatName, seatOkres } from "./seats.js";
import { statusText } from "./status.js";
import { chmiNotice, dayLabel, gustOver, gustOverText, parseOutlook, rowFor, sunFor, today } from "./tv.js";
import { AI_FILES, aiPath, aiText } from "./ai-source.js";
import { AI_MODEL, loadAi, withAi } from "./ai-model.js";

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
  document.getElementById("combined-note").textContent = t("forecast.note");
  document.getElementById("weights-section").hidden = true;
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

function timeTick(date) {
  const language = document.documentElement.lang;
  const hour = pragueHour(date);
  if (hour !== 0) return `${hour}:00`;
  return new Intl.DateTimeFormat(language, { weekday: "short", day: "numeric", month: "numeric", timeZone: TIME_ZONE }).format(date);
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
      const td = cell("td", fmt(gust?.gust), gustOver(gust) ? "num gust-over-threshold" : "num");
      if (gustOver(gust)) td.title = gustOverText(t, document.documentElement.lang);
      tr.append(td);
    }
    if (withSun) tr.append(sunCell(sunOf(d.day)));
    return tr;
  });
  table.replaceChildren(head, ...rows);
  // the notice under the table, only where a gust is flagged
  document.getElementById("gust-notice").replaceChildren(
    ...(withGust && days.some((d) => gustOver(gustOf(d.day))) ? [chmiNotice(t)] : []),
  );
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
  // the 80 % range of our temperature (outlook-hourly, `mvd blend-interval`): a band behind
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
        ...(band.length
          ? [Plot.areaY(band, { x: "time", y1: "lo", y2: "hi", fill: "#1d2329", fillOpacity: 0.12, curve })]
          : []),
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
            Plot.lineY(withRange, {
              x: "time", y: "value", stroke: "#1d2329", strokeWidth: 2.5, curve, tip: true,
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
  const { parsed, forecast, combined, table, days, sunOf, gustOf, range } = state;
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
    renderDays(rows.map(dayRow), sunOf, () => null);
  } else {
    modelNote.textContent = "";
    renderDays(days.map(dayRow), sunOf, gustOf);
  }
  const nights = nightBands(sunOf, forecast.times[0], forecast.times.at(-1), TIME_ZONE);
  const issued = Date.parse(parsed.generated ?? "") || Date.now();
  document.getElementById("charts").replaceChildren(
    ...VARIABLES.map((v) => chart(forecast, combined[v], table, v, colors, names, nights, selected, issued, range)),
  );
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
  const [weightsDoc, modelsDoc, ai] = await Promise.all([
    getJson(`data/scores/forecast/${point.code}.json`),
    getJson(`data/scores/forecast/models/${point.code}.json`),
    AI ? null : loadAi(getJson),
  ]);
  if (token !== showToken) return;
  const table = weightTable(weightsDoc);
  if (table.size === 0) {
    message.textContent = t("forecast.noWeights");
    return;
  }
  const parsed = withAi(parseModels(modelsDoc), ai, point.code);
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
  state = { point, table, parsed, forecast, combined, days, sunOf, gustOf, range };
  const when = issuedText(state.parsed.generated);
  issued.textContent = when ? t("forecast.issued", { time: when }) : "";
  selected = fillPicker(document.getElementById("model"), {
    table, names, available: new Set(Object.keys(parsed.models)), selected: preferred, t,
  });
  if (!AI) renderWeights(table, names);
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
