// The model selector of the measured page (measured.html): what a chosen model forecast
// at the station point (not the okres value, so no elevation error) next to what the
// station measured. Data: data/scores/station-fc/<station>.json (`mvd station-fc`,
// src/meteoverdict/station_fc.py: the single runs at the ~300 run stations, per day, lead
// day D+1 and D+2, with the measured values taken the same way). MeteoVerdict AI has its
// own files from the private engine (ai.zip): data/scores/ai/fc/stations/fc/<station>.json
// (the same layout with the model "ai", tmax, tmin and wind only, its own from/to: lined
// up by date) and ai/fc/stations/err-<day>.json for the maps. Pure helpers first, then the
// panels (station chart and the okres's stations table).

import * as Plot from "@observablehq/plot";

import { formatFixed, formatSigned } from "./station.js";

export const AI = "ai";
export const BLEND = "blend";
export const DEFAULT_MODEL = AI;
/** What the page shows instead of the default when the AI has no data at all. */
export const FALLBACK_MODEL = BLEND;
export const DEFAULT_LEAD = 1;
export const LEADS = [1, 2];
/** The station chart and summary show this many of the file's last days. */
export const CHART_DAYS = 7;
/** The values of the files, in the order of the selector: key, decimals, unit. */
export const VARIABLES = [
  { key: "tmax", digits: 1, unit: "°C" },
  { key: "tmin", digits: 1, unit: "°C" },
  { key: "r", digits: 1, unit: "mm" },
  { key: "wind", digits: 1, unit: "m/s" },
  { key: "gust", digits: 1, unit: "m/s" },
];

/** The values of the map's model-error colouring (the per-day files of `mvd station-fc`). */
export const ERROR_VARS = ["tmax", "tmin", "r", "wind"];
/** The map's dots start coloured by the model's error of the day's maximum ("none" in the hash: the measured values). */
export const DEFAULT_ERR = "tmax";

/** The single models in the order of the selector (others follow alphabetically). */
const MODEL_ORDER = [
  "chmi_aladin_cz_1km", "chmi_aladin_central_europe_2km", "dwd_icon_d2", "dwd_icon_eu", "dwd_icon",
  "ecmwf_ifs", "ecmwf_ifs025", "ecmwf_aifs025_single", "geosphere_arome_austria", "knmi_harmonie_arome_europe",
  "dmi_harmonie_arome_europe", "meteofrance_arpege_europe", "meteofrance_arpege_world",
  "ukmo_global_deterministic_10km", "ncep_gfs_global", "ncep_aigfs025", "gem_global", "gem_regional",
  "jma_gsm", "cma_grapes_global",
];

/** The Weather map's colour: the model's error ("bias": ±, "abs": absolute) or the measured values ("none"). */
export const WX_MODES = ["bias", "abs", "none"];
export const DEFAULT_WX = "bias";

const SUFFIX = /;m=([a-z0-9_]+)(?:;l=(\d))?(?:;e=([a-z]+))?(?:;w=([a-z]+))?$/;

/** "#day/…;m=dwd_icon_d2;l=2;e=tmax" → {hash: "#day/…", model, lead, err}; without the suffix
 * the choice of the page is left as it is (`model`/`lead` null); `err` (the map coloured by
 * that value's model error; null for "none") only when given. */
export function splitModelHash(hash) {
  const text = hash ?? "";
  const m = SUFFIX.exec(text);
  if (!m) return { hash: text, model: null, lead: null };
  const lead = Number(m[2] ?? DEFAULT_LEAD);
  let out = { hash: text.slice(0, m.index), model: m[1], lead: LEADS.includes(lead) ? lead : DEFAULT_LEAD };
  if (m[3] === "none") out = { ...out, err: null };
  else if (ERROR_VARS.includes(m[3])) out = { ...out, err: m[3] };
  // `wx`: how the Weather map is coloured (";w=abs", ";w=none"), only when given
  return WX_MODES.includes(m[4]) ? { ...out, wx: m[4] } : out;
}

/** The hash with the model choice appended (nothing for the defaults, to keep plain links plain). */
export function withModelHash(hash, { model, lead, err, wx = DEFAULT_WX }) {
  const base = splitModelHash(hash).hash || "#";
  const parts = [];
  if (model !== DEFAULT_MODEL || lead !== DEFAULT_LEAD || (err ?? null) !== DEFAULT_ERR || wx !== DEFAULT_WX) {
    parts.push(`;m=${model}`);
    if (lead !== DEFAULT_LEAD) parts.push(`;l=${lead}`);
    if ((err ?? null) !== DEFAULT_ERR) parts.push(`;e=${err ?? "none"}`);
    if (wx !== DEFAULT_WX) parts.push(`;w=${wx}`);
  }
  return `${base}${parts.join("")}`;
}

