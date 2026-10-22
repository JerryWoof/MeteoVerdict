// The Compare page's same-sample section (compare-ai.js has the pure parts).
import * as Plot from "@observablehq/plot";

import {
  SOURCES, LEADS, NOT_OPPONENTS, VARIABLES, aiStatus, availableModels, dailyRows, defaultOpponent, entryKey, formatView, hasAi,
  opponentSeries, pairVersus, parseView, regionGroups, seriesOf, threeWayPBest,
} from "./compare-ai.js";
import { dayTick, numberTick, tipText } from "./compare.js";
import { isDark, onThemeChange } from "./theme.js";
import { displayName } from "./tv.js";
import { dayCount, stationCount } from "./view.js";

// the three series of the page, the same colour everywhere (chart, table, verdict)
const COLORS = { ai: "var(--accent)", outlook: "#1f78b4", model: "#6a3d9a" };
const COLORS_DARK = { ai: "var(--accent)", outlook: "#3586bc", model: "#9473b6" };
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
  if (view.sample === "live" && !liveIndex) view.sample = "validation";
  const modelName = (id) => names[id] ?? valIndex?.models?.[id] ?? id;
  const label = (id, kind) => (kind === "ai" ? t("aic.ai") : kind === "outlook" ? t("aic.outlook") : modelName(id));
  const swatch = (kind) => Object.assign(el("span", null, "swatch"), { style: `background:${(isDark() ? COLORS_DARK : COLORS)[kind]}` });

  /** Fills the model menu: third-party models only (never our AI, our blend or the mean); one with too few shared hours is greyed out. */
  function fillOpponents(entry) {
    const have = new Set(availableModels(entry));
    const option = (value, text, disabled = false) => Object.assign(el("option", text), { value, selected: value === view.opponent, disabled });
    // the index lists the mean ("blend") and our blend ("combined") among the models: not third-party models
    const all = [...new Set([...Object.keys(valIndex?.models ?? {}), ...have])].filter((id) => !NOT_OPPONENTS.includes(id))
      .sort((x, y) => modelName(x).localeCompare(modelName(y), language));
    document.getElementById("aic-opponent").replaceChildren(...all.map((id) => option(id, have.has(id) ? modelName(id) : `${modelName(id)} (${t("aic.opp.few")})`, !have.has(id))));
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
      ...(groups.kraje.length ? [group(t("compare.kraje"), groups.kraje)] : []),

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
    let gone = false;
    if (entry && !opponentSeries(entry, view.opponent)) {
      // an unknown or unavailable model (or an old link naming our blend) falls back to the best model here
      gone = view.opponent !== "" && !NOT_OPPONENTS.includes(view.opponent);
      view.opponent = defaultOpponent(entry) ?? "";
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
    document.getElementById("aic-region-note").hidden = false;
    const unit = valIndex?.units?.[view.variable] ?? "";
    renderVerdict(entry, unit, gone);
    renderTable(entry, unit);
    renderChart(entry, unit);
    const url = new URL(window.location.href);
    url.searchParams.set("cmp", formatView(view));
    window.history.replaceState(null, "", url);
  }

  const VERDICT_KEY = { better: "betterVs", worse: "worseVs", same: "sameVs" };

  /** The three statements: AI against the model, our blend against the model, AI against our blend. */
  function renderVerdict(entry, unit, gone) {
    const node = document.getElementById("aic-verdict");
    const note = document.getElementById("aic-sample-note");
    const opp = entry ? opponentSeries(entry, view.opponent) : null;
    if (!entry || !hasAi(entry) || !opp) {
      node.className = "aic-verdict";
      node.replaceChildren(el("p", t(entry ? "aic.noVs" : "aic.noData")));
      note.textContent = "";
      return;
    }
    const model = label(opp.id, "model");
    const provisional = entry.small_sample || view.sample === "validation" || !status.verified;
    node.className = "aic-verdict";
    const lines = [];
    const numbers = el("div", null, "aic-numbers");
    for (const [kind, id] of [["ai", "ai"], ["outlook", "outlook"], ["model", opp.id]]) {
      const series = id === "ai" ? seriesOf(entry).find((s) => s.kind === "ai") : opponentSeries(entry, id);
      const box = el("div");
      const text = el("span", null, "label");
      text.append(swatch(kind), document.createTextNode(`${unit} · ${label(series.id, kind)}`));
      box.append(el("span", fmt(series.mae), "big"), text);
      numbers.append(box);
    }
    lines.push(numbers);
    for (const [a, b] of [["ai", opp.id], ["outlook", opp.id], ["ai", "outlook"]]) {
      const v = pairVersus(entry, a, b);
      if (!v) continue;
      // mid-sentence: "náš blend", not "Náš blend"
      const inText = (r) => (r.kind === "outlook" ? t("aic.outlookIn") : label(r.id, r.kind));
      const names = { a: inText(v.a), b: inText(v.b) };
      const row = el("div", null, `aic-pair ${v.verdict ?? "none"}`);
      const head = v.verdict ? t(`aic.pair.${VERDICT_KEY[v.verdict]}`, names) : t("aic.pair.noneVs", names);
      row.append(el("strong", head.charAt(0).toUpperCase() + head.slice(1)));
      row.append(el("div", v.verdict
        ? t("aic.pair.detail", { ...names, diff: fmt(v.diff, true), low: fmt(v.low, true), high: fmt(v.high, true), unit })
          + (v.pABetter != null ? " " + t("aic.pair.pBetter", { a: names.a, p: Math.round(v.pABetter * 100) }) : "")
        : t("aic.pair.detailNoInt", { ...names, diff: fmt(v.diff, true), unit }), "detail"));
      lines.push(row);
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

  /** Exactly three rows, best MAE first: the AI, our blend and the selected model. */
  function tableRows(entry) {
    const ai = seriesOf(entry).find((s) => s.kind === "ai");
    const rows = [ai, opponentSeries(entry, "outlook"), opponentSeries(entry, view.opponent)].filter(Boolean);
    return rows.sort((x, y) => x.mae - y.mae);
  }

  function renderTable(entry, unit) {
    const table = document.getElementById("aic-table");
    const opp = entry ? opponentSeries(entry, view.opponent) : null;
    if (!entry || !hasAi(entry) || !opp) {
      table.replaceChildren();
      return;
    }
    const model = label(opp.id, "model");
    const head = el("tr");
    for (const key of ["aic.col.name", "aic.col.mae", "aic.col.pbest", "aic.col.diff"]) head.append(el("th", t(key, { unit, model })));
    const shares = threeWayPBest(entry, opp.id, valIndex?.block_days ?? 4);
    const slot = { ai: 0, outlook: 1, model: 2 };
    const body = tableRows(entry).map((r) => {
      const tr = el("tr", null, r.kind);
      const name = el("td");
      name.append(swatch(r.kind), el("strong", label(r.id, r.kind)));
      if (r.kind === "ai") name.append(el("span", t("aic.badge.ai"), "badge provisional"));
      let diff = "–";
      if (r.kind !== "model") {
        const v = pairVersus(entry, r.kind, opp.id);
        if (v?.verdict) diff = `${t(`aic.rel.${v.verdict}`)}: ${fmt(v.diff, true)} [${fmt(v.low, true)}; ${fmt(v.high, true)}]`;
        else if (v) diff = fmt(v.diff, true);
      }
      tr.append(name, el("td", fmt(r.mae)), el("td", shares ? `${Math.round(shares[slot[r.kind]] * 100)} %` : "–"), el("td", diff));
      return tr;
    });
    table.replaceChildren(el("thead"), el("tbody"));
    table.tHead.append(head);
    table.tBodies[0].append(...body);
  }

  function renderChart(entry, unit) {
    const target = document.getElementById("aic-chart");
    if (!entry || entry.days < 2 || !hasAi(entry) || !opponentSeries(entry, view.opponent)) {
      target.replaceChildren(el("p", t("aic.noChart")));
      return;
    }
    const rows = tableRows(entry);
    const ids = rows.map((r) => r.id);
    const data = dailyRows(entry, ids);
    const kinds = Object.fromEntries(rows.map((s) => [s.id, s.kind]));
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
      color: { domain: names2, range: ids.map((id) => (isDark() ? COLORS_DARK : COLORS)[kinds[id]]), legend: true },
      marks: [
        Plot.lineY(data, { x: "date", y: "mae", z: (r) => `${r.id}${r.segment}`, stroke: (r) => label(r.id, r.kind), strokeWidth: 2.5,
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
  onThemeChange(() => render());
  await render();
}
