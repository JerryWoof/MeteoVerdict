// The TV-style forecast map (roadmap 6.7): what to draw from outlook.json (written
// twice a day by `mvd outlook`): per okres, day and part of day the combined forecast.

import { records } from "./data.js";

export const PARTS = ["night", "morning", "afternoon", "evening", "day"];
export const LAYERS = ["temperature", "precipitation", "wind", "cloud"];
export const TIME_ZONE = "Europe/Prague";

/** outlook.json → {generated, days, okresy, rows: Map "okres|day|part" → row} */
export function parseOutlook(doc) {
  const rows = new Map();
  for (const r of records(doc)) rows.set(`${r.okres}|${r.day}|${r.part}`, r);
  return {
    generated: doc?.generated ?? null,
    days: doc?.days ?? [],
    okresy: doc?.okresy ?? [],
    rows,
  };
}

export const rowFor = (outlook, okres, day, part) => outlook.rows.get(`${okres}|${day}|${part}`);

/** The number a layer shows: the night's low, otherwise the high; rain as probability. */
export function valueFor(row, layer, part) {
  if (!row) return null;
  if (layer === "temperature") return part === "night" ? row.tmin : row.tmax;
  if (layer === "precipitation") return row.rain_probability;
  if (layer === "wind") return row.wind;
  return row.cloud;
}

/** Text next to the symbol on the map: "12°", "60 %", "4 m/s". */
export function labelFor(row, layer, part) {
  const v = valueFor(row, layer, part);
  if (v == null) return "";
  if (layer === "temperature") return `${Math.round(v)}°`;
  if (layer === "precipitation" || layer === "cloud") {
    return `${Math.round(layer === "precipitation" ? v * 100 : v)} %`;
  }
  return `${Math.round(v)} m/s`;
}

// colour ramps: [value, [r, g, b]] in ascending order
export const RAMPS = {
  temperature: [
    [-15, [49, 54, 149]], [-5, [69, 117, 180]], [0, [171, 217, 233]], [5, [224, 243, 248]],
    [10, [254, 224, 144]], [15, [253, 174, 97]], [20, [244, 109, 67]], [25, [215, 48, 39]],
    [32, [165, 0, 38]],
  ],
  precipitation: [[0, [244, 241, 234]], [0.3, [198, 219, 239]], [0.6, [107, 174, 214]], [1, [8, 81, 156]]],
  wind: [[0, [244, 241, 234]], [4, [199, 233, 192]], [8, [116, 196, 118]], [14, [35, 139, 69]], [20, [0, 68, 27]]],
  cloud: [[0, [254, 240, 180]], [50, [220, 220, 215]], [100, [150, 150, 150]]],
};

const hex = (rgb) => `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;

/** Linear interpolation in a ramp, clamped at its ends. */
export function colorFor(value, layer) {
  const ramp = RAMPS[layer];
  if (value == null) return "#ececec";
  if (value <= ramp[0][0]) return hex(ramp[0][1]);
  for (let i = 1; i < ramp.length; i += 1) {
    const [v1, c1] = ramp[i];
    if (value <= v1) {
      const [v0, c0] = ramp[i - 1];
      const f = (value - v0) / (v1 - v0);
      return hex(c0.map((c, k) => c + f * (c1[k] - c)));
    }
  }
  return hex(ramp.at(-1)[1]);
}

/** MapLibre "match" expression colouring okresy for a day, part and layer. */
export function fillExpression(outlook, day, part, layer) {
  const pairs = outlook.okresy.flatMap((o) => [
    o.code,
    colorFor(valueFor(rowFor(outlook, o.code, day, part), layer, part), layer),
  ]);
  return pairs.length ? ["match", ["get", "code"], ...pairs, "#ececec"] : "#ececec";
}

/** Symbol image name: clear and partly cloudy skies get a moon at night. */
export function iconName(symbol, part) {
  if (!symbol) return "";
  const dark = part === "night";
  if (dark && (symbol === "clear" || symbol === "partly" || symbol === "showers")) return `${symbol}-night`;
  return symbol;
}

/** GeoJSON points at the okres forecast points with their symbol and label. */
export function pointFeatures(outlook, day, part, layer) {
  return {
    type: "FeatureCollection",
    features: outlook.okresy
      .map((o) => ({ o, row: rowFor(outlook, o.code, day, part) }))
      .filter(({ row }) => row)
      .map(({ o, row }) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [o.lon, o.lat] },
        properties: {
          code: o.code,
          name: o.name,
          icon: iconName(row.symbol, part),
          label: labelFor(row, layer, part),
          // larger towns first when labels collide: higher sort key = drawn later
          rank: -(valueFor(row, "temperature", part) ?? 0),
        },
      })),
  };
}

/** Headline for a day and part: warmest and coldest okres, okresy where rain is likely. */
export function summary(outlook, day, part) {
  const rows = outlook.okresy
    .map((o) => ({ o, row: rowFor(outlook, o.code, day, part) }))
    .filter(({ row }) => row);
  if (rows.length === 0) return null;
  const temp = (r) => valueFor(r.row, "temperature", part);
  const warmest = rows.reduce((a, b) => (temp(b) > temp(a) ? b : a));
  const coldest = rows.reduce((a, b) => (temp(b) < temp(a) ? b : a));
  return {
    warmest: { name: warmest.o.name, value: temp(warmest) },
    coldest: { name: coldest.o.name, value: temp(coldest) },
    rainy: rows.filter(({ row }) => (row.rain_probability ?? 0) >= 0.5).length,
    okresy: rows.length,
  };
}

/** The part of day it is now in Prague ("night" before 6, …). */
export function currentPart(now) {
  const hour = Number.parseInt(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: TIME_ZONE }).format(now),
    10,
  );
  return PARTS[Math.floor(hour / 6)];
}

/** Today in Prague as YYYY-MM-DD. */
export function today(now) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** Tab label: "today", "tomorrow" (as i18n keys) or a short weekday and date. */
export function dayLabel(day, todayIso, language) {
  const ms = Date.parse(`${day}T12:00Z`) - Date.parse(`${todayIso}T12:00Z`);
  const offset = Math.round(ms / 86400000);
  if (offset === 0) return { key: "tv.today" };
  if (offset === 1) return { key: "tv.tomorrow" };
  const text = new Intl.DateTimeFormat(language, { weekday: "short", day: "numeric", month: "numeric", timeZone: "UTC" }).format(
    Date.parse(`${day}T12:00Z`),
  );
  return { text };
}

/** The views a "play" cycles through: every part of every day, from (day, part) on. */
export function sequence(outlook, fromDay, fromPart) {
  const steps = [];
  for (const day of outlook.days) {
    for (const part of PARTS.slice(0, 4)) {
      if (outlook.okresy.some((o) => rowFor(outlook, o.code, day, part))) steps.push({ day, part });
    }
  }
  const start = steps.findIndex((s) => s.day === fromDay && s.part === fromPart);
  return start > 0 ? [...steps.slice(start), ...steps.slice(0, start)] : steps;
}
