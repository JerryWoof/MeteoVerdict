// The TV-style forecast map (roadmap 6.7): what to draw from outlook.json (written
// with each forecast run): per okres, day and part of day the combined forecast.

import { records } from "./data.js";
import { BEYOND, NEUTRAL, RAMPS, colorFor, rampKey } from "./palette.js";

/** Whether the part's corrected gust reaches MeteoVerdict's threshold (outlook files from
 * before the rename only have the old name ``gust_warning``). */
export const GUST_THRESHOLD = 13.5;
export const gustOver = (row) => row?.gust_over_threshold ?? row?.gust_warning ?? null;

/** "Gusts over 13.5 m/s" (the same threshold as
 * ``gusts.GUST_THRESHOLD`` in the pipeline). */
export const gustOverText = (t, language) => t("tv.gustOverThreshold", { gust: GUST_THRESHOLD.toLocaleString(language) });

/** The permanent line under the week table: red marks are our thresholds, not ČHMÚ warnings
 * (only ČHMÚ may issue those, Act 262/2024 Sb.). Always there, so the page never jumps. */
export function chmiNotice(t) {
  const notice = document.createElement("p");
  notice.className = "note small chmi-notice";
  notice.textContent = t("tv.notChmi");
  return notice;
}

export const PARTS = ["night", "morning", "afternoon", "evening", "day"];
// the four forecast values; any of them can be shown at the okres markers, and one
// colours the map
export const LAYERS = ["temperature", "precipitation", "wind", "cloud"];
export const COLOURS = LAYERS;
// the measured page (observed.js, measured.js) also shows the strongest gust and the sunshine
export const ALL_LAYERS = ["temperature", "precipitation", "wind", "gust", "sunshine", "cloud"];
export const DEFAULT_SHOWN = ["temperature", "precipitation"];
const SHORT = { temperature: "t", precipitation: "p", wind: "w", cloud: "c", gust: "g", sunshine: "s" };
export const TIME_ZONE = "Europe/Prague";

// okresy whose seat is a kraj capital (and Praha): their labels win when markers collide;
// roughly by the town's size, biggest first (a phone's whole-country view shows them in this order)
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
 * centre and size of each marker; a box's own `priority` (smaller first) replaces that
 * order (the station labels of the measured map, measured.js).
 */
