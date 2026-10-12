// The TV-style forecast map (roadmap 6.7): what to draw from outlook.json (written
// twice a day by `mvd outlook`): per okres, day and part of day the combined forecast.

import { records } from "./data.js";

export const PARTS = ["night", "morning", "afternoon", "evening", "day"];
// the four forecast values; any of them can be shown at the okres markers, and one
// colours the map
export const LAYERS = ["temperature", "precipitation", "wind", "cloud"];
export const COLOURS = LAYERS;
export const DEFAULT_SHOWN = ["temperature", "precipitation"];
const SHORT = { temperature: "t", precipitation: "p", wind: "w", cloud: "c" };
export const TIME_ZONE = "Europe/Prague";

// okresy whose seat is a kraj capital (and Praha): their labels win when markers collide
export const CAPITALS = [
  "CZ0100", "CZ0642", "CZ0806", "CZ0323", "CZ0513", "CZ0712", "CZ0427", "CZ0521",
  "CZ0311", "CZ0532", "CZ0724", "CZ0632", "CZ0412",
];

/** Short okres name for the map ("území Hlavního města Prahy" → "Praha"). */
export function displayName(name) {
  return /Hlavního města Prahy/.test(name) ? "Praha" : name;
}

/**
 * Which markers to show without overlaps: `first` (the selected okres), then the kraj
 * capitals, then the rest in the given order. `boxes` are {code, x, y, w, h}: screen
 * centre and size of each marker.
 */
export function placeMarkers(boxes, gap = 4, first = null) {
  const priority = (box) => (box.code === first ? 0 : CAPITALS.includes(box.code) ? 1 : 2);
  const order = [...boxes].sort((a, b) => priority(a) - priority(b));
  const placed = [];
  const overlaps = (a, b) =>
    Math.abs(a.x - b.x) < (a.w + b.w) / 2 + gap && Math.abs(a.y - b.y) < (a.h + b.h) / 2 + gap;
  for (const box of order) {
    if (!placed.some((p) => overlaps(p, box))) placed.push(box);
  }
  return new Set(placed.map((p) => p.code));
}

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

export const NEUTRAL = "#e9e5db";

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

