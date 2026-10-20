// The model selector of the measured page (measured.html): what a chosen model forecast
// at the station point (not the okres value, so no elevation error) next to what the
// station measured. Data: data/scores/station-fc/<station>.json (`mvd station-fc`,
// src/meteoverdict/station_fc.py: the single runs at the ~300 run stations, per day, lead
// day D+1 and D+2, with the measured values taken the same way). MeteoVerdict AI has no
// values published yet: data/scores/ai/fc/stations/fc/<station>.json would have the same
// layout with the model "ai" (absent: the page says so). Pure helpers first, then the
// panels (station chart and the okres's stations table).

import * as Plot from "@observablehq/plot";

export const AI = "ai";
export const BLEND = "blend";
export const DEFAULT_MODEL = AI;
export const DEFAULT_LEAD = 1;
export const LEADS = [1, 2];
/** The values of the files, in the order of the selector: key, decimals, unit. */
export const VARIABLES = [
  { key: "tmax", digits: 1, unit: "°C" },
  { key: "tmin", digits: 1, unit: "°C" },
  { key: "r", digits: 1, unit: "mm" },
  { key: "wind", digits: 1, unit: "m/s" },
  { key: "gust", digits: 1, unit: "m/s" },
];

/** The single models in the order of the selector (others follow alphabetically). */
const MODEL_ORDER = [
  "chmi_aladin_cz_1km", "chmi_aladin_central_europe_2km", "dwd_icon_d2", "dwd_icon_eu", "dwd_icon",
  "ecmwf_ifs", "ecmwf_ifs025", "ecmwf_aifs025_single", "geosphere_arome_austria", "knmi_harmonie_arome_europe",
  "dmi_harmonie_arome_europe", "meteofrance_arpege_europe", "meteofrance_arpege_world",
  "ukmo_global_deterministic_10km", "ncep_gfs_global", "ncep_aigfs025", "gem_global", "gem_regional",
  "jma_gsm", "cma_grapes_global",
];

const SUFFIX = /;m=([a-z0-9_]+)(?:;l=(\d))?$/;

/** "#day/…;m=dwd_icon_d2;l=2" → {hash: "#day/…", model, lead}; without the suffix the
 * defaults (the choice of the page is then left as it is: `model`/`lead` null). */
export function splitModelHash(hash) {
  const text = hash ?? "";
  const m = SUFFIX.exec(text);
  if (!m) return { hash: text, model: null, lead: null };
  const lead = Number(m[2] ?? DEFAULT_LEAD);
  return { hash: text.slice(0, m.index), model: m[1], lead: LEADS.includes(lead) ? lead : DEFAULT_LEAD };
}

/** The hash with the model choice appended (nothing for the defaults, to keep plain links plain). */
export function withModelHash(hash, { model, lead }) {
  const base = splitModelHash(hash).hash || "#";
  const parts = [];
  if (model !== DEFAULT_MODEL || lead !== DEFAULT_LEAD) {
    parts.push(`;m=${model}`);
    if (lead !== DEFAULT_LEAD) parts.push(`;l=${lead}`);
  }
  return `${base}${parts.join("")}`;
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
 * `ai` (the AI's file, optional) supplies the model "ai".
 */
export function compareSeries(doc, ai, model, lead, key) {
  if (!doc) return null;
  const source = model === AI ? ai : doc;
  const fc = source?.series?.[key]?.[String(lead)]?.[model] ?? null;
  const obs = doc.obs?.[key] ?? null;
  const n = Math.round((Date.parse(`${doc.to}T00:00:00Z`) - Date.parse(`${doc.from}T00:00:00Z`)) / DAY_MS) + 1;
  const days = Array.from({ length: n }, (_, i) => addDays(doc.from, i));
  const at = (list, i) => list?.[i] ?? null;
  const rows = days.map((_, i) => {
    const o = at(obs, i);
    const f = at(fc, i);
    return { o, f, e: o == null || f == null ? null : Math.round((f - o) * 10) / 10 };
  });
  return { days, obs: rows.map((r) => r.o), fc: rows.map((r) => r.f), err: rows.map((r) => r.e), hasModel: fc != null };
}

/** Over the days with both values: {n, mae, bias} (null without any). */
export function errorSummary(series) {
  const errors = (series?.err ?? []).filter((e) => e != null);
  if (!errors.length) return null;
  const sum = errors.reduce((a, b) => a + b, 0);
  return { n: errors.length, mae: errors.reduce((a, b) => a + Math.abs(b), 0) / errors.length, bias: sum / errors.length };
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

  const state = { model: DEFAULT_MODEL, lead: DEFAULT_LEAD, key: "tmax" };
  const fmt = (v, digits = 1) =>
    v == null ? "–" : v.toLocaleString(language, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const signed = (v, digits = 1) => (v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v), digits)}`);
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
      const series = compareSeries(doc, ai, model, lead, key);
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
      color: { domain: [t("fc.measured"), name], range: ["#1d2329", "#2b7bd1"], legend: true },
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
    for (const key of ["fc.col.day", "fc.col.measured", "fc.col.model", "fc.col.diff"]) head.append(element("th", t(key)));
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
      for (const col of ["fc.col.station", "fc.col.measured", "fc.col.model", "fc.col.diff"]) head.append(element("th", t(col)));
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
      const skipped = stations.length - covered.length;
      if (skipped > 0) children.push(element("p", t("fc.skipped", { n: skipped }), "model-note"));
      box.replaceChildren(...children);
    };
    draw();
    return box;
  }

  return { state, loadIndex, stationSection, okresSection, options: async () => modelOptions(await loadIndex(), t) };
}
