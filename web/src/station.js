// Pure helpers of the station page (measured.html): the per-station JSON written by
// `mvd station-pages` (site/data/station/<WSI>.json) turned into chart rows, labels
// and search results. Format: docs/data-sources.md#station-pages.

/** Views in the order they are shown: finest first. */
export const VIEWS = ["10min", "1hour", "daily", "monthly", "phenomena"];

const STEP_MS = { "10min": 600_000, "1h": 3_600_000, "1d": 86_400_000 };

/** Time of value `i` of a series starting at `start` (Date) with `step`. */
export function stepTime(start, step, i) {
  if (step === "1mo") {
    return new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + i, 1));
  }
  if (step === "1y") return new Date(Date.UTC(start.getUTCFullYear() + i, 0, 1));
  const ms = STEP_MS[step];
  if (!ms) throw new Error(`unknown step ${step}`);
  return new Date(start.getTime() + i * ms);
}

/** [{time, value}] of one element in one series; missing values are left out, or kept
 * as null with `withGaps` (so a line breaks there instead of bridging the gap). */
export function seriesPoints(series, element, withGaps = false) {
  const values = series?.values?.[element];
  if (!values) return [];
  const start = new Date(series.start);
  const points = [];
  values.forEach((value, i) => {
    if (value != null || withGaps) points.push({ time: stepTime(start, series.step, i), value });
  });
  return points;
}

/** Views of the document that have the element, finest first. */
export function viewsWith(doc, element) {
  return VIEWS.filter((v) => doc?.series?.[v]?.values?.[element]);
}

/** Totals are drawn as bars (precipitation, sunshine, new snow, radiation sums, days
 * with a phenomenon). */
export function isTotal(element, how = "", view = "") {
  return view === "phenomena" || /^(SRA|SSV|SNO|VY|RGLB_D|RDIF_D|REUV_D)/.test(element) || /\bSUM\b/.test(how);
}

// English names of ČHMÚ's element codes (the Czech names come from ČHMÚ's meta2)
export const ELEMENT_NAMES_EN = {
  T: "Air temperature", TMA: "Maximum temperature", TMI: "Minimum temperature",
  TMInoc: "Minimum night temperature", TPM: "Ground temperature (5 cm)",
  T05: "Soil temperature 5 cm", T10: "Soil temperature 10 cm", T20: "Soil temperature 20 cm",
  T50: "Soil temperature 50 cm", T100: "Soil temperature 100 cm",
  Td: "Dew point", H: "Relative humidity", E: "Vapour pressure",
  P: "Air pressure (station)", P_hm: "Air pressure (sea level)", ppp: "Pressure tendency",
  F: "Wind speed", Fprum: "Wind speed (mean)", Fmax: "Maximum wind gust", D: "Wind direction",
  Dprum: "Wind direction (mean)", Dmax: "Direction of the maximum gust", D10: "Wind direction (tens of degrees)",
  Casmax: "Time of the maximum gust",
  SRA: "Precipitation", SRA10M: "Precipitation (10 min)", SRA1H: "Precipitation (1 h)",
  API30: "Antecedent precipitation index",
  SCE: "Snow depth", SCEa: "Snow depth (automatic)", SCEdif: "Daily change of snow depth",
  SNO: "New snow", SVH: "Snow water equivalent", SVHa: "Snow water equivalent (automatic)",
  SSV: "Sunshine duration", SSV10M: "Sunshine duration (10 min)", SSV1H: "Sunshine duration (1 h)",
  RGLB10: "Global radiation", RGLB1H: "Global radiation", RGLB_D: "Global radiation (daily sum)",
  RDIF10: "Diffuse radiation", RDIF1H: "Diffuse radiation", RDIF_D: "Diffuse radiation (daily sum)",
  RDIR1H: "Direct solar radiation", RLWD1H: "Long-wave radiation",
  REUV10: "Erythemal UV radiation", REUV1H: "Erythemal UV radiation", REUV_D: "Erythemal UV radiation (daily sum)",
  VY: "Evaporation", N: "Cloud cover", O: "Cloudiness", SD: "Saturation deficit", VV: "Visibility",
  ww: "Present weather", W1: "Past weather 1", W2: "Past weather 2",
  Gph850: "Geopotential height 850 hPa", Gph925: "Geopotential height 925 hPa", O3: "Ozone",
  "C-MLAv": "Mixing layer height", "C-MLI": "Mixing layer reliability index",
};

