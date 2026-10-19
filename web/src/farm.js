// Event skill for farmers (farm.json, written by `mvd farm`): frost nights, strong
// gusts and 3-hour rain, per model and lead time bin, from the single runs. Pure
// helpers; the page draws them in compare-page.js.

/** farm.json rows as objects. */
export function farmRows(doc) {
  if (!doc?.rows || !doc.columns) return [];
  return doc.rows.map((row) => Object.fromEntries(doc.columns.map((c, i) => [c, row[i]])));
}

/** The event/threshold pairs with rows, in the file's order: [{event, threshold, key}]. */
export function farmChoices(doc) {
  const seen = new Map();
  for (const r of farmRows(doc)) {
    const key = `${r.event}:${r.threshold}`;
    if (!seen.has(key)) seen.set(key, { event: r.event, threshold: r.threshold, key });
  }
  const order = Object.keys(doc?.events ?? {});
  return [...seen.values()].sort(
    (a, b) =>
      order.indexOf(a.event) - order.indexOf(b.event) ||
      (doc.events[a.event]?.thresholds ?? []).indexOf(a.threshold) -
        (doc.events[b.event]?.thresholds ?? []).indexOf(b.threshold),
  );
}

/**
 * The table of one event and threshold: bins with data (in the file's order), models
 * ordered by their mean rank over the bins (by ETS, 0 best … 1 worst within a bin,
 * fair to short models), each cell's row, the best model(s) per bin (highest ETS, only
 * with at least 2 models and an ETS above 0, i.e. some skill), and per bin the observed events, the
 * units (nights or blocks) and whether the sample is small.
 */
export function farmGrid(doc, event, threshold) {
  const rows = farmRows(doc).filter((r) => r.event === event && r.threshold === threshold);
  const bins = (doc?.bins ?? []).filter((b) => rows.some((r) => r.bin === b));
  const cells = new Map(rows.map((r) => [`${r.model}|${r.bin}`, r]));
  const small = doc?.small_sample ?? 20;
  const perBin = bins.map((bin) => {
    const here = rows.filter((r) => r.bin === bin);
    const scored = here.filter((r) => r.ets != null);
    const top = scored.length ? Math.max(...scored.map((r) => r.ets)) : null;
    const events = here[0]?.events ?? 0;
    return {
      bin,
      events,
      units: here[0]?.units ?? 0,
      models: here.length,
      small: events < small,
      best: top != null && top > 0 && here.length > 1 && events > 0
        ? scored.filter((r) => r.ets === top).map((r) => r.model)
        : [],
    };
  });
  const scores = new Map();
  for (const bin of bins) {
    const scored = rows.filter((r) => r.bin === bin && r.ets != null).sort((a, b) => b.ets - a.ets);
    for (const r of rows.filter((x) => x.bin === bin)) if (!scores.has(r.model)) scores.set(r.model, []);
    if (scored.length < 2) continue;
    scored.forEach((r, i) => scores.get(r.model).push(i / (scored.length - 1)));
  }
  const models = [...scores.entries()]
    .map(([model, s]) => ({
      model,
      score: s.length ? s.reduce((a, b) => a + b, 0) / s.length : Number.POSITIVE_INFINITY,
      bins: bins.filter((b) => cells.has(`${model}|${b}`)).length,
    }))
    .sort((a, b) => a.score - b.score || b.bins - a.bins || a.model.localeCompare(b.model))
    .map((m) => m.model);
  return { bins, models, cells, perBin };
}

/** "0.42", "-0.05", "–" (two decimals, English format). */
export function score(value) {
  if (value == null || Number.isNaN(value)) return "–";
  const shown = Math.abs(value) < 0.005 ? 0 : value; // no "-0.00"
  return shown.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Counts with English thousands separators: 12,345. */
export function count(value) {
  return value == null ? "–" : value.toLocaleString("en-US");
}

/** "H+13–24" */
export function binLabel(bin) {
  return `H+${bin.replace("-", "–")}`;
}

/**
 * Plain-language reading of one cell: {caught, events, falseWarnings, warnings (event forecasts)}, i.e.
 * "caught 8 of 10 frosts, 3 of 11 event forecasts were false".
 */
export function plain(row) {
  return {
    caught: row.hits,
    events: row.hits + row.misses,
    falseWarnings: row.false_alarms,
    warnings: row.hits + row.false_alarms,
  };
}

/**
 * Cell colour by ETS: white at 0 or below, the darker the green the higher, full at
 * 0.6 and above (ETS rarely exceeds that for events). Null: grey.
 */
export function etsColor(ets) {
  if (ets == null || Number.isNaN(ets)) return "#ece9e2";
  const x = Math.max(0, Math.min(1, ets / 0.6));
  const mix = (a, b) => Math.round(a + (b - a) * x);
  // #ffffff → #2e7d4f
  return `rgb(${mix(255, 46)}, ${mix(255, 125)}, ${mix(255, 79)})`;
}

/** Text colour that stays readable on etsColor. */
export function etsTextColor(ets) {
  return ets != null && ets / 0.6 > 0.55 ? "#ffffff" : "#1d2329";
}
