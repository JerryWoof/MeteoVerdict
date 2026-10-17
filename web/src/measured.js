// "Measured weather": the landing of the station page (measured.html), the forecast
// map's look for what ČHMÚ's stations measured. Each station with its own values of a
// day and part of day, from data/scores/observed/<day>-stations.json (`mvd
// observed-map`, docs/data-sources.md#observed-map), its position and kind from
// data/scores/station/index.json. Pure helpers; the page is station-page.js, the map
// measured-map-view.js.

import { dayLength } from "./diary.js";
import { PARTS, isDark, observedSymbol } from "./observed.js";
import { classifyStation } from "./station-map.js";
import { CAPITALS, TIME_ZONE, displayName, labelFor, parseView, placeMarkers, valueFor, viewHash } from "./tv.js";

/** The kinds-of-station map (the station page's map before the measured weather). */
export const KINDS_HASH = "#kinds";
/** Day tabs: the last three measured days (yesterday first); any other day through the date field. */
export const MAX_TABS = 3;

const ISO = /^\d{4}-\d{2}-\d{2}$/;

/**
 * What the station page shows for a hash: "measured" (the landing: no hash, or
 * "#day/part/colour/values" as on the forecast map), "kinds" (the map of the kinds of
 * station) or "station" (a station: "#WSI" or "#WSI/element").
 */
export function pageMode(hash) {
  const h = (hash ?? "").replace(/^#/, "");
  if (!h || /^\d{4}-\d{2}-\d{2}(\/|$)/.test(h)) return "measured";
  if (`#${h}` === KINDS_HASH) return "kinds";
  return "station";
}

/** The layer the landing opens with: the okresy (the mean of each okres's stations). */
export const DEFAULT_LAYER = "okresy";
const LAYERS = ["okresy", "stations"];

/**
 * The landing's view from the hash "#day/part/colour/values[/okresy|/stations|/CZxxxx]"
 * (the forecast map's format): {day, part, colour, shown, layer, okres}. `layer` is
 * "okresy" (the mean of each okres's stations, with `okres` the open okres panel; the
 * default, DEFAULT_LAYER) or "stations" (each station's own values). `days` the
 * measured days offered, `fallback` {day, part}.
 */
export function parseLanding(hash, days, fallback) {
  const h = (pageMode(hash) === "measured" ? hash ?? "" : "").replace(/^#/, "");
  const segments = h.split("/");
  const isLayer = (s) => LAYERS.includes(s) || /^CZ/.test(s ?? "");
  const extra = segments[4] ?? (isLayer(segments[3]) ? segments[3] : undefined);
  const forView = isLayer(segments[3]) && !/^CZ/.test(segments[3]) ? segments.slice(0, 3).join("/") : h;
  const { day, part, colour, shown } = parseView(forView, { days, okresy: [] }, fallback);
  const layer = extra === "stations" ? "stations" : extra === "okresy" || /^CZ\d{3,4}$/.test(extra ?? "") ? "okresy" : DEFAULT_LAYER;
  return { day, part, colour, shown, layer, okres: layer === "okresy" && /^CZ/.test(extra ?? "") ? extra : null };
}

/** The landing's hash (the forecast map's format, plus the layer unless the default). */
export function landingHash(view) {
  const layer = view.layer === "stations" ? "stations" : view.okres ?? null; // okresy: the default
  return viewHash({ ...view, okres: layer });
}

/** The newest measured day before today (the landing opens on it), or null. */
export function defaultDay(index, todayIso) {
  const past = index.days.filter((d) => d.day < todayIso);
  return past.at(-1)?.day ?? null;
}

/**
 * The day tabs, newest first ("Yesterday", "Thursday", "Wednesday", …): the measured days
 * before today with parts of day (at most `count`), then `selected` when it is an older
 * measured day (from the date field).
 */
export function dayTabs(index, todayIso, selected = null, count = MAX_TABS) {
  const past = index.days.filter((d) => d.day < todayIso);
  const tabs = past.filter((d) => d.source !== "daily").slice(-count).map((d) => d.day).reverse();
  if (!tabs.length) tabs.push(...past.slice(-2).map((d) => d.day).reverse());
  if (selected && selected < todayIso && index.byDay.has(selected) && !tabs.includes(selected)) tabs.push(selected);
  return tabs;
}

// --- daylight of a part of the day ----------------------------------------------------
const PART_HOURS = { night: [0, 6], morning: [6, 12], afternoon: [12, 18], evening: [18, 24], day: [0, 24] };
const pragueHour = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, hour: "numeric", hourCycle: "h23" });