const CEILOMETER = { C: "cloud base", H: "boundary layer height", I: "boundary layer index" };
const CEILOMETER_STAT = { Av: "mean", Mn: "min", Mx: "max", Co: "count", Md: "mean", Su: "sum" };

/** Name of an element in the page's language. */
export function elementName(code, entry, language) {
  if (language !== "cs") {
    if (ELEMENT_NAMES_EN[code]) return ELEMENT_NAMES_EN[code];
    if (entry?.name_en) return entry.name_en; // phenomena: ČHMÚ names them in both languages
    const c = /^C-([CHI])(\d)(\w\w)$/.exec(code); // ceilometer, e.g. C-C1Av
    if (c) return `Ceilometer ${CEILOMETER[c[1]]} ${c[2]} (${CEILOMETER_STAT[c[3]] ?? c[3]})`;
  }
  return entry?.name ?? ELEMENT_NAMES_EN[code] ?? code;
}

/** Unit as shown: ČHMÚ's "kód" (a code, e.g. weather or quality) in English; none for
 * phenomena, which are counted in days. */
export function unitOf(entry, language) {
  const unit = entry?.unit;
  if (!unit || entry?.types?.includes("PHENO")) return null;
  return unit === "kód" && language !== "cs" ? "code" : unit;
}

/** "Air temperature (°C)" */
export function elementLabel(code, entry, language) {
  const unit = unitOf(entry, language);
  return `${elementName(code, entry, language)}${unit ? ` (${unit})` : ""}`;
}

/** Element codes in table order: alphabetical, the many ceilometer elements last. */
export function elementOrder(codes) {
  const ceilometer = (c) => (c.startsWith("C-") ? 1 : 0);
  return [...codes].sort((a, b) => ceilometer(a) - ceilometer(b) || a.localeCompare(b, "en"));
}

/** Numbers always in English format (decimal point), as on the other pages. */
const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
export function formatNumber(value) {
  return value == null || Number.isNaN(value) ? "–" : NUMBER.format(value);
}

/** The newest value of each element in its finest view: element → {time, value, view}. */
export function latestValues(doc) {
  const out = {};
  for (const view of VIEWS) {
    const series = doc?.series?.[view];
    if (!series) continue;
    for (const element of Object.keys(series.values)) {
      if (out[element]) continue;
      const points = seriesPoints(series, element);
      const last = points[points.length - 1];
      if (last) out[element] = { ...last, view };
    }
  }
  return out;
}

/** Element shown first: air temperature where there is one, else the first with data. */
export function defaultElement(doc) {
  const withData = Object.keys(doc?.elements ?? {}).filter((e) => viewsWith(doc, e).length);
  for (const code of ["T", "SRA", "SCE"]) if (withData.includes(code)) return code;
  return withData[0] ?? null;
}

const fold = (s) => (s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Stations of the index whose name (or WSI) matches the query, without diacritics;
 * names starting with the query first. */
export function searchStations(stations, query, limit = 20) {
  const q = fold(query).trim();
  if (!q) return [];
  const hits = stations.filter((s) => fold(s.name).includes(q) || s.id.includes(q));
  const starts = (s) => (fold(s.name).startsWith(q) ? 0 : 1);
  return hits
    .sort((a, b) => starts(a) - starts(b) || a.name.localeCompare(b.name, "cs"))
    .slice(0, limit);
}

/** "#0-20000-0-11520/T" → {id, element} */
export function parseStationHash(hash) {
  const [id, element] = decodeURIComponent((hash ?? "").replace(/^#/, "")).split("/");
  return { id: id || null, element: element || null };
}

/** Years covered by a series, e.g. "1961–2026". */
export function spanLabel(points) {
  if (!points.length) return "";
  const first = points[0].time.getUTCFullYear();
  const last = points[points.length - 1].time.getUTCFullYear();
  return first === last ? String(first) : `${first}–${last}`;
}
