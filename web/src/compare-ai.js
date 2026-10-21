// The Compare page's same-sample section: MeteoVerdict AI, our blend (the Outlook), the
// mean of all models and every model, ranked on the same station-days (files written by
// `mvd blend-test --compare-zip`, and for the live sample by the AI's daily verification).
// The pure helpers; the section itself is drawn by compare-ai-view.js.

/** Where the files are: the AI's own run (with MeteoVerdict AI) first, else the public one. */
export const SOURCES = { validation: ["data/scores/ai/fc/compare", "data/compare"], live: ["data/scores/ai/fc/compare/live"] };
// only what the AI forecasts: a comparison without it is the models-page's job
export const VARIABLES = ["temperature_2m", "wind_speed_10m"];
export const LEADS = [1, 2, 3, 4, 5];
/** The AI needs this many live days measured before it may be called verified (the AI tab's rule). */
export const MIN_LIVE_DAYS = 28;

/** "temperature_2m/1" */
export const entryKey = (variable, lead) => `${variable}/${lead}`;

/** The series of an entry, best first, with a display kind (model, mean, outlook, ai). */
export function seriesOf(entry) {
  return entry?.series ?? [];
}

/** Does the entry have the AI in it? */
export const hasAi = (entry) => seriesOf(entry).some((s) => s.kind === "ai");

/**
 * A series against our blend (the Outlook): "better", "worse" or "same" (≈): better or
 * worse only when the 95 % block-bootstrap interval of the difference excludes 0 and the
 * Diebold-Mariano test agrees (p < 0.05), as the ranking's ties; null without it.
 */
export function relation(series) {
  const v = series?.vs_outlook;
  if (!v || v.diff == null || v.low == null || v.high == null) return null;
  const significant = (v.p ?? 1) < 0.05;
  const verdict = significant && v.high < 0 ? "better" : significant && v.low > 0 ? "worse" : "same";
  return { verdict, diff: v.diff, low: v.low, high: v.high };
}

/** The AI against our blend, with the AI's series. */
export function aiVerdict(entry) {
  const ai = seriesOf(entry).find((s) => s.kind === "ai");
  const r = relation(ai);
  return r ? { ...r, ai, mae: ai.mae } : null;
}

/** The series with the best MAE among the plain models (not the mean, the blend or the AI). */
export function bestModel(entry) {
  return seriesOf(entry).find((s) => s.kind === "model") ?? null;
}

/** The opponents that are not one model: our blend, the mean of all models, the best model. */
export const GROUP_OPPONENTS = ["outlook", "mean", "best"];

/** The series the AI is compared against: "outlook", "mean", "best" (best plain model) or a model id. */
export function opponentSeries(entry, opponent) {
  const series = seriesOf(entry);
  if (opponent === "best") return bestModel(entry);
  if (opponent === "outlook" || opponent === "mean") return series.find((s) => s.kind === opponent) ?? null;
  return series.find((s) => s.id === opponent && s.kind === "model") ?? null;
}

/** Model ids with a value on every day of the AI's sample (the rest overlap too little). */
export const availableModels = (entry) => seriesOf(entry).filter((s) => s.kind === "model").map((s) => s.id);

/**
 * The AI against one opponent on the same sample. diff is AI minus opponent (negative: the
 * AI is better) with its 95 % interval; verdict "better", "worse" or "same" (no clear
 * winner: the interval crosses zero or the Diebold-Mariano test disagrees); pAiBetter is
 * the share of bootstrap resamples where the AI has the lower MAE. Null `verdict` when an
 * older file has no interval for this opponent (then only the MAE difference is given).
 */