export function placeMarkers(boxes, gap = 4, first = null) {
  const priority = (box) => box.priority ?? (box.code === first ? 0 : CAPITALS.includes(box.code) ? 1 : 2);
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

/**
 * Rain in mm, like every single model and the measurements: our combination too (its
 * weighted amount); the probability only where an old file has no amount.
 */
const inMm = (row) => Boolean(row?.single || row?.measured || row?.precipitation != null);

/**
 * The number a layer shows: the night's low, otherwise the high; rain as the total in mm (a single
 * model, a measured row and our combination alike; the combination's probability is
 * `row.rain_probability`, shown beside it).
 */
export function valueFor(row, layer, part) {
  if (!row) return null;
  if (layer === "temperature") return part === "night" ? row.tmin : row.tmax;
  if (layer === "precipitation") return inMm(row) ? row.precipitation : row.rain_probability;
  if (layer === "wind") return row.wind;
  if (layer === "gust") return row.gust ?? null;
  if (layer === "sunshine") return row.sunshine ?? null;
  return row.cloud;
}

/** "1.2" with one decimal, in the page language ("1,2" in Czech; English without a page). */
const oneDecimal = (v) =>
  v.toLocaleString(globalThis.document?.documentElement.lang || "en", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/**
 * Text next to the symbol on the map: "12°", "60 %", "4 m/s"; a single model's rain
 * "1.2 mm"; "–" beyond a single model's horizon.
 */
export function labelFor(row, layer, part) {
  if (row?.beyond) return "–";
  const v = valueFor(row, layer, part);
  // measured: "–" where no station of the okres measures it
  if (v == null) return row?.measured ? "–" : "";
  if (layer === "temperature") return `${Math.round(v)}°`;
  if (layer === "precipitation" && inMm(row)) return `${oneDecimal(v)} mm`;
  if (layer === "sunshine") return `${oneDecimal(v)} h`;
  if (layer === "precipitation" || layer === "cloud") {
    return `${Math.round(layer === "precipitation" ? v * 100 : v)} %`;
  }
  return `${Math.round(v)} m/s`;
}

// the colour scales and their legend live in palette.js, shared with the measured page
export { BEYOND, NEUTRAL, RAMPS, colorFor, rampKey } from "./palette.js";

/** A single model's rain threshold (mm), as its rain symbol (models.js RAIN_MM). */
export const MODEL_RAIN_MM = 0.3;

/** Every view shows rain in mm (the combination's probability is a second value). */
export const mmView = () => true;

// the hours of each part of the day, Prague time
const PART_HOURS = { night: [0, 6], morning: [6, 12], afternoon: [12, 18], evening: [18, 24] };

const minutes = (hhmm) => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm ?? "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
};

/**
 * Whether a part of the day is dark: more than half of its hours between sunset and
 * sunrise ("HH:MM" from sun, e.g. a row). In October the evening is dark, in June it
 * is not. Without sun times only "night" is; the whole "day" never is.
 */
export function isNightPart(part, sun) {
  const hours = PART_HOURS[part];
  if (!hours) return false;
  const rise = minutes(sun?.sunrise);
  const set = minutes(sun?.sunset);
  if (rise == null || set == null || rise >= set) return part === "night";
  const [start, end] = hours.map((h) => h * 60);
  const overlap = (a, b) => Math.max(0, Math.min(end, b) - Math.max(start, a));
  const dark = overlap(0, rise) + overlap(set, 24 * 60);
  return dark > (end - start) / 2;
}

/**
 * Symbol image name: clear and partly cloudy skies and showers get a moon when the part
 * is dark (see isNightPart; sun is {sunrise, sunset}, e.g. the row itself).
 */
export function iconName(symbol, part, sun) {
  if (!symbol) return "";
  // a measured row knows whether it was dark (observed.js isDark)
  const dark = sun?.dark ?? isNightPart(part, sun);
  if (dark && (symbol === "clear" || symbol === "partly" || symbol === "showers")) return `${symbol}-night`;
  return symbol;
}

/**
 * Headline for a day and part: warmest and coldest okres, okresy where rain is likely
 * (our combination: probability ≥ 50 %; a single model's view, `outlook.single`: its own
 * total ≥ MODEL_RAIN_MM). Okresy beyond a single model's horizon do not count; null
 * without any okres.
 */
export function summary(outlook, day, part) {
  const rows = outlook.okresy
    .map((o) => ({ o, row: rowFor(outlook, o.code, day, part) }))
    .filter(({ row }) => row && !row.beyond);
  if (rows.length === 0) return null;
  const single = Boolean(outlook.single);
  const temp = (r) => valueFor(r.row, "temperature", part);
  const warmest = rows.reduce((a, b) => (temp(b) > temp(a) ? b : a));
  const coldest = rows.reduce((a, b) => (temp(b) < temp(a) ? b : a));
  return {
    warmest: { name: warmest.o.name, value: temp(warmest) },
    coldest: { name: coldest.o.name, value: temp(coldest) },
    rainy: rows.filter(({ row }) => (single
      ? (row.precipitation ?? 0) >= MODEL_RAIN_MM
      : (row.rain_probability ?? 0) >= 0.5)).length,
    single,
    // a single model may lack a variable (MeteoVerdict AI: no rain or cloud): no line then
    hasRain: !single || rows.some(({ row }) => row.precipitation != null),
    hasCloud: !single || rows.some(({ row }) => row.cloud != null),
    windiest: (() => {
      const w = rows.reduce((a, b) => ((b.row.wind ?? -1) > (a.row.wind ?? -1) ? b : a));
      return { name: w.o.name, value: w.row.wind };
    })(),
    clear: rows.filter(({ row }) => (row.cloud ?? 100) < 25).length,
    okresy: rows.length,
  };
}

// --- sunrise and sunset ("HH:MM", Prague time, the same on every row of a day; older
// outlook files have neither) --------------------------------------------------------

/** Sunrise and sunset of an okres on a day: {sunrise, sunset}, or null without them. */
export function sunFor(outlook, okres, day) {
  const row = PARTS.map((part) => rowFor(outlook, okres, day, part)).find((r) => r?.sunrise && r?.sunset);
  return row ? { sunrise: row.sunrise, sunset: row.sunset } : null;
}

/**
 * Sunrise and sunset over all okresy on a day, earliest and latest:
 * {sunrise: ["07:03", "07:28"], sunset: ["17:59", "18:23"]}, or null without them.
 * "HH:MM" strings sort as times.
 */
export function sunRange(outlook, day) {
  const times = outlook.okresy.map((o) => sunFor(outlook, o.code, day)).filter(Boolean);
  if (times.length === 0) return null;
  const range = (key) => {
    const sorted = times.map((s) => s[key]).sort();
    return [sorted[0], sorted.at(-1)];
  };
  return { sunrise: range("sunrise"), sunset: range("sunset") };
}

/** "07:03–07:28", or one time when earliest and latest are the same. */
export const rangeText = ([first, last]) => (first === last ? first : `${first}–${last}`);

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
 * Day labels, the same shape for every day: `name` is "Today", "Tomorrow" (as the i18n
 * key `key`) or the full weekday ("Wednesday"); `date` is the short weekday with the
 * date ("Wed, 10/14") and `short` the date alone ("10/14").
 */
export function dayLabel(day, todayIso, language) {
  const at = Date.parse(`${day}T12:00Z`);
  const format = (options) => new Intl.DateTimeFormat(language, { timeZone: "UTC", ...options }).format(at);
  const weekday = format({ weekday: "long" });
  const offset = Math.round((at - Date.parse(`${todayIso}T12:00Z`)) / 86400000);
  const label = {
    name: weekday.charAt(0).toLocaleUpperCase(language) + weekday.slice(1),
    date: format({ weekday: "short", day: "numeric", month: "numeric" }),
    short: format({ day: "numeric", month: "numeric" }),
  };
  if (offset === 0) label.key = "day.today";
  if (offset === 1) label.key = "day.tomorrow";
  if (offset === -1) label.key = "day.yesterday";
  return label;
}


/**
 * The view in the URL: "#day/part/colour/values/okres", values as letters
 * ("tp" = temperature and rain), and "/obec" after it opens that obec's panel; the short
 * "#okres/obec" (the home page's links) means the same with the defaults. Older links "#day/part/layer/okres" still work, and
 * the colour "none" offered earlier becomes temperature.
 * Unknown parts fall back to `fallback` ({day, part}).
 */
export function parseView(hash, outlook, fallback) {
  // outlook.days: every day offered (the measured page passes its measured days)
  let parts = hash.replace(/^#/, "").split("/");
  // "#CZ0423/Obec": an okres and an obec, the rest as default; the codes of the
  // okresy around Prague end in a letter (CZ020A, CZ020B, CZ020C)
  if (/^CZ\w{4}$/.test(parts[0]) && parts.length === 2) parts = ["", "", "", undefined, parts[0], parts[1]];
  const [day, part, colour] = parts;
  let [, , , values, okres] = parts;
  let obec = parts[5];
  if (values && /^CZ/.test(values)) [values, okres] = [undefined, values];
  const letters = Object.fromEntries(Object.entries(SHORT).map(([k, v]) => [v, k]));
  const shown = values === undefined ? DEFAULT_SHOWN : [...values].map((c) => letters[c]).filter(Boolean);
  const known = outlook.okresy.some((o) => o.code === okres);
  let decoded = "";
  try {
    decoded = known && obec ? decodeURIComponent(obec) : "";
  } catch {
    // a broken link: no obec
  }
  return {
    day: outlook.days.includes(day) ? day : fallback.day,
    part: PARTS.includes(part) ? part : fallback.part,
    colour: ALL_LAYERS.includes(colour) ? colour : "temperature",
    shown: ALL_LAYERS.filter((l) => shown.includes(l)),
    okres: known ? okres : null,
    ...(decoded ? { obec: decoded } : {}),
  };
}

/**
 * Where a forecast-map hash belongs when it is not this page's: the old "#CZ0423" (the
 * detailed forecast per okres, now forecast-detail.html). The address to open, or null to stay.
 */
export function leaveFor(hash) {
  return /^#CZ\w{4}$/.test(hash ?? "") ? `forecast-detail.html${hash}` : null;
}

/**
 * How a change of the view goes into the browser's history: "push" (Back returns to the
 * view before) for another day, okres or obec, the steps people retrace; "replace" for
 * the part of the day, the colour and the values, which would only fill the history.
 * `before` and `after` are views as viewHash takes them.
 */
export function historyMode(before, after) {
  const differs = (key) => (before?.[key] ?? null) !== (after?.[key] ?? null);
  return ["day", "okres", "obec"].some(differs) ? "push" : "replace";
}

export function viewHash(view) {
  const values = ALL_LAYERS.filter((l) => view.shown.includes(l)).map((l) => SHORT[l]).join("") || "-";
  return `#${[view.day, view.part, view.colour, values, view.okres, view.okres && view.obec ? encodeURIComponent(view.obec) : null].filter(Boolean).join("/")}`;
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
      // with a single model only the parts it covers
      const has = (o) => { const row = rowFor(outlook, o.code, d, part); return row && !row.beyond; };
      if (outlook.okresy.some(has)) steps.push({ day: d, part });
    }
  }
  return steps;
}