/**
 * The measured page's model choice after reading `hash` on one of its tabs (`weather`: the
 * Weather tab, else Stations). The model and lead come from the hash, the defaults when it has
 * none (Back to a plain link shows the plain view); of the two colours only the tab's own is
 * read (`wx` on Weather, `err` on Stations): the other tab's stays as chosen there.
 */
export function readModelChoice(hash, state, weather) {
  const { model, lead, err, wx } = splitModelHash(hash);
  const next = { ...state, model: model ?? DEFAULT_MODEL, lead: model ? lead : DEFAULT_LEAD };
  if (weather) next.wx = wx ?? DEFAULT_WX;
  else next.err = err === undefined ? DEFAULT_ERR : err;
  return next;
}

/** The choice as a tab's hash carries it: the other tab's colour left out (";e=none" in a Weather link meant nothing there). */
export function tabChoice(state, weather) {
  return weather ? { ...state, err: DEFAULT_ERR } : { ...state, wx: DEFAULT_WX };
}

/** The selector's options: [{id, name}], MeteoVerdict AI, the blend, then the models. */
export function modelOptions(index, t) {
  const names = index?.models ?? {};
  const rank = (id) => (MODEL_ORDER.includes(id) ? MODEL_ORDER.indexOf(id) : MODEL_ORDER.length);
  const singles = Object.keys(names)
    .filter((id) => id !== BLEND)
    .sort((a, b) => rank(a) - rank(b) || (a < b ? -1 : 1));
  return [
    { id: AI, name: t("fc.model.ai") },
    { id: BLEND, name: t("fc.model.blend") },
    ...singles.map((id) => ({ id, name: names[id] })),
  ];
}

/** How big a difference is, as the okres panel's: small / medium / large (°C, m/s; mm). */
export function sizeClass(e, unit) {
  const a = Math.abs(e);
  return a <= 1 ? "small" : a <= (unit === "mm" ? 5 : 3) ? "medium" : "large";
}

const DAY_MS = 86_400_000;
const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY_MS).toISOString().slice(0, 10);

/**
 * The measured and forecast values of one variable over the file's days:
 * {days: ["2026-10-01", …], obs: [value|null], fc: [value|null], err: [fc − obs | null]}.
 * `ai` (the AI's file, optional) supplies the model "ai"; its days are lined up by date
 * (its window is its own).
 */
export function compareSeries(doc, ai, model, lead, key) {
  if (!doc) return null;
  const source = model === AI ? ai : doc;
  const fc = source?.series?.[key]?.[String(lead)]?.[model] ?? null;
  const obs = doc.obs?.[key] ?? null;
  const n = Math.round((Date.parse(`${doc.to}T00:00:00Z`) - Date.parse(`${doc.from}T00:00:00Z`)) / DAY_MS) + 1;
  const days = Array.from({ length: n }, (_, i) => addDays(doc.from, i));
  const at = (list, i) => (i >= 0 ? list?.[i] ?? null : null);
  // the AI's file starts on its own day: day i of the station file is day i + shift of it
  const shift = source !== doc && source?.from ? Math.round((Date.parse(`${doc.from}T00:00:00Z`) - Date.parse(`${source.from}T00:00:00Z`)) / DAY_MS) : 0;
  const rows = days.map((_, i) => {
    const o = at(obs, i);
    const f = at(fc, i + shift);
    return { o, f, e: o == null || f == null ? null : Math.round((f - o) * 10) / 10 };
  });
  return { days, obs: rows.map((r) => r.o), fc: rows.map((r) => r.f), err: rows.map((r) => r.e), hasModel: fc != null };
}

/** The last `n` days of a series (compareSeries), or the series itself when it is null. */
export function lastDays(series, n = CHART_DAYS) {
  if (!series) return series;
  const cut = (list) => list.slice(-n);
  return { ...series, days: cut(series.days), obs: cut(series.obs), fc: cut(series.fc), err: cut(series.err) };
}

