// Turning the score JSON (written by `mvd aggregate`) into what the map draws.

import { isDark } from "./theme.js";

export const NO_DATA = "#ececec";
export const TOO_FEW = "#bdbdbd";
// the best model is best with probability under P_BEST_MIN (ranking.P_BEST_MIN, also in
// meta.json as p_best_min): the region still takes that model's colour
export const P_BEST_MIN = 0.6;

// Qualitative palette (ColorBrewer Paired, then the Tableau 20 pairs Paired lacks),
// assigned in the order of the models in meta.json (models.yaml order, new models at the
// end), so a model keeps its colour between updates. 20 colours: every model of the
// catalogue (19 enabled, 1 disabled) has its own.
const PALETTE = [
  "#1f78b4", "#e31a1c", "#33a02c", "#ff7f00", "#6a3d9a", "#b15928",
  "#a6cee3", "#fb9a99", "#b2df8a", "#fdbf6f", "#cab2d6", "#ffff99",
  "#17becf", "#e377c2", "#bcbd22", "#8c564b",
  "#00695c", "#8e0152", "#7f7f7f", "#c49c94",
];
// the same hues, lightened where the dark ones fail 3:1 against the dark surface (#1e1c19)
const PALETTE_DARK = [
  "#3586bc", "#e84345", "#33a02c", "#ff7f00", "#9473b6", "#b96a3e",
  "#a6cee3", "#fb9a99", "#b2df8a", "#fdbf6f", "#cab2d6", "#ffff99",
  "#17becf", "#e377c2", "#bcbd22", "#a1746b",
  "#3d8d83", "#b96294", "#7f7f7f", "#c49c94",
];

/** {"columns": [...], "rows": [[...]]} → array of objects */
export function records(doc) {
  if (!doc) return [];
  return doc.rows.map((row) => Object.fromEntries(doc.columns.map((c, i) => [c, row[i]])));
}

/** model id → colour; the blend (not ranked) gets none */
export function modelColors(models, dark = isDark()) {
  const ids = Object.keys(models ?? {}).filter((id) => id !== "blend");
  const palette = dark ? PALETTE_DARK : PALETTE;
  return Object.fromEntries(ids.map((id, i) => [id, palette[i % palette.length]]));
}

/**
 * Best model per region at one lead day: region → {name, model, mae, tied, enough,
 * ranked, borrowed, pBest, clear, small}. `tied` lists the models not significantly
 * worse than the best; `borrowed` counts the stations an okres borrowed from its
 * neighbours; `pBest` is the best model's probability of being the best (p_best, null
 * in older files), `clear` whether that is at least `pBestMin` (no p_best: true);
 * `small` marks a ranking on fewer than 30 days (small_sample).
 */
export function bestByRegion(rows, leadDay, pBestMin = P_BEST_MIN) {
  const best = new Map();
  const unranked = new Map(); // region → lowest MAE, for variables without a ranking
  for (const r of rows) {
    if (r.lead_day !== leadDay) continue;
    const entry = best.get(r.region) ?? {
      name: r.region_name, model: null, mae: null, tied: [], enough: r.enough_stations,
      ranked: false, borrowed: r.borrowed ?? 0, pBest: null, clear: true, small: false,
    };
    if (r.rank === 1) {
      const pBest = r.p_best ?? null;
      Object.assign(entry, {
        model: r.model, mae: r.mae, ranked: true, pBest,
        clear: pBest == null || pBest >= pBestMin, small: Boolean(r.small_sample),
      });
    } else if (r.tied_with_best && r.rank != null) {
      entry.tied.push(r.model);
    }
    if (r.rank == null && r.model !== "blend" && r.mae != null && !r.short_record) {
      const low = unranked.get(r.region);
      if (!low || r.mae < low.mae) unranked.set(r.region, { model: r.model, mae: r.mae });
    }
    best.set(r.region, entry);
  }
  // e.g. the synoptic-hour temperatures are aggregated but not ranked
  for (const [region, entry] of best) {
    if (entry.model == null && unranked.has(region)) Object.assign(entry, unranked.get(region));
  }
  return best;
}

/** Fill colour of a region: its best model (also when the win is not clear: only the
 * tooltip and panel say so), grey with too few stations or no model at all. */
export function regionColor(entry, colors) {
  if (!entry || entry.model == null) return NO_DATA;
  if (!entry.enough) return TOO_FEW;
  return colors[entry.model] ?? NO_DATA;
}

/** An okres without a ranking of its own (no model, or too few stations) takes its
 * kraj's best model, marked `fallback`. okres code CZ0201 belongs to kraj CZ020. */
export function withKrajFallback(okresBest, krajBest) {
  const out = new Map(okresBest);
  for (const [code, entry] of okresBest) {
    if (entry.model != null && entry.enough) continue;
    const kraj = krajBest.get(code.slice(0, 5));
    if (!kraj || kraj.model == null || !kraj.enough) continue;
    out.set(code, { ...kraj, name: entry.name, fallback: true, krajName: kraj.name });
  }
  return out;
}

/** The regions whose ranking rests on a small sample (outlined dashed on the map). */
export function smallSampleCodes(best) {
  return [...best].filter(([, e]) => e.small && e.enough && e.model != null).map(([code]) => code);
}

/** MapLibre "match" expression colouring features by their `code` property. */
export function fillExpression(best, colors) {
  const pairs = [...best].flatMap(([code, entry]) => [code, regionColor(entry, colors)]);
  return pairs.length ? ["match", ["get", "code"], ...pairs, NO_DATA] : NO_DATA;
}

/** GeoJSON points of the stations with a score, coloured by their best model. */
export function stationFeatures(stations, best, colors) {
  return {
    type: "FeatureCollection",
    features: records(stations)
      .filter((s) => best.has(s.id))
      .map((s) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: { code: s.id, name: s.name, color: regionColor(best.get(s.id), colors) },
      })),
  };
}

/** Every station of an okres (or kraj) in the station table, by name: links to the
 * station pages. All of them, not only those scored for the variable shown; `high`:
 * a high site (high_site), scored on its own and not in the okres's ranking. */
export function stationsIn(table, region) {
  return records(table)
    .filter((s) => s.okres_code === region || s.kraj_code === region)
    .map((s) => ({ id: s.id, name: s.name, high: Boolean(s.high_site) }))
    .sort((a, b) => a.name.localeCompare(b.name, "cs"));
}
