// Turning the score JSON (written by `mvd aggregate`) into what the map draws.

export const NO_DATA = "#ececec";
export const TOO_FEW = "#bdbdbd";

// Qualitative palette (ColorBrewer Paired / Tableau), assigned in the order of the
// models in meta.json, so a model keeps its colour between updates.
const PALETTE = [
  "#1f78b4", "#e31a1c", "#33a02c", "#ff7f00", "#6a3d9a", "#b15928",
  "#a6cee3", "#fb9a99", "#b2df8a", "#fdbf6f", "#cab2d6", "#ffff99",
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
 * Best model per region at one lead day: region → {name, model, mae, tied, enough}.
 * `tied` lists the models not significantly worse than the best.
 */
export function bestByRegion(rows, leadDay) {
  const best = new Map();
  for (const r of rows) {
    if (r.lead_day !== leadDay) continue;
    const entry = best.get(r.region) ?? {
      name: r.region_name, model: null, mae: null, tied: [], enough: r.enough_stations,
    };
    if (r.rank === 1) {
      entry.model = r.model;
      entry.mae = r.mae;
    } else if (r.tied_with_best && r.rank != null) {
      entry.tied.push(r.model);
    }
    best.set(r.region, entry);
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

/** Text for a region's popup. */
export function describe(entry, names) {
  if (!entry || entry.model == null) return "no data";
  if (!entry.enough) return "too few stations to rank";
  const name = (id) => names[id] ?? id;
  const tied = entry.tied.length ? `; not significantly worse: ${entry.tied.map(name).join(", ")}` : "";
  return `best: ${name(entry.model)} (MAE ${entry.mae.toFixed(2)})${tied}`;
}
