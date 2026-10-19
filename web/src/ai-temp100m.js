// The AI tab's extra map colour: MeteoVerdict AI's temperature at 100 m from the terrain
// (data/scores/ai/fc/temp100m.json and the image it names, transparent outside Czechia,
// its rows already in the map's spacing). Without a valid file the choice is not offered.

export const TEMP100M_JSON = "data/scores/ai/fc/temp100m.json";

const TIME_ZONE = "Europe/Prague";
const finite = (v) => typeof v === "number" && Number.isFinite(v);
const COLOR = /^#[0-9a-f]{6}$/i;

/**
 * The file's parts the map needs, or null when it is not usable: `url` the image (relative
 * to the json), `coordinates` its corners for a MapLibre image source, `time` (ms),
 * `min`/`max`/`unit` and `stops` [{value, color}] for the legend.
 */
export function parseTemp100m(doc, jsonPath = TEMP100M_JSON) {
  if (!doc || typeof doc !== "object") return null;
  const b = doc.bounds;
  if (!Array.isArray(b) || b.length !== 4 || !b.every(finite)) return null;
  const [west, south, east, north] = b;
  if (!(west < east && south < north)) return null;
  const time = Date.parse(doc.time);
  if (typeof doc.png !== "string" || !/^[\w.-]+\.png$/.test(doc.png) || Number.isNaN(time)) return null;
  const stops = Array.isArray(doc.colormap)
    ? doc.colormap.filter((s) => finite(s?.value) && COLOR.test(s?.color ?? "")).sort((a, b) => a.value - b.value)
    : [];
  if (stops.length < 2) return null;
  const min = finite(doc.legend?.min) ? doc.legend.min : stops[0].value;
  const max = finite(doc.legend?.max) ? doc.legend.max : stops.at(-1).value;
  if (!(min < max)) return null;
  return {
    url: jsonPath.replace(/[^/]*$/, doc.png),
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
    time,
    min,
    max,
    unit: typeof doc.legend?.unit === "string" ? doc.legend.unit : "°C",
    stops: stops.map(({ value, color }) => ({ value, color })),
  };
}

/** The legend's CSS gradient, the stops placed between min and max. */
export function temp100mGradient({ stops, min, max }) {
  const at = (v) => Math.round(Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100)) * 10) / 10;
  return `linear-gradient(to right, ${stops.map((s) => `${s.color} ${at(s.value)}%`).join(", ")})`;
}

const pragueParts = (ms) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(ms);
  const get = (type) => parts.find((p) => p.type === type).value;
  return { day: `${get("year")}-${get("month")}-${get("day")}`, hour: Number(get("hour")), clock: `${get("hour")}:${get("minute")}` };
};

/**
 * When the image is for, Prague time: `key` "tonight" (this evening, the night after
 * today until 06:00, or after midnight the night still going on), "today", "tomorrow" or null (another day: `day` its date), and `clock`.
 */
export function temp100mWhen(time, now) {
  const at = pragueParts(time);
  const today = pragueParts(now).day;
  const offset = Math.round((Date.parse(`${at.day}T12:00Z`) - Date.parse(`${today}T12:00Z`)) / 86400000);
  let key = null;
  if ((offset === 0 && (at.hour >= 18 || at.hour < 6)) || (offset === 1 && at.hour < 6)) key = "tonight";
  else if (offset === 0) key = "today";
  else if (offset === 1) key = "tomorrow";
  return { key, day: at.day, clock: at.clock };
}

/** "dnes v noci 02:00", "tomorrow 14:00", "St 21. 10. 14:00" (`t` the translator). */
export function temp100mTimeText(time, now, language, t) {
  const when = temp100mWhen(time, now);
  if (when.key) return t(`ai.temp100m.${when.key}`, { time: when.clock });
  const date = new Intl.DateTimeFormat(language, { timeZone: "UTC", weekday: "short", day: "numeric", month: "numeric" })
    .format(Date.parse(`${when.day}T12:00Z`));
  return `${date} ${when.clock}`;
}
