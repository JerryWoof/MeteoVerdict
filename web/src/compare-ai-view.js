// The Compare page's same-sample section (compare-ai.js has the pure parts).
import * as Plot from "@observablehq/plot";

import {
  SOURCES, LEADS, VARIABLES, aiStatus, aiVersus, availableModels, bestModel, dailyRows, entryKey, formatView, hasAi,
  opponentSeries, parseView, regionGroups, seriesOf,
} from "./compare-ai.js";
import { dayTick, numberTick, tipText } from "./compare.js";
import { displayName } from "./tv.js";
import { dayCount, stationCount } from "./view.js";

const COLORS = { ai: "#c0392b", outlook: "#1f78b4", mean: "#1d2329", model: "#6a3d9a" };
// in the page language: "0,92" in Czech
const fmt = (v, signed = false, digits = 2) =>
  v == null
    ? "–"
    : `${signed && v > 0 ? "+" : ""}${v.toLocaleString(document.documentElement.lang || "en", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`.replace("-", "−");

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const cache = new Map();
/** First source that has the file (cached; a miss is not remembered). */
function load(sample, file) {
  const key = `${sample}/${file}`;
  if (!cache.has(key)) {
    const attempt = async () => {
      for (const base of SOURCES[sample]) {
        const doc = await getJson(`${base}/${file}`);
        if (doc) return doc;
      }
      return null;
    };
    cache.set(key, attempt().then((doc) => {
      if (!doc) cache.delete(key);
      return doc;
    }));
  }
  return cache.get(key);
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function fillSelect(id, options, current) {
  document.getElementById(id).replaceChildren(...options.map(([value, label, group]) => {
    const option = el("option", label);
    option.value = value;
    option.selected = String(value) === String(current);
    return group ? Object.assign(option, { group }) : option;
  }));
}

export async function setUpAiCompare(t, names, language) {
  const root = document.getElementById("ai-compare");
  if (!root) return;
  const [aiDoc, valIndex] = await Promise.all([getJson("data/scores/ai/ai.json"), load("validation", "index.json")]);
  // the live sample exists only once a day since the launch is measured (ai.json says how
  // many): no request for a file that is not there yet
  const liveIndex = aiDoc?.test?.days === 0 ? null : await load("live", "index.json");
  if (!valIndex && !liveIndex) {
    root.hidden = true;
    return;
  }
  const status = aiStatus(liveIndex ? { days: liveIndex.days, measured_hours: liveIndex.hours } : aiDoc?.test);
  const query = new URLSearchParams(window.location.search).get("cmp");
  const view = parseView(query, valIndex?.regions);
  // an old link to a kraj (no longer offered): Czechia
  if (valIndex?.regions?.[view.region]?.[0] === "kraj") view.region = "cz";
  if (view.sample === "live" && !liveIndex) view.sample = "validation";
  const modelName = (id) => names[id] ?? valIndex?.models?.[id] ?? id;
  let bestId = null;
  const label = (id, kind) =>
    kind === "ai" ? t("aic.ai") : kind === "outlook" ? t("aic.outlook") : kind === "mean" ? t("model.blend")
      : id === bestId && view.opponent === "best" ? t("aic.bestModel", { name: modelName(id) }) : modelName(id);
  const opponentName = (entry) => {
    const opp = opponentSeries(entry, view.opponent);
    return view.opponent === "best" && opp ? t("aic.bestModel", { name: modelName(opp.id) }) : label(opp.id, opp.kind);
  };

  /** Fills the opponent menu; a model the AI shares too few hours with here is greyed out. */
  function fillOpponents(entry) {
    const have = new Set(availableModels(entry));
    const option = (value, text, disabled = false) => Object.assign(el("option", text), { value, selected: value === view.opponent, disabled });
    const group = (text, items) => {
      const g = document.createElement("optgroup");
      g.label = text;
      g.append(...items);
      return g;
    };
    const best = bestModel(entry);
    const summaries = [
      option("outlook", t("aic.outlook")), option("mean", t("model.blend")),
      option("best", t("aic.opp.best") + (best ? ` (${modelName(best.id)})` : ""), !best),
    ];
    // the index lists the mean ("blend") and our blend ("combined") among the models: not single models
    const all = [...new Set([...Object.keys(valIndex?.models ?? {}), ...have])].filter((id) => !["blend", "combined"].includes(id))
      .sort((x, y) => modelName(x).localeCompare(modelName(y), language));
    const models = all.map((id) => option(id, have.has(id) ? modelName(id) : `${modelName(id)} (${t("aic.opp.few")})`, !have.has(id)));
    document.getElementById("aic-opponent").replaceChildren(group(t("aic.opp.group"), summaries), group(t("aic.opp.models"), models));
  }

  function fillRegions(index) {
    const groups = regionGroups(index, language);
    const select = document.getElementById("aic-region");
    const group = (text, items) => {
      const g = document.createElement("optgroup");
      g.label = text;
      g.append(...items.map(([code, name]) => Object.assign(el("option", displayName(name)), { value: code, selected: code === view.region })));
      return g;
    };
    select.replaceChildren(
      Object.assign(el("option", t("region.cz")), { value: "cz", selected: view.region === "cz" }),
      // okresy, not kraje (the owner's choice, as on compare-models)
      ...(groups.okresy.length ? [group(t("compare.okresy"), groups.okresy)] : []),
    );
  }

  function banner(index) {
    const node = document.getElementById("aic-status");
    const live = view.sample === "live";
    node.className = `aic-status ${status.verified ? "verified" : "provisional"}`;
    node.replaceChildren(
      el("strong", t(status.verified ? "aic.verified" : "aic.provisional")),
      document.createTextNode(" " + t(live ? "aic.sampleLive" : "aic.sampleValidation", {
        from: index?.from, to: index?.to, days: (index?.test_days ?? index?.days) != null ? dayCount(index.test_days ?? index.days, t) : "–",
      })),
    );
  }

  async function render() {
    const index = view.sample === "live" ? liveIndex : valIndex;
    fillRegions(valIndex ?? liveIndex);
    const doc = await load(view.sample, `${view.region}.json`);
    const entry = doc?.entries?.[entryKey(view.variable, view.lead)];
    bestId = bestModel(entry)?.id ?? null;
    let gone = false;
    if (entry && !opponentSeries(entry, view.opponent)) {
      view.opponent = "outlook";
      gone = true;
    }
    if (entry) fillOpponents(entry);
    fillSelect("aic-variable", VARIABLES.map((v) => [v, t(`variable.${v}`)]), view.variable);
    fillSelect("aic-lead", LEADS.map((l) => [l, `D+${l}`]), view.lead);
    fillSelect("aic-sample", [
      ["validation", t("aic.validation")],
      ["live", t("aic.live") + (liveIndex ? "" : ` (${t("aic.none")})`)],
    ], view.sample);
    document.getElementById("aic-sample").querySelector('[value="live"]').disabled = !liveIndex;
    banner(index);
    // an okres stands on its 1–2 stations: say so
    document.getElementById("aic-region-note").hidden = view.region === "cz";
    const unit = valIndex?.units?.[view.variable] ?? "";
    renderVerdict(entry, unit, gone);
    renderTable(entry, unit);
    renderChart(entry, unit);
    const url = new URL(window.location.href);
    url.searchParams.set("cmp", formatView(view));
    window.history.replaceState(null, "", url);
  }

  function renderVerdict(entry, unit, gone) {
    const node = document.getElementById("aic-verdict");
    const note = document.getElementById("aic-sample-note");
    if (!entry || !hasAi(entry)) {
      node.className = "aic-verdict";
      node.replaceChildren(el("p", t(entry ? "aic.noVs" : "aic.noData")));
      note.textContent = "";
      return;
    }
    const v = aiVersus(entry, view.opponent);
    const name = opponentName(entry);
    const provisional = entry.small_sample || view.sample === "validation" || !status.verified;
    node.className = `aic-verdict ${v?.verdict ?? "none"}`;
    const head = el("div", null, "aic-headline");
    head.append(el("strong", v ? t(`aic.verdict.${v.verdict ?? "none"}Vs`, { name }) : t("aic.noVs")));
    const lines = [head];
    if (v) {
      const numbers = el("div", null, "aic-numbers");
      for (const [text, value] of [[t("aic.ai"), v.ai.mae], [name, v.opponent.mae]]) {
        const box = el("div");
        box.append(el("span", fmt(value), "big"), el("span", `${unit} · ${text}`, "label"));
        numbers.append(box);
      }
      lines.push(numbers);
      lines.push(el("div", v.verdict
        ? t("aic.verdictDetailVs", { name, diff: fmt(v.diff, true), low: fmt(v.low, true), high: fmt(v.high, true), unit })
        : t("aic.verdictDetailNoInt", { name, diff: fmt(v.diff, true), unit }) + " " + t("aic.noInterval"), "detail"));
      if (v.pAiBetter != null) lines.push(el("div", t("aic.pAiBetter", { p: Math.round(v.pAiBetter * 100) }), "detail"));
    }
    if (gone) lines.push(el("div", t("aic.opp.gone"), "tag"));
    if (provisional) lines.push(el("div", t("aic.provisionalTag"), "tag"));
    node.replaceChildren(...lines);
    note.textContent = t("aic.sampleNote", {
      days: dayCount(entry.days, t), hours: entry.hours?.toLocaleString(language) ?? "?", from: entry.dates[0], to: entry.dates[1],
      stations: entry.stations == null ? "?" : stationCount(entry.stations, t),
      block: valIndex?.block_days ?? 4,
    }) + (entry.small_sample ? " " + t("aic.smallSample", { days: valIndex?.small_sample_days ?? 30 }) : "")
      + (entry.stations != null && entry.stations < 5 ? " " + t("aic.fewStations", { stations: stationCount(entry.stations, t) }) : "");
  }

  /** The rows: the AI, the chosen opponent, then our blend, the mean and the best model (no repeats). */
  function tableRows(entry) {
    const ai = seriesOf(entry).find((s) => s.kind === "ai");
    const rows = [ai, opponentSeries(entry, view.opponent), opponentSeries(entry, "outlook"), opponentSeries(entry, "mean"), bestModel(entry)];
    return [...new Set(rows.filter(Boolean))];
  }

  function renderTable(entry, unit) {
    const table = document.getElementById("aic-table");
    if (!entry || !hasAi(entry)) {
      table.replaceChildren();
      return;
    }
    const head = el("tr");
    for (const key of ["aic.col.name", "aic.col.mae", "aic.col.pbest", "aic.col.diff"]) head.append(el("th", t(key, { unit })));
    const chosen = opponentSeries(entry, view.opponent);
    const body = tableRows(entry).map((r) => {
      const tr = el("tr", null, `${r.kind}${r === chosen ? " selected" : ""}`);
      const name = el("td");
      name.append(el("strong", label(r.id, r.kind)));
      if (r.kind === "ai") name.append(el("span", t("aic.badge.ai"), "badge provisional"));
      if (r === chosen) name.append(el("span", t("aic.selected"), "badge"));
      let diff = "–";
      const v = r.kind === "ai" ? null : aiVersus(entry, r.kind === "model" ? r.id : r.kind);
      if (v?.verdict) diff = `${t(`aic.rel.${v.verdict}`)}: ${fmt(v.diff, true)} [${fmt(v.low, true)}; ${fmt(v.high, true)}]`;
      else if (v) diff = fmt(v.diff, true);
      tr.append(name, el("td", fmt(r.mae)), el("td", r.p_best == null ? "–" : `${Math.round(r.p_best * 100)} %`), el("td", diff));
      return tr;
    });
    table.replaceChildren(el("thead"), el("tbody"));
    table.tHead.append(head);
    table.tBodies[0].append(...body);
  }

  function renderChart(entry, unit) {
    const target = document.getElementById("aic-chart");
    if (!entry || entry.days < 2) {
      target.replaceChildren(el("p", t("aic.noChart")));
      return;
    }
    const ids = tableRows(entry).map((r) => r.id);
    const data = dailyRows(entry, ids);
    const kinds = Object.fromEntries(entry.series.map((s) => [s.id, s.kind]));
    const names2 = ids.map((id) => label(id, kinds[id]));
    // the text column up to 1200 px, without its side padding (as in compare-page.js)
    const column = document.querySelector(".content");
    const style = getComputedStyle(column);
    const width = Math.min(1200, column.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
    const day = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-US", { dateStyle: "long", timeZone: "UTC" });
    target.replaceChildren(Plot.plot({
      width,
      height: 300,
      marginLeft: 44,
      x: { label: null, type: "utc", tickFormat: dayTick(language) },
      y: { label: `MAE (${unit})`, grid: true, zero: true, tickFormat: numberTick(language) },
      color: { domain: names2, range: ids.map((id) => COLORS[kinds[id]]), legend: true },
      marks: [
        Plot.lineY(data, { x: "date", y: "mae", z: (r) => `${r.id}${r.segment}`, stroke: (r) => label(r.id, r.kind), strokeWidth: (r) => (r.kind === "model" ? 1.5 : 2.5), strokeDasharray: (r) => (r.kind === "mean" ? "5,4" : null),
          title: (r) => tipText(label(r.id, r.kind), day.format(r.date), `MAE ${fmt(r.mae)} ${unit}`), tip: true }),
        Plot.dot(data.filter((r) => r.mae != null), { x: "date", y: "mae", fill: (r) => label(r.id, r.kind), r: 2.5 }),
      ],
    }));
  }

  for (const [id, key, parse] of [
    ["aic-opponent", "opponent", String], ["aic-region", "region", String], ["aic-variable", "variable", String],
    ["aic-lead", "lead", Number], ["aic-sample", "sample", String],
  ]) {
    document.getElementById(id).addEventListener("change", (event) => {
      view[key] = parse(event.target.value);
      render();
    });
  }
  await render();
}