/** Where a round starts: at the step shown now, or at the beginning. */
export function startIndex(steps, day, part) {
  return Math.max(0, steps.findIndex((s) => s.day === day && s.part === part));
}

/** The next map colour after a round: temperature → rain → wind → cloud → temperature. */
export function nextColour(colour, layers = LAYERS) {
  const i = layers.indexOf(colour);
  return layers[(i + 1) % layers.length];
}

const NUMERIC = ["tmin", "tmax", "precipitation", "rain_probability", "wind", "gust", "sunshine", "cloud"];

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

/**
 * Okres → fill colour for a day, part and colour layer (what fillExpression draws); a
 * single model's view colours rain by mm and greys the okresy beyond its horizon.
 */
export function okresColours(outlook, day, part, layer) {
  const ramp = rampKey(layer, mmView(outlook));
  return new Map(
    outlook.okresy.map((o) => {
      const row = rowFor(outlook, o.code, day, part);
      if (row?.beyond) return [o.code, BEYOND];
      // measured: grey where no station of the okres measures it
      if (outlook.observed && RAMPS[layer] && valueFor(row, layer, part) == null) return [o.code, BEYOND];
      return [o.code, RAMPS[layer] ? colorFor(valueFor(row, layer, part), ramp) : NEUTRAL];
    }),
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
