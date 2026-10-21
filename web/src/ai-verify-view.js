// "Forecast vs measured" on the AI tab: for one okres, what the ČHMÚ stations measured
// and what MeteoVerdict AI and one public model forecast for the same hours, from the AI's
// launch on; right of "now" the latest forecast (data/scores/ai/fc/verify/). Hidden without its index.
import * as Plot from "@observablehq/plot";

import { dateText as isoDateText, numText } from "./ai-format.js";
import { chartRows, measuredHours, modelsByMae, okresyByName, pickModel, startOkres } from "./ai-verify.js";

const BASE = "data/scores/ai/fc/verify";
const VARIABLES = ["temperature_2m", "wind_speed_10m"];
const UNITS = { temperature_2m: "°C", wind_speed_10m: "m/s" };
const TIME_ZONE = "Europe/Prague";
export const COLORS = { measured: "#1d2329", ai: "#6a4fb3", model: "#e08a1e" };

const lang = () => document.documentElement.lang;

const fmt = (value, digits = 2) => numText(value, digits, lang());

function el(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

const dateText = (iso) => isoDateText(iso, lang());

// the day ticks: Prague midnights from the first to the last time, at most `count` of them
function dayTicks(first, last, count) {
  const hourAt = (date) =>
    Number.parseInt(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: TIME_ZONE }).format(date), 10);
  const days = [];
  const start = new Date(first);
  start.setUTCHours(0, 0, 0, 0);
  for (let d = start.getTime(); d <= last.getTime() + 86_400_000; d += 86_400_000) {
    const midnight = new Date(d - hourAt(new Date(d)) * 3_600_000);
    if (midnight >= first && midnight <= last) days.push(midnight);
  }
  const step = Math.max(1, Math.ceil(days.length / Math.max(2, count)));
  return days.filter((_, i) => i % step === 0);
}

const dayTick = (date) =>
  new Intl.DateTimeFormat(lang(), { weekday: "short", day: "numeric", month: "numeric", timeZone: TIME_ZONE }).format(date);