/** Hours Prague time is ahead of UTC on a day (1 in winter, 2 in summer). */
export function pragueOffset(iso) {
  return Number.parseInt(pragueHour.format(Date.parse(`${iso}T12:00:00Z`)), 10) - 12;
}

/** Sunrise and sunset at a place on a day, as hours of the Prague clock (decimal). */
export function sunTimes(lat, lon, iso) {
  const length = dayLength(lat, iso);
  const n = Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.UTC(Number(iso.slice(0, 4)), 0, 1)) / 86_400_000) + 1;
  const b = (2 * Math.PI * (n - 81)) / 364;
  const equation = 9.87 * Math.sin(2 * b) - 7.53 * Math.cos(b) - 1.5 * Math.sin(b); // minutes
  const noon = 12 - lon / 15 - equation / 60 + pragueOffset(iso);
  return { rise: noon - length / 2, set: noon + length / 2 };
}

/** Hours of daylight of a part of the day at a place (the symbol's sunshine share). */
export function partDaylight(lat, lon, iso, part) {
  const hours = PART_HOURS[part];
  if (!hours || lat == null || lon == null) return null;
  const { rise, set } = sunTimes(lat, lon, iso);
  const value = Math.max(0, Math.min(hours[1], set) - Math.max(hours[0], rise));
  return Math.round(value * 10) / 10;
}

// --- the stations' rows -----------------------------------------------------------------
const COLUMN_OF = { tmax: "tmax", tmin: "tmin", precipitation: "r", wind: "wind", gust: "gust", sunshine: "ssv", cloud: "cloud" };

/** Order of the labels when they collide: main (WMO) stations, then the automatic
 * climate stations, the mountain ones, the rest that measure temperature, rain gauges. */
const PRIORITY = { main: 1, climate: 2, snow: 3, climate_manual: 4, other: 4, station: 4, precipitation_auto: 5, precipitation: 6 };

/** Label priority of a row (smaller first); `selected` always first, then the row's own
 * `priority` (okresy), else by the kind of station. */
export function labelPriority(row, selected = null) {
  if (row.id === selected) return 0;
  return row.priority ?? PRIORITY[row.kind] ?? 6;
}

/**
 * The okres layer's rows: one per okres of a measured day's view (observed.js
 * parseObservedDay) with a value in `part`, at the okres's point, as the map's labels
 * take them; the kraj capitals' okresy first when labels collide (as on the forecast map).
 */
export function okresRows(view, part) {
  if (!view?.rows) return [];
  const rows = [];
  for (const o of view.okresy) {
    const row = view.rows.get(`${o.code}|${view.day}|${part}`);
    if (!row || o.lat == null || o.lon == null) continue;
    if (!["tmax", "tmin", "precipitation", "wind", "gust", "sunshine", "cloud"].some((k) => row[k] != null)) continue;
    rows.push({
      ...row, id: o.code, name: displayName(o.name), lat: o.lat, lon: o.lon, okresCode: o.code,
      priority: CAPITALS.includes(o.code) ? 1 : 2,
    });
  }
  return rows;
}

/**
 * One row per station with a value in `part` of the day's stations file `doc`, with its
 * position and kind from the station index: {id, name, lat, lon, kind, automatic,
 * measured: true, tmax, tmin, precipitation, wind, gust, sunshine, cloud, light, symbol,
 * dark}. The symbol as on the forecast map's past days (observed.js observedSymbol, with
 * the station's own daylight): only from what the station measured, so a rain gauge has
 * one only on a wet day.
 */
export function stationRows(doc, index, part) {
  if (!doc?.stations || !index) return [];
  const parts = doc.parts ?? PARTS;
  const p = parts.indexOf(part);
  const columns = doc.columns ?? [];
  if (p < 0 || !columns.length) return [];
  const at = Object.fromEntries(Object.entries(COLUMN_OF).map(([key, column]) => [key, columns.indexOf(column)]));
  const where = new Map((index.stations ?? index).map((s) => [s.id, s]));
  const rows = [];
  for (const [id, values] of Object.entries(doc.stations)) {
    const s = where.get(id);
    if (!s || s.lat == null || s.lon == null) continue;
    const pick = (key) => (at[key] >= 0 ? values[p * columns.length + at[key]] ?? null : null);
    const row = { id, name: s.name ?? id, lat: s.lat, lon: s.lon, okres: s.okres ?? null, measured: true };
    for (const key of Object.keys(COLUMN_OF)) row[key] = pick(key);
    if (!Object.keys(COLUMN_OF).some((key) => row[key] != null)) continue;
    const { kind, automatic } = classifyStation(s);
    row.kind = kind;
    row.automatic = automatic;
    row.light = partDaylight(s.lat, s.lon, doc.day, part);
    // what the station measured only: no phenomena or new snow in this file
    row.symbol = observedSymbol({ ...row, ph: [], sno: null }, doc.day);
    row.dark = isDark(part, row.light);
    rows.push(row);
  }
  return rows;
}

