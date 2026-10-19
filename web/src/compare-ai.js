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

/** "temperature_2m.1.validation.cz" (the URL's ?cmp=) → a view; unknown parts fall back. */
export function parseView(text, regions) {
  const [variable, lead, sample, region] = String(text ?? "").split(".");
  return {
    variable: VARIABLES.includes(variable) ? variable : "temperature_2m",
    lead: LEADS.includes(Number(lead)) ? Number(lead) : 1,
    sample: sample === "live" ? "live" : "validation",
    region: region && region in (regions ?? { cz: 1 }) ? region : "cz",
  };
}

export const formatView = (v) => `${v.variable}.${v.lead}.${v.sample}.${v.region}`;