const timeText = (date) =>
  new Intl.DateTimeFormat(lang(), { weekday: "short", day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", timeZone: TIME_ZONE }).format(date);

function segmented(options, selected, onPick) {
  const box = el("div", null, "segmented");
  for (const [value, label] of options) {
    const button = el("button", label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(value === selected));
    button.addEventListener("click", () => onPick(value));
    box.append(button);
  }
  return box;
}

function field(label, control, className = "field") {
  const box = el(control.tagName === "SELECT" ? "label" : "div", null, className);
  box.append(el("span", label), " ", control);
  return box;
}

/** Fill the section #ai-verify-section; `open` is the okres open in the map's panel. */
export async function renderAiVerify(t, getJson, open) {
  const index = await getJson(`${BASE}/index.json`);
  const section = document.getElementById("ai-verify-section");
  if (!index?.okresy || !section) return;
  const names = index.models ?? {};
  const leads = index.lead_days?.length ? index.lead_days : [1, 2, 3];
  const docs = new Map();
  const load = (code) => {
    if (!docs.has(code)) docs.set(code, getJson(`${BASE}/${code}.json`));
    return docs.get(code);
  };
  const view = { okres: startOkres(index.okresy, open), variable: VARIABLES[0], lead: leads[0], model: null };
  let userModel = false;

  const controls = document.getElementById("ai-verify-controls");
  const okresSelect = el("select");
  for (const [code, name] of okresyByName(index.okresy, lang())) {
    const option = el("option", name);
    option.value = code;
    okresSelect.append(option);
  }
  okresSelect.addEventListener("change", () => draw({ okres: okresSelect.value }));
  const modelSelect = el("select");
  modelSelect.addEventListener("change", () => {
    userModel = true;
    draw({ model: modelSelect.value });
  });
  const variableBox = el("div", null, "field");
  const leadBox = el("div", null, "field");
  const row = el("div", null, "strip-row");
  row.append(
    field(t("control.okres"), okresSelect),
    variableBox,
    leadBox,
    field(t("ai.verifyCompare"), modelSelect, "field ai-verify-compare"),
  );
  controls.replaceChildren(row);

  const chart = document.getElementById("ai-verify-chart");
  const legend = document.getElementById("ai-verify-legend");
  const maeLine = document.getElementById("ai-verify-mae");
  const stationsLine = document.getElementById("ai-verify-stations");
  const launch = index.launch ?? index.from;
  const now = index.now ? new Date(index.now) : null;
  document.getElementById("ai-verify-intro").textContent = t("ai.verifyIntro", { launch: launch ? dateText(launch) : "–" });

  let drawn = 0;
  async function draw(change = {}) {
    Object.assign(view, change);
    const ticket = ++drawn;
    okresSelect.value = view.okres;
    variableBox.replaceChildren(
      el("span", t("control.variable")),
      segmented(VARIABLES.map((v) => [v, t(`ai.verifyVar.${v}`)]), view.variable, (variable) => draw({ variable })),
    );
    leadBox.replaceChildren(
      el("span", t("control.lead")),
      segmented(leads.map((d) => [d, `D+${d}`]), view.lead, (lead) => draw({ lead })),
    );
    const doc = await load(view.okres);
    if (ticket !== drawn) return;
    const series = doc?.lead_days?.[String(view.lead)]?.[view.variable];
    const unit = UNITS[view.variable];
    const ranked = modelsByMae(series, names);
    // the preselected model (index.default) until one is chosen
    view.model = pickModel(ranked, userModel ? view.model : index.default?.[view.variable]);
    modelSelect.replaceChildren(
      ...ranked.map((m) => {
        const option = el("option", m.mae == null ? m.name : `${m.name} (${fmt(m.mae)} ${unit})`);
        option.value = m.id;
        return option;
      }),
    );
    modelSelect.value = view.model ?? "";
    modelSelect.disabled = !ranked.length;
    if (!series || !doc.times?.length) {
      legend.replaceChildren();
      chart.replaceChildren(el("p", t("ai.verifyNone"), "note"));
      maeLine.textContent = "";
      stationsLine.textContent = "";
      return;
    }
    const modelName = names[view.model] ?? view.model ?? "–";
    legend.replaceChildren(
      ...[["measured", t("ai.verifyMeasured")], ["ai", "MeteoVerdict AI"], ["model", modelName]].map(([key, name]) =>
        el("span", name, `ai-verify-key ${key}`),
      ),
    );
    chart.replaceChildren(plot(chartRows(doc.times, series, view.model), now, view, unit, t, chart.clientWidth || 360, modelName));
    // nothing to compare yet: no measured hour with an AI forecast for it
    const hours = series.mae?.ai == null ? 0 : measuredHours(series);
    maeLine.textContent = hours
      ? t(hours === 1 ? "ai.verifyMae1" : "ai.verifyMae", {
          launch: launch ? dateText(launch) : "–",
          lead: `D+${view.lead}`,
          ai: `${fmt(series.mae?.ai)} ${unit}`,
          model: modelName,
          value: `${fmt(series.mae?.[view.model])} ${unit}`,
          n: hours,
        })
      : t("ai.verifyNoMeasured");
    stationsLine.textContent = doc.stations
      ? t(doc.stations === 1 ? "ai.verifyStation" : "ai.verifyStations", { n: doc.stations })
      : "";
  }

  // the panel on the map opens another okres: show it here too
  document.addEventListener("mv:okres", (event) => {
    if (event.detail && event.detail in index.okresy && event.detail !== view.okres) draw({ okres: event.detail });
  });
  let width = chart.clientWidth;
  new ResizeObserver(() => {
    if (Math.abs(chart.clientWidth - width) < 8) return;
    width = chart.clientWidth;
    draw();
  }).observe(chart);

  section.hidden = false;
  await draw();
}

const signed = (value) => (value == null ? "–" : `${value > 0 ? "+" : value < 0 ? "−" : "±"}${fmt(Math.abs(value), 1)}`);

function plot(rows, now, view, unit, t, width, modelName) {
  const first = rows[0].time;
  const last = rows.at(-1).time;
  const future = now && now < last ? [{ x1: now < first ? first : now, x2: last }] : [];
  const tipTitle = (r) => {
    const lines = [timeText(r.time), `${t("ai.verifyMeasured")}: ${fmt(r.measured, 1)} ${unit}`];
    const forecast = (name, value, d) =>
      `${name}: ${fmt(value, 1)} ${unit}${d == null ? "" : ` (${signed(d)})`}`;
    lines.push(forecast("MeteoVerdict AI", r.ai, r.dAi), forecast(modelName, r.model, r.dModel));
    return lines.join("\n");
  };
  const shown = rows.filter((r) => r.measured != null || r.ai != null || r.model != null);
  return Plot.plot({
    width,
    height: width < 500 ? 240 : 280,
    marginLeft: 40,
    marginRight: 12,
    marginTop: 26,
    x: { label: null, type: "time", domain: [first, last], ticks: dayTicks(first, last, Math.floor(width / 85)), tickFormat: dayTick },
    y: { label: unit, labelAnchor: "top", labelArrow: "none", labelOffset: 36, grid: true, zero: view.variable === "wind_speed_10m" },
    marks: [
      Plot.rectX(future, { x1: "x1", x2: "x2", fill: "#8a949c", fillOpacity: 0.12 }),
      future.length ? Plot.ruleX([future[0].x1], { stroke: "#8a949c", strokeWidth: 1.5 }) : null,
      // "now" left of the line unless the line is at the very start (then only "forecast")
      future.length && future[0].x1 - first > (last - first) * 0.12
        ? Plot.text([future[0].x1], { x: (d) => d, frameAnchor: "top", dy: -12, text: () => t("ai.verifyNow"), textAnchor: "end", dx: -4, fill: "#5b6670", fontSize: 11 })
        : null,
      future.length
        ? Plot.text([future[0].x1], { x: (d) => d, frameAnchor: "top", dy: -12, text: () => `${t("ai.verifyForecast")} →`, textAnchor: "start", dx: 4, fill: "#5b6670", fontSize: 11 })
        : null,
      Plot.lineY(rows, { x: "time", y: "model", stroke: COLORS.model, strokeWidth: 2, strokeDasharray: "6 4" }),
      Plot.lineY(rows, { x: "time", y: "ai", stroke: COLORS.ai, strokeWidth: 3 }),
      Plot.lineY(rows, { x: "time", y: "measured", stroke: COLORS.measured, strokeWidth: 1 }),
      Plot.dot(rows, { x: "time", y: "measured", fill: COLORS.measured, r: 3 }),
      Plot.ruleX(shown, Plot.pointerX({ x: "time", stroke: "#8a949c", strokeOpacity: 0.6 })),
      Plot.tip(shown, Plot.pointerX({ x: "time", y: (r) => r.measured ?? r.ai ?? r.model, title: tipTitle })),
    ],
  });
}