/** Does the row have anything to show for the values chosen (its label would not be empty)? */
export function hasLabel(row, shown, part) {
  return Boolean(row.symbol) || shown.some((layer) => valueFor(row, layer, part) != null);
}

/**
 * The size of a station's label on the map (px), as the forecast map's markers lay it
 * out: the symbol (30 px) and the temperature in a row, the other values as chips
 * below, wrapped at 115 px. An estimate, for placing them without measuring each.
 */
export function labelSize(row, shown, part) {
  const temperature = shown.includes("temperature") && valueFor(row, "temperature", part) != null;
  const topWidth = (row.symbol ? 30 : 0) + (temperature ? 9 * labelFor(row, "temperature", part).length + 4 : 0);
  const topHeight = row.symbol ? 30 : temperature ? 20 : 0;
  const chips = shown
    .filter((l) => l !== "temperature" && valueFor(row, l, part) != null)
    .map((l) => 11 + 6.2 * labelFor(row, l, part).length + 10);
  let rows = 0;
  let width = 0;
  let line = Infinity;
  for (const w of chips) {
    if (line + w > 115) {
      rows += 1;
      line = w;
    } else line += w + 2;
    width = Math.max(width, Math.min(115, line));
  }
  return { w: Math.max(topWidth, width, 12), h: Math.max(topHeight + rows * 15, 12) };
}

/**
 * Which stations get a label: the rows with something to show, by priority (main
 * stations first: at the country's zoom they are what is labelled), each placed only
 * where it overlaps no label placed before. `project(row)` → {x, y} on the screen;
 * `width`, `height` the map's size (labels off the map are left out). Returns the ids.
 */
export function pickLabels(rows, { shown, part, project, width, height, selected = null, gap = 3 }) {
  const boxes = rows
    .filter((r) => hasLabel(r, shown, part) || r.id === selected)
    .map((r) => {
      const { x, y } = project(r);
      return { code: r.id, x, y, ...labelSize(r, shown, part), priority: labelPriority(r, selected) };
    })
    .filter((b) => b.x >= -b.w / 2 && b.y >= -b.h / 2 && b.x <= width + b.w / 2 && b.y <= height + b.h / 2)
    .sort((a, b) => (a.code < b.code ? -1 : 1)); // the same stations win every time
  return placeMarkers(boxes, gap);
}

const best = (rows, value, better) =>
  rows.reduce((a, b) => (value(b) != null && (a == null || better(value(b), value(a))) ? b : a), null);

/**
 * Headline of the stations' day and part: the warmest station (highest maximum; at night
 * the highest minimum) and the coldest (lowest minimum), the wettest, how many had at
 * least 1 mm (of those measuring precipitation), the strongest gust and the most sunshine;
 * each {id, name, value} or null. `stations`: how many have any value.
 */
export function stationSummary(rows, part) {
  const pick = (value, better) => {
    const hit = best(rows, value, better);
    return hit ? { id: hit.id, name: hit.name, value: value(hit) } : null;
  };
  const up = (a, b) => a > b;
  const down = (a, b) => a < b;
  const rain = rows.filter((r) => r.precipitation != null);
  return {
    warmest: pick((r) => (part === "night" ? r.tmin : r.tmax), up),
    coldest: pick((r) => r.tmin, down),
    wettest: pick((r) => r.precipitation, up),
    wet: rain.filter((r) => r.precipitation >= 1).length,
    rainStations: rain.length,
    gust: pick((r) => r.gust, up),
    sunniest: pick((r) => r.sunshine, up),
    stations: rows.length,
  };
}

/** The station page of a station with its diary on `day` (from the landing's map). */
export function stationHref(id, day) {
  return `${day && ISO.test(day) ? `?day=${day}` : ""}#${encodeURIComponent(id)}`;
}
