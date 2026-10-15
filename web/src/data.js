// Turning the score JSON (written by `mvd aggregate`) into what the map draws.

export const NO_DATA = "#ececec";
export const TOO_FEW = "#bdbdbd";

// Qualitative palette (ColorBrewer Paired, then the Tableau 20 pairs Paired lacks),
// assigned in the order of the models in meta.json (models.yaml order, new models at the
// end), so a model keeps its colour between updates. 20 colours: every model of the
// catalogue (19 enabled, 1 disabled) has its own.
const PALETTE = [
  "#1f78b4", "#e31a1c", "#33a02c", "#ff7f00", "#6a3d9a", "#b15928",
  "#a6cee3", "#fb9a99", "#b2df8a", "#fdbf6f", "#cab2d6", "#ffff99",
  "#17becf", "#e377c2", "#bcbd22", "#8c564b",
  "#9edae5", "#f7b6d2", "#dbdb8d", "#c49c94",
];

/** {"columns": [...], "rows": [[...]]} → array of objects */
export function records(doc) {
  if (!doc) return [];
  return doc.rows.map((row) => Object.fromEntries(doc.columns.map((c, i) => [c, row[i]])));
}

/** model id → colour; the blend (not ranked) gets none */
export function modelColors(models) {
  const ids = Object.keys(models ?? {}).filter((id) => id !== "blend");
  return Object.fromEntries(ids.map((id, i) => [id, PALETTE[i % PALETTE.length]]));
}

/**
 * Best model per region at one lead day: region → {name, model, mae, tied, enough,
 * ranked, borrowed}. `tied` lists the models not significantly worse than the best;
 * `borrowed` counts the stations an okres borrowed from its neighbours.
 */
export function bestByRegion(rows, leadDay) {
  const best = new Map();
  const unranked = new Map(); // region → lowest MAE, for variables without a ranking
  for (const r of rows) {
    if (r.lead_day !== leadDay) continue;
    const entry = best.get(r.region) ?? {
      name: r.region_name, model: null, mae: null, tied: [], enough: r.enough_stations,
      ranked: false, borrowed: r.borrowed ?? 0,
    };
    if (r.rank === 1) {
      Object.assign(entry, { model: r.model, mae: r.mae, ranked: true });
    } else if (r.tied_with_best && r.rank != null) {
      entry.tied.push(r.model);
    }
    if (r.rank == null && r.model !== "blend" && r.mae != null) {
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

/** Fill colour of a region: its best model, grey with too few stations. */
export function regionColor(entry, colors) {
  if (!entry || entry.model == null) return NO_DATA;
  if (!entry.enough) return TOO_FEW;
  return colors[entry.model] ?? NO_DATA;
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
 * station pages. All of them, not only those scored for the variable shown. */
export function stationsIn(table, region) {
  return records(table)
    .filter((s) => s.okres_code === region || s.kraj_code === region)
    .map((s) => ({ id: s.id, name: s.name }))
    .sort((a, b) => a.name.localeCompare(b.name, "cs"));
}
