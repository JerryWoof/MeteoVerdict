// "Weather at the station": the station's diary, day by day (pure helpers; the page is
// station-page.js). Data: the decade files diary/<WSI>/<decade>.json.gz written by
// `mvd station-pages` (src/meteoverdict/station_diary.py), summarised under `diary` in
// the station file. Format and the window of each value: docs/data-sources.md#station-diary.

export const TIME_ZONE = "Europe/Prague";
/** Fields of a day, as in the files: max, min and mean temperature, precipitation, new
 * snow, snow depth, sunshine (h), maximum gust (m/s). */
export const FIELDS = ["tx", "tn", "t", "r", "sno", "sce", "ssv", "g"];
/** Phenomena shown as badges (rain and snow show in the symbol instead). */
export const BADGES = ["BO", "KR", "MS", "LE", "NA", "ML", "SV"];
/** A day is wet from this much precipitation (mm). */
export const WET_MM = 0.5;
/** Sky from the sunshine as a share of the day's length: clear, partly cloudy, else cloudy. */
export const CLEAR_SUNSHINE = 0.6;
export const PARTLY_SUNSHINE = 0.25;
/** A wet day with at least this share of sunshine shows showers. */
export const SHOWERS_SUNSHINE = 0.3;
/** Sky from the daytime mean cloud cover (%), as the forecast symbols (models.js). */
export const CLEAR_BELOW = 30;
export const PARTLY_BELOW = 65;
/** Rain, sleet or snow from the temperature when no phenomenon says (models.js). */
export const SNOW_AT_OR_BELOW = 0.5;
export const SLEET_AT_OR_BELOW = 2;
export const VIEWS = ["days", "week", "month"];
/** Days of the default view. */
export const RECENT_DAYS = 14;

const DAY_MS = 86_400_000;

// --- days as "YYYY-MM-DD" ------------------------------------------------------------
const toMs = (iso) => Date.parse(`${iso}T00:00:00Z`);
const toIso = (ms) => new Date(ms).toISOString().slice(0, 10);
export const addDays = (iso, n) => toIso(toMs(iso) + n * DAY_MS);
export const daysBetween = (a, b) => Math.round((toMs(b) - toMs(a)) / DAY_MS);
const clampDay = (iso, first, last) => (first && iso < first ? first : last && iso > last ? last : iso);

/** Monday of the week of a day. */
export function weekStart(iso) {
  const weekday = (new Date(toMs(iso)).getUTCDay() + 6) % 7; // Monday 0
  return addDays(iso, -weekday);
}

export function monthEnd(iso) {
  const d = new Date(toMs(iso));
  return toIso(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
}

/** The days a view shows around `day`: the 14 days up to it, its week (Monday to
 * Sunday) or its month; never past the archive's first or last day. */
export function viewRange(view, day, first = null, last = null) {
  let from;
  let to;
  if (view === "week") {
    from = weekStart(day);
    to = addDays(from, 6);
  } else if (view === "month") {
    from = `${day.slice(0, 7)}-01`;
    to = monthEnd(day);
  } else {
    from = addDays(day, -(RECENT_DAYS - 1));
    to = day;
  }
  return { from: clampDay(from, first, null), to: clampDay(to, null, last) };
}

/** The day `step` views before (-1) or after (+1) `day`. */
export function shiftDay(view, day, step) {
  if (view === "month") {
    const d = new Date(toMs(day));
    const month = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + step, 1));
    // the same day of the month where it exists, else its last day
    return toIso(Math.min(month.getTime() + (d.getUTCDate() - 1) * DAY_MS, toMs(monthEnd(toIso(month.getTime())))));
  }
  return addDays(day, step * (view === "week" ? 7 : RECENT_DAYS));
}

// --- the files ---------------------------------------------------------------------------
/** First years of the decade files that cover from … to. */
export function chunksFor(diary, from, to) {
  const size = diary?.decade ?? 10;
  return (diary?.chunks ?? []).filter((y) => y + size > Number(from.slice(0, 4)) && y <= Number(to.slice(0, 4)));
}