export function aiVersus(entry, opponent) {
  const ai = seriesOf(entry).find((s) => s.kind === "ai");
  const opp = opponentSeries(entry, opponent);
  if (!ai || !opp) return null;
  const base = { ai, opponent: opp, diff: ai.mae - opp.mae, low: null, high: null, p: null, pAiBetter: null, verdict: null };
  let v = null;
  if (opp.kind === "outlook") {
    const r = ai.vs_outlook;
    if (r?.diff != null) v = { diff: r.diff, low: r.low, high: r.high, p: r.p ?? 1, pAiBetter: r.p_lower ?? null };
  } else {
    const r = opp.vs_ai;
    if (r?.diff != null) v = { diff: -r.diff, low: -r.high, high: -r.low, p: r.p ?? 1, pAiBetter: r.p_lower != null ? 1 - r.p_lower : null };
  }
  if (!v || v.low == null || v.high == null) return base;
  const significant = v.p < 0.05;
  const verdict = significant && v.high < 0 ? "better" : significant && v.low > 0 ? "worse" : "same";
  return { ...base, ...v, verdict };
}

/**
 * The AI's standing for the banner: "live" with enough days is verified; anything else
 * (no live days, few days, or only the validation sample) is provisional.
 * `status` is ai.json's test block ({measured_hours, days}).
 */
export function aiStatus(status, minDays = MIN_LIVE_DAYS) {
  const days = status?.days ?? 0;
  const hours = status?.measured_hours ?? 0;
  return { days, hours, verified: days >= minDays, need: minDays };
}

/**
 * The rows of the comparison, in a fixed order: the AI, our blend, the mean of all
 * models and the best single model; each with its relation to our blend.
 */
export function compareRows(entry) {
  const series = seriesOf(entry);
  const best = bestModel(entry);
  const pick = [
    series.find((s) => s.kind === "ai"), series.find((s) => s.kind === "outlook"),
    series.find((s) => s.kind === "mean"), best,
  ];
  return pick.filter(Boolean).map((s) => ({ ...s, relation: relation(s) }));
}

/** Plot rows of the error over time: one per series and date (mae null: no value). */
export function dailyRows(entry, ids) {
  const dates = entry?.date_list ?? [];
  const out = [];
  for (const s of seriesOf(entry)) {
    if (!ids.includes(s.id)) continue;
    let segment = 0;
    s.daily.forEach((mae, i) => {
      const date = new Date(`${dates[i]}T12:00:00Z`);
      // a gap of days with no common sample starts a new line segment instead of being bridged
      if (i > 0 && date - new Date(`${dates[i - 1]}T12:00:00Z`) > 1.5 * 86400000) segment += 1;
      out.push({ id: s.id, kind: s.kind, date, mae, segment });
    });
  }
  return out;
}

/** The series to draw by default: the AI, our blend, the mean, the best model. */
export const defaultSeries = (entry) => compareRows(entry).map((s) => s.id);

/** Regions of an index.json: {cz, kraje: [[code, name]], okresy: [[code, name]]} by name. */
export function regionGroups(index, language = "cs") {
  const sort = (rows) => rows.sort((a, b) => a[1].localeCompare(b[1], language));
  // only the regions with the AI (older files have no flag: all)
  const flagged = Object.values(index?.regions ?? {}).some((r) => r.length > 2);
  const rows = Object.entries(index?.regions ?? {}).filter(([, r]) => !flagged || r[2]);
  const pick = (level) => sort(rows.filter(([, [l]]) => l === level).map(([code, [, name]]) => [code, name]));
  return { cz: rows.some(([code]) => code === "cz"), kraje: pick("kraj"), okresy: pick("okres") };
}

/** Series ids that are ours or a summary: never the selected model. */
export const NOT_OPPONENTS = ["outlook", "mean", "best", "blend", "combined", "meteoverdict_ai"];

/** The model that starts selected: the best plain model on the AI's sample. */
export const defaultOpponent = (entry) => bestModel(entry)?.id ?? null;

/**
 * Any two of the three series (the AI, our blend, one model) against each other on the same
 * sample: a and b are "ai", "outlook" or a model id. diff is a minus b (negative: a is
 * better) with its 95 % interval; verdict "better", "worse" or "same" (≈) as in aiVersus;
 * pABetter is the share of bootstrap resamples where a has the lower MAE.
 */