/** Over the days with both values: {n, mae, bias} (null without any). */
export function errorSummary(series) {
  const errors = (series?.err ?? []).filter((e) => e != null);
  if (!errors.length) return null;
  const sum = errors.reduce((a, b) => a + b, 0);
  return { n: errors.length, mae: errors.reduce((a, b) => a + Math.abs(b), 0) / errors.length, bias: sum / errors.length };
}

/**
 * One station's model error (model minus measured) for a day, from the per-day error file:
 * {byId: Map(station id → error | null), hasModel}; `hasModel` false when the file has no
 * values of the model (MeteoVerdict AI: none published; or no model at all that day).
 */
export function errorLookup(doc, model, lead, key) {
  const column = doc?.e?.[key]?.[String(lead)]?.[model];
  if (!doc || !column || !Array.isArray(doc.stations)) return { byId: new Map(), hasModel: false };
  const scale = doc.scale ?? 10;
  return { byId: new Map(doc.stations.map((id, i) => [id, column[i] == null ? null : column[i] / scale])), hasModel: true };
}

/** The error value the Weather map shows for a colour layer and part of day (null: no model error exists). */
export function errorKeyFor(layer, part) {
  if (layer === "temperature") return part === "night" ? "tmin" : "tmax";
  if (layer === "precipitation") return "r";
  return layer === "wind" ? "wind" : null;
}

/**
 * The model's error per okres: the mean error (bias) and mean absolute error of its stations
 * with a value, {code → {n, bias, mae}}. `stations`: [{id, okres}], `codeOf` maps a station's
 * okres name to the okres code (null: unknown).
 */
export function okresErrors(byId, stations, codeOf) {
  const sums = new Map();
  for (const s of stations) {
    const e = byId.get(s.id);
    const code = e == null ? null : codeOf(s.okres);
    if (!code) continue;
    const a = sums.get(code) ?? { n: 0, sum: 0, abs: 0 };
    a.n += 1;
    a.sum += e;
    a.abs += Math.abs(e);
    sums.set(code, a);
  }
  return new Map([...sums].map(([code, a]) => [code, { n: a.n, bias: a.sum / a.n, mae: a.abs / a.n }]));
}

/**
 * @param {object} o
 * @param {(path: string) => Promise<object|null>} o.getJson
 * @param {Function} o.t i18n
 * @param {string} o.language
 */
