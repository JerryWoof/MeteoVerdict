import "./style.css";

import * as Plot from "@observablehq/plot";

import { setUpLanguage } from "./i18n.js";
import { displayName } from "./tv.js";

const t = setUpLanguage();
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
  el.textContent = text;
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

function renderExperiments(doc) {
  const box = document.getElementById("ai-experiments");
  box.replaceChildren(
    ...doc.experiments.map((e) => {
      const card = document.createElement("article");
      card.className = `ai-card ${e.status}`;
      const title = document.createElement("h3");
      title.append(cell("span", t(`ai.exp.${e.id}.name`)), " ", cell("span", t(`ai.status.${e.status}`), `ai-status ${e.status}`));
      card.append(title, cell("p", t(`ai.exp.${e.id}.what`)));
      if (e.result) card.append(cell("p", t(`ai.exp.${e.id}.result`, e.result), "ai-result"));
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

function setUpForecast(fc) {
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
  const show = () => renderForecast(select.value, fc.okresy[select.value]);
  select.addEventListener("change", show);
  show();
}

async function main() {
  const status = document.getElementById("status");
  const [doc, fc] = await Promise.all([getJson("data/scores/ai/ai.json"), getJson("data/scores/ai/ai-forecast.json")]);
  if (fc) setUpForecast(fc);
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