/** A day of a chunk → its phenomena; built once per chunk. */
const phenomenaIndex = new WeakMap();
function phenomenaOf(chunk) {
  let index = phenomenaIndex.get(chunk);
  if (!index) {
    index = new Map();
    for (const [code, days] of Object.entries(chunk.phenomena ?? {})) {
      for (const i of days) index.set(i, [...(index.get(i) ?? []), code]);
    }
    phenomenaIndex.set(chunk, index);
  }
  return index;
}

/** Rows from … to (inclusive), one a day: {day, tx, tn, t, r, sno, sce, ssv, g,
 * phenomena: [codes], flags: {field: flag}, unchecked}; null where a value is missing. */
export function dayRows(chunks, from, to) {
  const rows = [];
  for (let day = from; day <= to; day = addDays(day, 1)) {
    const row = { day, phenomena: [], flags: {}, unchecked: false };
    for (const field of FIELDS) row[field] = null;
    for (const chunk of chunks) {
      const i = daysBetween(chunk.start, day);
      if (i < 0 || i >= chunk.days) continue;
      for (const field of FIELDS) {
        const v = chunk.values?.[field]?.[i];
        if (v != null) row[field] = v;
      }
      row.phenomena = [...(phenomenaOf(chunk).get(i) ?? [])].sort();
      for (const [field, flags] of Object.entries(chunk.flags ?? {})) {
        for (const [flag, days] of Object.entries(flags)) if (days.includes(i)) row.flags[field] = flag;
      }
      row.unchecked = (chunk.unchecked ?? []).includes(i);
    }
    rows.push(row);
  }
  return rows;
}

// --- the observed symbol --------------------------------------------------------------
/** Hours from sunrise to sunset at a latitude on a day (the sun's centre 0.833° below
 * the horizon, as for the sunrise times). */
export function dayLength(lat, iso) {
  const start = Date.UTC(Number(iso.slice(0, 4)), 0, 1);
  const n = Math.round((toMs(iso) - start) / DAY_MS) + 1;
  const rad = Math.PI / 180;
  const declination = -23.44 * Math.cos(((2 * Math.PI) / 365) * (n + 10)) * rad;
  const phi = lat * rad;
  const cos = (Math.sin(-0.833 * rad) - Math.sin(phi) * Math.sin(declination)) / (Math.cos(phi) * Math.cos(declination));
  if (cos <= -1) return 24;
  if (cos >= 1) return 0;
  return (2 * Math.acos(cos)) / rad / 15;
}

/** How sunny the day was, 0 … 1, and from what: the sunshine hours as a share of the
 * day's length, else the daytime mean cloud cover (`row.cloud`, octas); null when the
 * station measures neither. */
export function sunniness(row, lat) {
  if (row.ssv != null && lat != null) {
    const hours = dayLength(lat, row.day);
    if (hours > 0) return { share: Math.min(1, row.ssv / hours), from: "sunshine" };
  }
  if (row.cloud != null) return { share: 1 - row.cloud / 8, from: "cloud" };
  return null;
}

/** Rain, sleet or snow: what the observer recorded (rain DE, snow SN, both: sleet), else
 * new snow on the ground, else the day's temperature. */
export function precipitationKind(row) {
  const rain = row.phenomena.includes("DE") || row.phenomena.includes("MS");
  const snow = row.phenomena.includes("SN");
  if (rain && snow) return "sleet";
  if (snow) return "snow";
  if (rain) return "rain";
  if ((row.sno ?? 0) >= 1) return "snow";
  const t = row.t ?? (row.tx != null && row.tn != null ? (row.tx + row.tn) / 2 : null);
  if (t != null && t <= SNOW_AT_OR_BELOW) return "snow";
  if (t != null && t <= SLEET_AT_OR_BELOW) return "sleet";
  return "rain";
}

/**
 * The weather symbol of an observed day (an icon of icons.js), honest about what was
 * measured: precipitation of at least WET_MM gives rain, sleet or snow (showers when the
 * sun shone for at least SHOWERS_SUNSHINE of the day as well); a dry day gets its sky
 * from the sunshine (or cloud cover); null when the station measures neither, or when it
 * measures no precipitation and the day had no sky observation.
 */