export function pairVersus(entry, a, b) {
  const find = (id) => (id === "ai" ? seriesOf(entry).find((s) => s.kind === "ai") : id === "outlook" ? opponentSeries(entry, "outlook") : opponentSeries(entry, id));
  const x = find(a);
  const y = find(b);
  if (!x || !y || x === y) return null;
  const base = { a: x, b: y, diff: x.mae - y.mae, low: null, high: null, p: null, pABetter: null, verdict: null };
  // the files hold ai-vs-blend (on the AI), model-vs-ai and model-vs-blend (on the model)
  const flip = (r) => (r?.diff != null && r.low != null && r.high != null
    ? { diff: -r.diff, low: -r.high, high: -r.low, p: r.p ?? 1, pABetter: r.p_lower != null ? 1 - r.p_lower : null } : null);
  const direct = (r) => (r?.diff != null && r.low != null && r.high != null
    ? { diff: r.diff, low: r.low, high: r.high, p: r.p ?? 1, pABetter: r.p_lower ?? null } : null);
  const key = (k1, k2) => `${k1}/${k2}`;
  const kinds = key(x.kind, y.kind);
  const v = {
    "ai/outlook": () => direct(x.vs_outlook),
    "outlook/ai": () => flip(y.vs_outlook),
    "ai/model": () => flip(y.vs_ai),
    "model/ai": () => direct(x.vs_ai),
    "outlook/model": () => flip(y.vs_outlook),
    "model/outlook": () => direct(x.vs_outlook),
  }[kinds]?.();
  if (!v) return base;
  const significant = v.p < 0.05;
  return { ...base, ...v, verdict: significant && v.high < 0 ? "better" : significant && v.low > 0 ? "worse" : "same" };
}

/**
 * The chance that each of the three (AI, blend, the model) has the lowest MAE of the three
 * (block bootstrap over the days, as the files' own p_best but among these three only, so the
 * shares add up to 100 %). Days where one of them has no value are left out. Null without a sample.
 */
export function threeWayPBest(entry, modelId, blockDays = 4, draws = 2000) {
  const rows = ["ai", "outlook", modelId].map((id) => (id === "ai" ? seriesOf(entry).find((s) => s.kind === "ai") : id === "outlook" ? opponentSeries(entry, "outlook") : opponentSeries(entry, id)));
  if (rows.some((r) => !r?.daily)) return null;
  const days = rows[0].daily.map((_, i) => i).filter((i) => rows.every((r) => r.daily[i] != null));
  if (days.length < 2) return null;
  let seed = 12345;
  const random = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const wins = [0, 0, 0];
  const block = Math.max(1, Math.min(blockDays, days.length));
  for (let d = 0; d < draws; d += 1) {
    const sums = [0, 0, 0];
    let n = 0;
    while (n < days.length) {
      const start = Math.floor(random() * days.length);
      for (let k = 0; k < block && n < days.length; k += 1, n += 1) {
        const day = days[(start + k) % days.length];
        rows.forEach((r, j) => { sums[j] += r.daily[day]; });
      }
    }
    wins[sums.indexOf(Math.min(...sums))] += 1;
  }
  return wins.map((w) => w / draws);
}

/** "temperature_2m.1.validation.cz.outlook" (the URL's ?cmp=) → a view; unknown parts fall back. */
export function parseView(text, regions) {
  const [variable, lead, sample, region, opponent] = String(text ?? "").split(".");
  return {
    variable: VARIABLES.includes(variable) ? variable : "temperature_2m",
    lead: LEADS.includes(Number(lead)) ? Number(lead) : 1,
    sample: sample === "live" ? "live" : "validation",
    region: region && region in (regions ?? { cz: 1 }) ? region : "cz",
    // a model id is checked against the sample later (it may not be there): only its shape here
    // "" = the default (the best model in the area); our own series are no opponents, so
    // old links that named the blend, the mean or "best" fall back to it
    opponent: /^[a-z0-9_]+$/.test(opponent ?? "") && !NOT_OPPONENTS.includes(opponent) ? opponent : "",
  };
}

export const formatView = (v) => `${v.variable}.${v.lead}.${v.sample}.${v.region}.${v.opponent}`;