/** Symbol image name: clear and partly cloudy skies get a moon at night. */
export function iconName(symbol, part) {
  if (!symbol) return "";
  const dark = part === "night";
  if (dark && (symbol === "clear" || symbol === "partly" || symbol === "showers")) return `${symbol}-night`;
  return symbol;
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
    windiest: (() => {
      const w = rows.reduce((a, b) => ((b.row.wind ?? -1) > (a.row.wind ?? -1) ? b : a));
      return { name: w.o.name, value: w.row.wind };
    })(),
    clear: rows.filter(({ row }) => (row.cloud ?? 100) < 25).length,
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

/**
 * Day labels, the same shape for every day: the full weekday ("Tuesday"), the short
 * weekday with the date ("Tue, 10/13") and the date alone ("10/13").
 */
export function dayLabel(day, language) {
  const at = Date.parse(`${day}T12:00Z`);
  const format = (options) => new Intl.DateTimeFormat(language, { timeZone: "UTC", ...options }).format(at);
  const name = format({ weekday: "long" });
  return {
    name: name.charAt(0).toLocaleUpperCase(language) + name.slice(1),
    date: format({ weekday: "short", day: "numeric", month: "numeric" }),
    short: format({ day: "numeric", month: "numeric" }),
  };
}


/**
 * The view in the URL: "#day/part/colour/values/okres", values as letters
 * ("tp" = temperature and rain). Older links "#day/part/layer/okres" still work, and
 * the colour "none" offered earlier becomes temperature.
 * Unknown parts fall back to `fallback` ({day, part}).
 */
export function parseView(hash, outlook, fallback) {
  const parts = hash.replace(/^#/, "").split("/");
  const [day, part, colour] = parts;
  let [, , , values, okres] = parts;
  if (values && /^CZ/.test(values)) [values, okres] = [undefined, values];
  const letters = Object.fromEntries(Object.entries(SHORT).map(([k, v]) => [v, k]));
  const shown = values === undefined ? DEFAULT_SHOWN : [...values].map((c) => letters[c]).filter(Boolean);
  return {
    day: outlook.days.includes(day) ? day : fallback.day,
    part: PARTS.includes(part) ? part : fallback.part,
    colour: COLOURS.includes(colour) ? colour : "temperature",
    shown: LAYERS.filter((l) => shown.includes(l)),
    okres: outlook.okresy.some((o) => o.code === okres) ? okres : null,
  };
}

export function viewHash(view) {
  const values = LAYERS.filter((l) => view.shown.includes(l)).map((l) => SHORT[l]).join("") || "-";
  return `#${[view.day, view.part, view.colour, values, view.okres].filter(Boolean).join("/")}`;
}

// --- "play": a TV-style run through the next days ------------------------------------

// one round of "play" goes through the four parts of the day, night included
export const PLAY_PARTS = ["night", "morning", "afternoon", "evening"];

/**
 * The steps of one round of "play": the four parts of `day` (scope "day"), or the four
 * parts of every day (scope "week"). Only steps with data.
 */
export function playSteps(outlook, scope, day) {
  const days = scope === "week" ? outlook.days : [day];
  const steps = [];
  for (const d of days) {
    for (const part of PLAY_PARTS) {
      if (outlook.okresy.some((o) => rowFor(outlook, o.code, d, part))) steps.push({ day: d, part });
    }
  }
  return steps;
}

/** Where a round starts: at the step shown now, or at the beginning. */
export function startIndex(steps, day, part) {
  return Math.max(0, steps.findIndex((s) => s.day === day && s.part === part));
}

/** The next map colour after a round: temperature → rain → wind → cloud → temperature. */
export function nextColour(colour) {
  const i = LAYERS.indexOf(colour);
  return LAYERS[(i + 1) % LAYERS.length];
}

const NUMERIC = ["tmin", "tmax", "precipitation", "rain_probability", "wind", "cloud"];

/** A row between `a` and `b` (f from 0 to 1): numbers interpolated, the symbol switching
 * half-way; a missing side keeps the other. */
export function lerpRow(a, b, f) {
  if (!a || !b) return f < 0.5 ? (a ?? b) : (b ?? a);
  const row = { ...(f < 0.5 ? a : b) };
  for (const key of NUMERIC) {
    if (a[key] != null && b[key] != null) row[key] = a[key] + (b[key] - a[key]) * f;
  }
  return row;
}

/** Mix two "#rrggbb" colours (f from 0 to 1). */
export function mixColor(c1, c2, f) {
  const p = (c, i) => Number.parseInt(c.slice(1 + 2 * i, 3 + 2 * i), 16);
  const out = [0, 1, 2].map((i) => Math.round(p(c1, i) + (p(c2, i) - p(c1, i)) * f));
  return `#${out.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

/** Ease in and out, for transitions that start and end softly. */
export const ease = (f) => (f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2);

/** Okres → fill colour for a day, part and colour layer (what fillExpression draws). */
export function okresColours(outlook, day, part, layer) {
  return new Map(
    outlook.okresy.map((o) => [
      o.code,
      RAMPS[layer] ? colorFor(valueFor(rowFor(outlook, o.code, day, part), layer, part), layer) : NEUTRAL,
    ]),
  );
}

/**
 * Okres colours during a switch to another map colour, `f` from 0 to 1: the old colours
 * fade to the neutral background, then the new ones come up from it, so two different
 * values are never mixed.
 */
export function switchColours(coloursFrom, coloursTo, f) {
  const out = new Map();
  for (const [code, to] of coloursTo) {
    const from = coloursFrom.get(code) ?? to;
    out.set(code, f < 0.5 ? mixColor(from, NEUTRAL, ease(f * 2)) : mixColor(NEUTRAL, to, ease(f * 2 - 1)));
  }
  return out;
}
