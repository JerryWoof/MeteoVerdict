// Pure helpers of the station map on measured.html: the stations of
// data/scores/station/index.json as map points, their kind, the "only stations
// measuring …" filter and the station nearest a point. No MapLibre here, so the node
// tests can run them.

/** Kinds of station, in legend order: those of `stations.NETWORKS` (index.json's
 * `network`, from ČHMÚ's metadata, docs/data-sources.md#kinds-of-station), then
 * "station", the fallback for an index without networks or elements. All of them are
 * ČHMÚ's own network. */
export const KINDS = [
  "main",
  "climate",
  "snow",
  "precipitation_auto",
  "precipitation",
  "climate_manual",
  "other",
  "station",
];

export const KIND_COLORS = {
  main: "#d95f02",
  climate: "#1f78b4",
  snow: "#7b5ea7",
  precipitation_auto: "#33a02c",
  precipitation: "#1b5e20",
  climate_manual: "#6baed6",
  other: "#8a949c",
  station: "#1f78b4",
};

/** Kinds that report every 10 minutes. */
const AUTOMATIC_KINDS = new Set(["main", "climate", "snow", "precipitation_auto"]);
const TEMPERATURE = ["T", "TMA", "TMI"];
const MAIN_PREFIX = "0-20000-";

/** What the map can filter by: a group of ČHMÚ element codes, the first the one a
 * click on the station then opens. */
export const MEASURES = {
  temperature: ["T", "TMA", "TMI"],
  precipitation: ["SRA", "SRA1H", "SRA10M"],
  snow: ["SCE", "SCEa", "SNO", "SVH", "SVHa"],
  wind: ["F", "Fmax", "Fprum"],
  sunshine: ["SSV", "SSV1H", "SSV10M"],
  soil: ["T10", "T05", "T20", "T50", "T100"],
  humidity: ["H"],
  pressure: ["P", "P_hm"],
  radiation: ["RGLB_D", "RGLB1H", "RGLB10"],
  visibility: ["VV", "ww"],
  evaporation: ["VY"],
};

/** Kind of a station (one of KINDS) and whether it is automatic. The index's
 * `network` when it has one; an older index: main for a WMO id (WIGOS 0-20000-…), else
 * guessed from the elements and whether there are 10-minute values. */
export function classifyStation(station) {
  if (KINDS.includes(station.network) && station.network !== "station") {
    return { kind: station.network, automatic: AUTOMATIC_KINDS.has(station.network) };
  }
  const automatic = Boolean(station.views?.includes("10min"));
  let kind;
  if (station.id.startsWith(MAIN_PREFIX)) kind = "main";
  else if (!Array.isArray(station.elements)) kind = "station";
  else if (TEMPERATURE.some((c) => station.elements.includes(c))) kind = automatic ? "climate" : "climate_manual";
  else if (station.elements.includes("SRA")) kind = automatic ? "precipitation_auto" : "precipitation";
  else kind = "other";
  return { kind, automatic };
}

/** The index with coordinates: an index written before it listed lat/lon gets them from
 * data/scores/stations.json ({columns, rows}); stations without any are left out. */
export function withCoordinates(stations, table) {
  const where = new Map();
  if (table?.columns && table?.rows) {
    const [id, lat, lon] = ["id", "lat", "lon"].map((c) => table.columns.indexOf(c));
    if (id >= 0 && lat >= 0 && lon >= 0) for (const row of table.rows) where.set(row[id], [row[lat], row[lon]]);
  }
  const out = [];
  for (const s of stations ?? []) {
    if (Number.isFinite(s.lat) && Number.isFinite(s.lon)) out.push(s);
    else if (where.has(s.id)) {
      const [lat, lon] = where.get(s.id);
      if (Number.isFinite(lat) && Number.isFinite(lon)) out.push({ ...s, lat, lon });
    }
  }
  return out;
}

/** Whether every station of the index lists its elements (so the filter can be offered). */
export function hasElements(stations) {
  return stations.length > 0 && stations.every((s) => Array.isArray(s.elements));
}

/** Does the station measure something of the group? No group: every station does. */
export function measures(station, measure) {
  if (!measure) return true;
  const codes = MEASURES[measure];
  return Boolean(codes && station.elements?.some((c) => codes.includes(c)));
}

/** Element to open for a station found through the filter: the group's first it has. */
export function elementFor(station, measure) {
  return MEASURES[measure]?.find((c) => station.elements?.includes(c)) ?? null;
}

/** Groups at least one station measures, with how many: [[measure, count]]. */
export function measureCounts(stations) {
  return Object.keys(MEASURES)
    .map((m) => [m, stations.filter((s) => measures(s, m)).length])
    .filter(([, n]) => n > 0);
}

export function filterStations(stations, measure) {
  return stations.filter((s) => measures(s, measure));
}

/** Kinds present among the stations, in legend order, with counts: [[kind, count]]. */
export function kindCounts(stations) {
  const counts = new Map();
  for (const s of stations) {
    const { kind } = classifyStation(s);
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }
  return KINDS.filter((k) => counts.has(k)).map((k) => [k, counts.get(k)]);
}

/** GeoJSON points of the stations; manual stations (no 10-minute data) drawn hollow. */
export function stationFeatures(stations) {
  return {
    type: "FeatureCollection",
    features: stations.map((s) => {
      const { kind, automatic } = classifyStation(s);
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: {
          id: s.id,
          name: s.name ?? s.id,
          kind,
          automatic: automatic ? 1 : 0,
          elevation: s.elevation ?? null,
        },
      };
    }),
  };
}

/** Elevation colours, low to high (m above sea level). */
export const ELEVATION_STOPS = [
  [150, "#1a9850"],
  [400, "#a6d96a"],
  [650, "#fee08b"],
  [950, "#f46d43"],
  [1300, "#a50026"],
  [1600, "#54278f"],
];

/** MapLibre colour expression: by kind, or by elevation. */
export function colorExpression(by) {
  if (by === "elevation") {
    return [
      "case",
      ["==", ["get", "elevation"], null],
      "#8a949c",
      ["interpolate", ["linear"], ["get", "elevation"], ...ELEVATION_STOPS.flat()],
    ];
  }
  return ["match", ["get", "kind"], ...KINDS.flatMap((k) => [k, KIND_COLORS[k]]), "#8a949c"];
}

/** CSS gradient of the elevation legend. */
export function elevationGradient() {
  const [lo, hi] = [ELEVATION_STOPS[0][0], ELEVATION_STOPS.at(-1)[0]];
  const stops = ELEVATION_STOPS.map(([m, c]) => `${c} ${Math.round(((m - lo) / (hi - lo)) * 100)}%`);
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

/** The station nearest to [lon, lat] (distances on the local plane, longitude shrunk by
 * the cosine of the latitude), or null for no stations. */
export function nearestStation(stations, [lon, lat]) {
  const k = Math.cos((lat * Math.PI) / 180);
  let best = null;
  let bestD = Infinity;
  for (const s of stations) {
    const d = ((s.lon - lon) * k) ** 2 + (s.lat - lat) ** 2;
    if (d < bestD) {
      bestD = d;
      best = s;
    }
  }
  return best;
}