export function daySymbol(row, lat) {
  const sky = sunniness(row, lat);
  if (row.r != null && row.r >= WET_MM) {
    const kind = precipitationKind(row);
    return kind === "rain" && sky && sky.share >= SHOWERS_SUNSHINE ? "showers" : kind;
  }
  if (!sky) return null;
  if (sky.from === "cloud") {
    const cloud = (1 - sky.share) * 100;
    return cloud < CLEAR_BELOW ? "clear" : cloud < PARTLY_BELOW ? "partly" : "cloudy";
  }
  return sky.share >= CLEAR_SUNSHINE ? "clear" : sky.share >= PARTLY_SUNSHINE ? "partly" : "cloudy";
}

// --- what to show -----------------------------------------------------------------------
const any = (rows, test) => rows.some(test);
const has = (rows, field) => any(rows, (r) => r[field] != null);

/**
 * Columns of the day table that the rows have something for, in table order: symbol,
 * temperature (max / min), precipitation, snow (only where there was some), sunshine,
 * gust, phenomena. A rain gauge gets day, symbol (wet days), precipitation and snow.
 */
export function columnsFor(rows, lat) {
  const columns = [];
  if (any(rows, (r) => daySymbol(r, lat))) columns.push("symbol");
  if (has(rows, "tx") || has(rows, "tn")) columns.push("temperature");
  if (has(rows, "r")) columns.push("precipitation");
  if (any(rows, (r) => (r.sce ?? 0) > 0 || (r.sno ?? 0) > 0 || r.flags.sce || r.flags.sno)) columns.push("snow");
  if (has(rows, "ssv")) columns.push("sunshine");
  if (has(rows, "g")) columns.push("gust");
  if (any(rows, (r) => r.phenomena.some((c) => BADGES.includes(c)))) columns.push("phenomena");
  return columns;
}

const round1 = (v) => Math.round(v * 10) / 10;

function extreme(rows, field, better) {
  let best = null;
  for (const r of rows) {
    if (r[field] != null && (best == null || better(r[field], best.value))) best = { value: r[field], day: r.day };
  }
  return best;
}

/**
 * Summary of a period (a month, a week): `days` in it and, where there are values,
 * `count` (days with a value of each field), `tmean` (mean of ČHMÚ's daily means), `tmax`
 * and `tmin` ({value, day}: the highest maximum, the lowest minimum), `precipitation`
 * (total), `wetDays` (≥ 1 mm), `frostDays` (minimum below 0 °C), `iceDays` (maximum below
 * 0 °C), `summerDays` (maximum ≥ 25 °C), `sunshine` (total hours), `gust` ({value, day}),
 * `snowDays` (snow depth ≥ 1 cm), `snowMax` ({value, day}) and `storms` (days with a
 * thunderstorm); a field the period has no value of is null.
 */
export function periodSummary(rows) {
  const count = Object.fromEntries(FIELDS.map((f) => [f, rows.filter((r) => r[f] != null).length]));
  const sum = (field) => (count[field] ? round1(rows.reduce((a, r) => a + (r[field] ?? 0), 0)) : null);
  const days = (field, test) => (count[field] ? rows.filter((r) => r[field] != null && test(r[field])).length : null);
  return {
    days: rows.length,
    count,
    tmean: count.t ? round1(rows.reduce((a, r) => a + (r.t ?? 0), 0) / count.t) : null,
    tmax: extreme(rows, "tx", (a, b) => a > b),
    tmin: extreme(rows, "tn", (a, b) => a < b),
    precipitation: sum("r"),
    wetDays: days("r", (v) => v >= 1),
    frostDays: days("tn", (v) => v < 0),
    iceDays: days("tx", (v) => v < 0),
    summerDays: days("tx", (v) => v >= 25),
    sunshine: sum("ssv"),
    gust: extreme(rows, "g", (a, b) => a > b),
    snowDays: days("sce", (v) => v >= 1),
    snowMax: extreme(rows, "sce", (a, b) => a > b),
    // only where phenomena are recorded at all (not every station has an observer)
    storms: rows.some((r) => r.phenomena.length) ? rows.filter((r) => r.phenomena.includes("BO")).length : null,
  };
}

