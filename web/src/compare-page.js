import * as Plot from "@observablehq/plot";

import "./style.css";

import { biasByElevation, fmt, rankingTable } from "./compare.js";
import { modelColors, records } from "./data.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";
import {
  WINDOWS, availableLeadDays, availableVariables, parseHash, toHash,
} from "./view.js";

const t = setUpLanguage();

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const load = (view, level) =>
  getJson(`data/scores/${view.window}/${level}/${view.variable}.json`).then(records);

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
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderTable(rows, names) {
  const table = document.getElementById("ranking");
  const head = document.createElement("tr");
  for (const key of ["rank", "model", "mae", "diff", "bias", "rmse", "stations", "days"]) {
    head.append(cell("th", t(`table.${key}`)));
  }
  const body = rows.map((r) => {
    const tr = document.createElement("tr");
    if (r.rank == null) tr.className = "baseline";
    const rank = r.rank == null ? "–" : `${r.tied ? "≈" : ""}${r.rank}`;
    const ci = r.ci ? ` ${t("compare.interval", { low: fmt(r.ci[0], true), high: fmt(r.ci[1], true) })}` : "";
    tr.append(
      cell("td", rank),
      cell("td", names[r.model] ?? r.model),
      cell("td", fmt(r.mae), "num"),
      cell("td", r.rank === 1 ? t("compare.best") : r.diff == null ? "–" : `${fmt(r.diff, true)}${ci}`, "num"),
      cell("td", fmt(r.bias, true), "num"),
      cell("td", fmt(r.rmse), "num"),
      cell("td", r.stations ?? "–", "num"),
      cell("td", r.days ?? "–", "num"),
    );
    return tr;
  });
  if (body.length === 0) {
    const tr = document.createElement("tr");
    tr.append(cell("td", t("compare.empty")));
    body.push(tr);
  }
  table.replaceChildren(head, ...body);
}

function renderBias(rows, colors, names) {
  const target = document.getElementById("bias");
  if (rows.length === 0) {
    target.replaceChildren(cell("p", t("compare.empty")));
    return;
  }
  const models = [...new Set(rows.map((r) => r.model))];
  target.replaceChildren(
    Plot.plot({
      width: Math.min(720, document.body.clientWidth - 32),
      marginLeft: 180,
      x: { label: "Bias", grid: true },
      y: { label: null, tickFormat: (m) => names[m] ?? m },
      fy: { label: null, tickFormat: (e) => t(`elevation.${e}`) },
      color: { domain: models, range: models.map((m) => colors[m] ?? "#888888") },
      marks: [
        Plot.barX(rows, { x: "bias", y: "model", fy: "elevation", fill: "model", tip: true }),
        Plot.ruleX([0]),
      ],
    }),
  );
}

async function main() {
  const meta = await getJson("data/scores/meta.json");
  document.getElementById("status").textContent = statusText(meta, t);
  const names = { ...meta?.models, blend: t("model.blend") };
  const colors = modelColors(names);
  const view = parseHash(window.location.hash);

  async function render() {
    const cz = await load(view, "cz");
    const leadDays = availableLeadDays(cz);
    if (!leadDays.includes(view.leadDay)) view.leadDay = leadDays[0];
    fillSelect("lead", leadDays.map((d) => [d, `D+${d}`]), view.leadDay);
    renderTable(rankingTable(cz, view.leadDay), names);
    renderBias(biasByElevation(await load(view, "elevation"), view.leadDay), colors, names);
    window.history.replaceState(null, "", toHash(view));
  }

  fillSelect("variable", availableVariables(meta).map((v) => [v, t(`variable.${v}`)]), view.variable);
  fillSelect("window", WINDOWS.map((w) => [w, t(`window.${w}`)]), view.window);
  for (const [id, key, parse] of [
    ["variable", "variable", String],
    ["lead", "leadDay", Number],
    ["window", "window", String],
  ]) {
    document.getElementById(id).addEventListener("change", (event) => {
      view[key] = parse(event.target.value);
      render();
    });
  }
  await render();
}

main();
