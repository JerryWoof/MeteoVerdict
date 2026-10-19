// The monthly accuracy report (report.html): numbers from `mvd monthly-report`
// (site/reports/YYYY-MM.json) turned into the sentences and bars the page shows.

export const VARIABLES = ["temperature_2m", "wind_speed_10m", "precipitation_24h"];

/** "2026-09" → "září 2026" / "September 2026". */
export function monthLabel(month, language) {
  const [y, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", {
    month: "long", year: "numeric", timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, 15)));
}

/** "clear" (nobody tied with the best), "tie" (some are) or "none" (no ranked model). */
export function winnerKind(lead) {
  if (!lead?.best) return "none";
  return lead.clear_winner ? "clear" : "tie";
}

/** How the mean of all models compares with the best single model: "better", "worse" or
 * "same" (the 95 % interval of the difference includes zero). */
export function meanVerdict(lead) {
  const mean = lead?.mean_of_all;
  if (!mean || mean.ci_high == null || mean.ci_low == null) return null;
  if (mean.ci_high < 0) return "better";
  if (mean.ci_low > 0) return "worse";
  return "same";
}

/** The bars of one chart: every model of the lead with its share of the largest error. */
export function barRows(lead) {
  const models = lead?.models ?? [];
  const top = Math.max(0, ...models.map((m) => m.mae ?? 0));
  const tied = new Set(lead?.tied_with_best ?? []);
  return models.map((m) => ({
    model: m.model,
    name: m.name,
    mae: m.mae,
    bias: m.bias,
    share: top > 0 ? m.mae / top : 0,
    best: m.model === lead.best,
    tied: tied.has(m.model),
    short: m.short_record,
  }));
}

/** Leads present for every variable, lowest first. */
export function leadsOf(report) {
  const sets = VARIABLES.map((v) => Object.keys(report.variables?.[v]?.leads ?? {}));
  return sets.reduce((a, b) => a.filter((x) => b.includes(x)), sets[0] ?? []).sort();
}