export function createModelCompare({ getJson, t, language }) {
  const cache = new Map();
  const once = (key, load) => {
    if (!cache.has(key)) cache.set(key, load());
    return cache.get(key);
  };
  const loadIndex = () => once("index", () => getJson("data/scores/station-fc/index.json"));
  const loadStation = (id) => once(`s|${id}`, () => getJson(`data/scores/station-fc/${id}.json`));
  const loadAi = (id) => once(`a|${id}`, () => getJson(`data/scores/ai/fc/stations/fc/${id}.json`));

  // the AI's error files come with its station files (ai.zip)
  const loadErrors = (day, model = state.model) =>
    model === AI
      ? once(`ae|${day}`, () => getJson(`data/scores/ai/fc/stations/err-${day}.json`))
      : once(`e|${day}`, () => getJson(`data/scores/station-fc/err-${day}.json`));

  // `err`: the value whose model error colours the map's dots (null: the measured values)
  const state = { model: DEFAULT_MODEL, lead: DEFAULT_LEAD, key: "tmax", err: DEFAULT_ERR, wx: DEFAULT_WX };
  // the page's decimal sign, never "-0", a true minus sign
  const fmt = (v, digits = 1) => formatFixed(v, language, digits);
  const signed = (v, digits = 1) => (v == null ? "–" : formatSigned(v, language, digits));
  const dayFormat = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { day: "numeric", month: "numeric", timeZone: "UTC" });
  const dayText = (iso) => dayFormat.format(new Date(`${iso}T00:00:00Z`));
  const variableOf = (key) => VARIABLES.find((v) => v.key === key) ?? VARIABLES[0];

  function element(tag, text, className) {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (className) e.className = className;
    return e;
  }

  /** Why a model has nothing to show for a station: {text}; or null when it has values. */
  async function unavailable(id, model, lead, key, doc, ai) {
    const index = await loadIndex();
    if (!index) return t("fc.noData");
    if (!doc) return t("fc.noStation");
    if (model === AI && !ai) return t("fc.noAi");
    const series = compareSeries(doc, ai, model, lead, key);
    if (!series?.hasModel) {
      return model === AI ? t("fc.noAi") : t("fc.noModelValue", { model: index.models?.[model] ?? model, value: t(`fc.var.${key}`).toLowerCase() });
    }
    return null;
  }

  /** The station's chart and table of last days, in a section; filled when the files arrive. */
  function stationSection(id, { onChange } = {}) {
    const box = element("section", null, "model-compare");
    box.append(element("h3", t("fc.title")), element("p", t("fc.loading"), "model-note"));
    const draw = async () => {
      // most stations have no stored forecasts (the index lists the ~300 that do): say so,
      // without asking for a file that is not there or offering values that lead nowhere
      const listed = await loadIndex();
      if (listed && !listed.stations?.includes(id)) {
        box.replaceChildren(element("h3", t("fc.title")), element("p", t("fc.noStation"), "model-note missing"));
        return;
      }
      const [index, doc, ai] = await Promise.all([loadIndex(), loadStation(id), state.model === AI ? loadAi(id) : null]);
      const { model, lead, key } = state;
      const name = modelOptions(index, t).find((m) => m.id === model)?.name ?? model;
      const children = [element("h3", t("fc.title"))];
      const picker = element("div", null, "segmented model-var");
      picker.setAttribute("aria-label", t("fc.value"));
      for (const v of VARIABLES) {
        const button = element("button", t(`fc.var.${v.key}`));
        button.type = "button";
        button.setAttribute("aria-pressed", String(v.key === key));
        button.addEventListener("click", () => {
          state.key = v.key;
          onChange?.();
          draw();
        });
        picker.append(button);
      }
      children.push(picker);
      const series = lastDays(compareSeries(doc, ai, model, lead, key));
      const reason = await unavailable(id, model, lead, key, doc, ai);
      if (doc && series) {
        const info = errorSummary(series);
        const v = variableOf(key);
        if (reason) children.push(element("p", reason, "model-note missing"));
        else {
          children.push(
            element("p", info ? t("fc.summary", { model: name, lead, mae: fmt(info.mae, v.digits), unit: v.unit, bias: signed(info.bias, v.digits), n: info.n }) : t("fc.noOverlap"), "model-note"),
          );
        }
        children.push(chart(series, v, name), table(series, v), element("p", t("fc.note", { lead }), "model-note"));
        if (model === AI) children.push(element("p", t("fc.aiSample"), "model-note"));
      } else {
        children.push(element("p", reason ?? t("fc.noStation"), "model-note missing"));
      }
      box.replaceChildren(...children);
    };
    draw();
    return box;
  }

  /** Observed line and the model's line over the days (Observable Plot). */
  function chart(series, v, name) {
    const points = [];
    // gaps stay gaps (null breaks the line)
    series.days.forEach((day, i) => {
      const date = new Date(`${day}T12:00:00Z`);
      points.push({ date, value: series.obs[i], series: t("fc.measured") }, { date, value: series.fc[i], series: name });
    });
    const frame = element("div", null, "model-chart");
    if (!points.some((p) => p.value != null)) return frame;
    const width = Math.max(260, Math.min(460, (typeof window === "undefined" ? 360 : window.innerWidth) - 56));
    const plot = Plot.plot({
      width,
      height: 190,
      marginLeft: 36,
      style: { fontSize: "11px" },
      x: { label: null, type: "utc", ticks: 5, tickFormat: (d) => dayText(d.toISOString().slice(0, 10)) },
      y: { label: v.unit, grid: true },
      color: { domain: [t("fc.measured"), name], range: ["var(--ink)", "var(--model)"], legend: true },
      marks: [
        Plot.lineY(points, { x: "date", y: "value", stroke: "series", strokeWidth: 1.6 }),
        Plot.dot(points, { x: "date", y: "value", stroke: "series", r: 2 }),
        Plot.tip(points, Plot.pointerX({ x: "date", y: "value", title: (p) => `${dayText(p.date.toISOString().slice(0, 10))}\n${p.series}: ${fmt(p.value, v.digits)} ${v.unit}` })),
      ],
    });
    frame.append(plot);
    return frame;
  }

  /** The last days: measured, model and the difference. */
  function table(series, v) {
    const wrap = element("div", null, "table-scroll");
    const tbl = element("table", null, "compare-table matrix model-table");
    const head = element("tr");
    for (const key of ["fc.col.day", "fc.col.measured", "fc.col.model", "fc.col.diff"]) head.append(element("th", t(key), key === "fc.col.day" ? null : "num"));
    tbl.append(head);
    const last = series.days.map((_, i) => i).filter((i) => series.obs[i] != null || series.fc[i] != null).slice(-7).reverse();
    for (const i of last) {
      const tr = element("tr");
      const e = series.err[i];
      tr.append(element("th", dayText(series.days[i])), element("td", fmt(series.obs[i], v.digits), "num"), element("td", fmt(series.fc[i], v.digits), "num"));
      const cell = element("td", signed(e, v.digits), "num");
      if (e != null) cell.classList.add("delta", sizeClass(e, v.unit));
      tr.append(cell);
      tbl.append(tr);
    }
    wrap.append(tbl);
    return wrap;
  }

  /** The okres's stations on a day: measured and the model's value for the chosen value, with
   * a link to each station's own chart. `stations`: [{id, name, elevation}]. */
  function okresSection(stations, day, openStation) {
    const box = element("section", null, "model-compare okres-model");
    box.append(element("h3", t("fc.okresTitle")), element("p", t("fc.loading"), "model-note"));
    const draw = async () => {
      const index = await loadIndex();
      const { model, lead, key } = state;
      const name = modelOptions(index, t).find((m) => m.id === model)?.name ?? model;
      const v = variableOf(key);
      const children = [element("h3", t("fc.okresTitle"))];
      const picker = element("div", null, "segmented model-var");
      for (const variable of VARIABLES.slice(0, 3)) {
        const button = element("button", t(`fc.var.${variable.key}`));
        button.type = "button";
        button.setAttribute("aria-pressed", String(variable.key === key));
        button.addEventListener("click", () => {
          state.key = variable.key;
          draw();
        });
        picker.append(button);
      }
      children.push(picker);
      if (!index) {
        box.replaceChildren(...children, element("p", t("fc.noData"), "model-note missing"));
        return;
      }
      const covered = stations.filter((s) => index.stations?.includes(s.id));
      if (!covered.length) {
        box.replaceChildren(...children, element("p", t("fc.noOkresStations"), "model-note missing"));
        return;
      }
      const docs = await Promise.all(covered.map((s) => Promise.all([loadStation(s.id), model === AI ? loadAi(s.id) : null])));
      const tbl = element("table", null, "compare-table matrix model-table");
      const head = element("tr");
      // the numbers' headings right-aligned over them
      for (const col of ["fc.col.station", "fc.col.measured", "fc.col.model", "fc.col.diff"]) head.append(element("th", t(col), col === "fc.col.station" ? null : "num"));
      tbl.append(head);
      let anyValue = false;
      covered.forEach((s, n) => {
        const [doc, ai] = docs[n];
        const series = compareSeries(doc, ai, model, lead, key);
        const i = series?.days.indexOf(day) ?? -1;
        const tr = element("tr");
        const th = element("th");
        const link = element("a", s.name ?? s.id);
        link.href = `#kinds/${encodeURIComponent(s.id)}`;
        link.addEventListener("click", (event) => openStation?.(s.id, event));
        th.append(link, element("small", s.elevation == null ? "" : ` ${Math.round(s.elevation)} m`));
        const o = i >= 0 ? series.obs[i] : null;
        const f = i >= 0 ? series.fc[i] : null;
        if (f != null) anyValue = true;
        tr.append(th, element("td", fmt(o, v.digits), "num"), element("td", f == null ? t("fc.none") : fmt(f, v.digits), "num"));
        const e = i >= 0 ? series.err[i] : null;
        const cell = element("td", signed(e, v.digits), "num");
        if (e != null) cell.classList.add("delta", sizeClass(e, v.unit));
        tr.append(cell);
        tbl.append(tr);
      });
      children.push(element("p", t("fc.okresIntro", { model: name, lead, value: t(`fc.var.${key}`).toLowerCase(), unit: v.unit }), "model-note"));
      const wrap = element("div", null, "table-scroll");
      wrap.append(tbl);
      children.push(wrap);
      if (!anyValue) {
        children.push(element("p", model === AI ? t("fc.noAi") : t("fc.noModelValue", { model: name, value: t(`fc.var.${key}`).toLowerCase() }), "model-note missing"));
      }
      if (model === AI) children.push(element("p", t("fc.aiSample"), "model-note"));
      const skipped = stations.length - covered.length;
      if (skipped > 0) children.push(element("p", t("fc.skipped", { n: skipped }), "model-note"));
      box.replaceChildren(...children);
    };
    draw();
    return box;
  }

  return { state, loadIndex, loadErrors, stationSection, okresSection, options: async () => modelOptions(await loadIndex(), t) };
}
