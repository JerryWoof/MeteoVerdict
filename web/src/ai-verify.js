// "Forecast vs measured" on the AI tab (data/scores/ai/fc/verify/): the pure helpers;
// the section itself is drawn by ai-verify-view.js. Only public models are compared.

/** The public models with data in this series, lowest MAE first ({id, name, mae}). */
export function modelsByMae(series, names) {
  return Object.keys(series?.models ?? {})
    .filter((id) => id in (names ?? {}))
    .map((id) => ({ id, name: names[id], mae: series.mae?.[id] ?? null }))
    .sort((a, b) => (a.mae ?? Infinity) - (b.mae ?? Infinity) || a.name.localeCompare(b.name));
}

/** The preferred model if it has data here, else the best one (null: none). */
export function pickModel(ranked, preferred) {
  if (ranked.some((m) => m.id === preferred)) return preferred;
  return ranked[0]?.id ?? null;
}

/** Index of the first time within the last `days` days of `times` (0: all of them). */
export function firstOfLastDays(times, days) {
  if (!times?.length || !days) return 0;
  const cutoff = Date.parse(times.at(-1)) - days * 86_400_000;
  const i = times.findIndex((time) => Date.parse(time) > cutoff);
  return i < 0 ? 0 : i;
}

/** The okresy of index.json sorted by name ([[code, name]]), in the page's language. */
export function okresyByName(okresy, language = "cs") {
  return Object.entries(okresy ?? {}).sort((a, b) => a[1].localeCompare(b[1], language));
}

/** The okres to show first: the one open in the map's panel if it is listed, else Praha. */
export function startOkres(okresy, open, fallback = "CZ0100") {
  if (open && open in (okresy ?? {})) return open;
  if (fallback in (okresy ?? {})) return fallback;
  return Object.keys(okresy ?? {})[0] ?? null;
}