// --- Prague time -----------------------------------------------------------------------
const pragueParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
});

/** Prague day ("YYYY-MM-DD") and hour of a moment (ms). */
export function pragueDayHour(ms) {
  const p = Object.fromEntries(pragueParts.formatToParts(ms).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) };
}

/** The moments (ms) a Prague day starts and ends. */
export function pragueDayBounds(iso) {
  const startOf = (day) => {
    for (const offset of [1, 2, 0]) {
      const ms = toMs(day) - offset * 3_600_000;
      const local = pragueDayHour(ms);
      if (local.day === day && local.hour === 0) return ms;
    }
    return toMs(day) - 3_600_000;
  };
  return { start: startOf(iso), end: startOf(addDays(iso, 1)) };
}

const STEP_MS = { "10min": 600_000, "1h": 3_600_000 };

/** Daytime (observations 8–17 h Prague) mean cloud cover (octas) per Prague day from
 * the hourly series' N, where at least 6 of those hours have a value. */
export function daytimeCloud(series) {
  const values = series?.values?.N;
  const out = new Map();
  if (!values || series.step !== "1h") return out;
  const start = Date.parse(series.start);
  const sums = new Map();
  values.forEach((v, i) => {
    if (v == null || v > 8) return; // 9: sky not visible (fog)
    // an observation at the full hour
    const { day, hour } = pragueDayHour(start + i * 3_600_000);
    if (hour < 8 || hour > 17) return;
    const s = sums.get(day) ?? { sum: 0, n: 0 };
    s.sum += v;
    s.n += 1;
    sums.set(day, s);
  });
  for (const [day, s] of sums) if (s.n >= 6) out.set(day, round1(s.sum / s.n));
  return out;
}

/**
 * The course of one Prague day from the station file's finest series that covers it:
 * the 10-minute values (the last 3 days), else the hourly ones (the last 30 days).
 * Returns {view, start, end, temperature, precipitation, wind, gust} (each a list of
 * {time: Date, value}, the precipitation as totals per step), or null when the file has
 * no values that day (older days: daily values only).
 */
export function dayCourse(doc, iso) {
  const { start, end } = pragueDayBounds(iso);
  for (const [view, precipitation] of [["10min", "SRA10M"], ["1hour", "SRA1H"]]) {
    const series = doc?.series?.[view];
    if (!series) continue;
    const step = STEP_MS[series.step];
    const first = Date.parse(series.start);
    // the 10-minute series often starts within the day: then the hourly one, whole
    if (view === "10min" && first > start + step) continue;
    const pick = (element) => {
      const values = series.values?.[element] ?? [];
      const points = [];
      values.forEach((value, i) => {
        const time = first + i * step;
        if (time > start && time <= end) points.push({ time: new Date(time), value });
      });
      return points.some((p) => p.value != null) ? points : [];
    };
    const course = {
      view,
      start: new Date(start),
      end: new Date(end),
      temperature: pick("T"),
      precipitation: pick(precipitation),
      wind: pick("F"),
      gust: pick("Fmax"),
    };
    if (["temperature", "precipitation", "wind", "gust"].some((k) => course[k].length)) return course;
  }
  return null;
}

/** The JSON of a diary file: gzipped as stored, or already unpacked by the server. */
export async function parseDiaryFile(buffer) {
  const bytes = new Uint8Array(buffer);
  let text;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes);
  }
  return JSON.parse(text);
}

/** View and day from the page's query (?view=month&day=2025-07-14), or null each. */
export function parseDiaryQuery(search) {
  const params = new URLSearchParams(search ?? "");
  const view = params.get("view");
  const day = params.get("day");
  return {
    view: VIEWS.includes(view) ? view : null,
    day: /^\d{4}-\d{2}-\d{2}$/.test(day ?? "") && !Number.isNaN(toMs(day)) ? day : null,
  };
}
