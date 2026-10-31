// Test (forecast for a place): the obce on the forecast map from okres zoom on (the files
// of the okresy in view, obce-test.js): per obec its name and its value for the day and
// part shown, the bigger places first. Only with
// our combination (the obce have no single-model parts).
import { GUST_THRESHOLD } from "./models.js";
import { obecTimes } from "./obce-test.js";
import { isDark } from "./theme.js";
import { themeMap } from "./map-theme.js";
import { colorFor, labelFor, mixColor, rampKey, valueFor } from "./tv.js";

// from about the zoom where one okres fills the map
export const MIN_ZOOM = 8.5;
// from this population a place is a town: larger text
const TOWN = 5000;
const PARTS = { night: [0, 6], morning: [6, 12], afternoon: [12, 18], evening: [18, 24] };
// as outlook.json (a part needs 4 hours, a day 18)
const MIN_PART_HOURS = 4;
const MIN_DAY_HOURS = 18;
const HOUR = 3600000;

const local = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Prague", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23",
});

// "YYYY-MM-DD" and the hour (0-23), Prague time
function dayHour(ms) {
  const p = Object.fromEntries(local.formatToParts(ms).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) };
}

const partOf = (hour) => Object.keys(PARTS).find((k) => hour >= PARTS[k][0] && hour < PARTS[k][1]);

/**
 * Per obec a Map "day|part" → {tmin, tmax, precipitation, wind, single: true} (rain in
 * mm, as a single model's row), "day" for the whole day; as the outlook's summary:
 * temperature and wind at the hour, rain in the hour ending at the time.
 */
export function obcePartRows(doc) {
  const times = obecTimes(doc);
  const at = times.map((ms) => dayHour(ms));
  const before = times.map((ms) => dayHour(ms - HOUR));
  const out = new Map();
  const okres = okresPartValues(doc, times, at, before);
  for (const place of doc.places) {
    const acc = new Map();
    const entry = (day, part) => {
      const key = `${day}|${part}`;
      if (!acc.has(key)) acc.set(key, { t: [], w: [], p: 0, pn: 0, g: [], h: [], d: [], pr: [], x: 0, y: 0, dn: 0, wet: null });
      return acc.get(key);
    };
    times.forEach((_, i) => {
      const temp = place.temperature_2m[i];
      const wind = place.wind_speed_10m[i];
      const dir = place.wind_direction_10m?.[i];
      for (const part of [partOf(at[i].hour), "day"]) {
        const e = entry(at[i].day, part);
        if (temp != null) e.t.push(temp);
        if (wind != null) e.w.push(wind);
        const h = place.relative_humidity_2m?.[i];
        const d = place.dew_point_2m?.[i];
        const pr = place.pressure_msl?.[i];
        if (h != null) e.h.push(h);
        if (d != null) e.d.push(d);
        if (pr != null) e.pr.push(pr);
        // the mean direction: the vector mean weighted by the wind (a calm hour has no direction)
        if (dir != null) {
          const w = wind != null && wind > 0 ? wind : 1;
          e.x += w * Math.sin((dir * Math.PI) / 180);
          e.y += w * Math.cos((dir * Math.PI) / 180);
          e.dn += 1;
        }
      }
      const rain = place.precipitation[i];
      if (rain != null) {
        for (const part of [partOf(before[i].hour), "day"]) {
          const e = entry(before[i].day, part);
          e.p += rain;
          e.pn += 1;
        }
      }
      // the chance of a wet hour belongs to the hour before its time, like rain; a part keeps its highest
      const chance = place.precipitation_probability?.[i];
      if (chance != null) {
        for (const part of [partOf(before[i].hour), "day"]) {
          const e = entry(before[i].day, part);
          e.wet = e.wet == null ? chance : Math.max(e.wet, chance);
        }
      }
      // a gust belongs to the hour before its time, like rain
      const gust = place.wind_gusts_10m?.[i];
      if (gust != null) {
        for (const part of [partOf(before[i].hour), "day"]) entry(before[i].day, part).g.push(gust);
      }
    });
    const rows = new Map();
    const mean = (values) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);
    for (const [key, e] of acc) {
      const enough = key.endsWith("|day") ? MIN_DAY_HOURS : MIN_PART_HOURS;
      if (e.t.length < enough) continue;
      const gust = e.g.length ? Math.max(...e.g) : null;
      rows.set(key, {
        tmin: Math.min(...e.t),
        tmax: Math.max(...e.t),
        wind: e.w.length ? Math.max(...e.w) : null,
        precipitation: e.pn ? e.p : null,
        wet_hour_max: e.wet,
        gust,
        gust_over_threshold: gust == null ? null : gust >= GUST_THRESHOLD,
        humidity: mean(e.h),
        dew_point: mean(e.d),
        pressure: mean(e.pr),
        direction: e.dn && Math.hypot(e.x, e.y) > 1e-9 ? (Math.atan2(e.x, e.y) * 180 / Math.PI + 360) % 360 : null,
        okres: okres.get(key) ?? null,
        single: true,
      });
    }
    out.set(place.name, rows);
  }
  return out;
}

// the okres's own values that every obec of the file shares (doc.okres_values, MeteoVerdict AI's file):
// per "day|part" the further variables the obec panel names
const OKRES_AGGREGATE = {
  temperature_5cm: Math.min, visibility: Math.min, fog_probability: Math.max, cape: Math.max,
  snow_depth: Math.max, snow_depth_water_equivalent: Math.max,
};
const OKRES_MEAN = ["shortwave_radiation", "cloud_cover_low"];

function okresPartValues(doc, times, at, before) {
  const values = doc.okres_values;
  const out = new Map();
  if (!values) return out;
  const bucket = (key) => {
    if (!out.has(key)) out.set(key, {});
    return out.get(key);
  };
  const push = (key, variable, v) => {
    const b = bucket(key);
    (b[variable] ??= []).push(v);
  };
  times.forEach((_, i) => {
    for (const part of [partOf(at[i].hour), "day"]) {
      const key = `${at[i].day}|${part}`;
      for (const variable of [...Object.keys(OKRES_AGGREGATE), ...OKRES_MEAN]) {
        const v = values[variable]?.[i];
        if (v != null) push(key, variable, v);
      }
    }
    const snow = values.snowfall?.[i];
    if (snow != null) for (const part of [partOf(before[i].hour), "day"]) push(`${before[i].day}|${part}`, "snowfall", snow);
  });
  const result = new Map();
  for (const [key, b] of out) {
    const row = {};
    for (const [variable, list] of Object.entries(b)) {
      if (variable === "snowfall") row[variable] = list.reduce((a, c) => a + c, 0);
      else if (OKRES_MEAN.includes(variable)) row[variable] = list.reduce((a, c) => a + c, 0) / list.length;
      else row[variable] = OKRES_AGGREGATE[variable](...list);
    }
    result.set(key, row);
  }
  return result;
}

const empty = { type: "FeatureCollection", features: [] };
let painted = []; // the features last drawn

/** The okresy whose obce are drawn for the day and part shown (the others keep their marker). */
export const obceDrawn = () => new Set(painted.map((f) => f.properties.okres));

/** The obec found in the search (`lngLat`): the map goes there (its panel opens beside). */
export function goToObec(map, lngLat) {
  // the user's own choice: counts as their move (panel-room.js userMoved), so the map
  // stays there when the panel opens or closes
  map.easeTo({ center: lngLat, zoom: Math.max(map.getZoom(), 10.5) }, { originalEvent: "obce-search" });
}

/** The obec of `doc` nearest to `lat`, `lon` (the search's places are RÚIAN's, as ours). */
export function nearestObec(doc, lat, lon) {
  let best = null;
  let distance = Infinity;
  for (const place of doc?.places ?? []) {
    const d = (place.lat - lat) ** 2 + ((place.lon - lon) * Math.cos((lat * Math.PI) / 180)) ** 2;
    if (d < distance) [best, distance] = [place, d];
  }
  return best;
}

// the name small and the value large beneath it; colours of the name and of the extra values
function textField(dark) {
  const name = dark ? "#cfc7bb" : "#4b5863";
  const extra = dark ? "#8cc4e0" : "#1f5f8b";
  const value = ["get", "valueColor"];
  const head = [["get", "name"], { "font-scale": 0.62, "text-color": name }, "\n", {}, ["get", "label"], { "text-font": ["literal", ["Noto Sans Bold"]], "text-color": value }];
  return [
    "case",
    ["==", ["get", "extra"], ""],
    ["format", ...head],
    ["format", ...head, "\n", {}, ["get", "extra"], { "font-scale": 0.62, "text-color": extra }],
  ];
}

// the dark halo is the page's dark; the selected place's yellow turns a dull gold
const haloColor = (dark) => ["case", ["get", "selected"], dark ? "#6b5316" : "#ffe08a", dark ? "rgba(21,20,18,0.9)" : "rgba(255,255,255,0.92)"];

/** The source and its layer (once the map has loaded); a click on a label calls `onPick(okres, name)`. */
export function addObceLayers(map, onPick) {
  map.addSource("obce-test", { type: "geojson", data: empty });
  // as yr.no and Windy draw places: no dots, the name small and the value large beneath it;
  // the bigger places are placed first and the rest only where they fit, so zooming in
  // fills the gaps with villages
  map.addLayer({
    id: "obce-test-label",
    type: "symbol",
    source: "obce-test",
    minzoom: MIN_ZOOM,
    layout: {
      // the name, the main value (temperature, or the first value ticked) and the other
      // values ticked under "Values at each okres and village" (rain, wind) small beneath
      "text-field": textField(false),
      "text-font": ["Noto Sans Regular"],
      "text-size": ["case", [">=", ["coalesce", ["get", "population"], 0], TOWN], 19, 16],
      "text-anchor": "center",
      "text-line-height": 1.05,
      "text-max-width": 9,
      "text-padding": 6,
      "symbol-sort-key": ["-", ["coalesce", ["get", "population"], 0]],
    },
    paint: {
      "text-halo-color": haloColor(false),
      "text-halo-width": ["case", ["get", "selected"], 3, 1.6],
    },
  });
  themeMap(map, {
    "obce-test-label": { "layout:text-field": [textField(false), textField(true)], "text-halo-color": [haloColor(false), haloColor(true)] },
  })();
  map.on("click", "obce-test-label", (event) => {
    const p = event.features[0].properties;
    onPick(p.okres, p.name);
  });
  map.on("mouseenter", "obce-test-label", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "obce-test-label", () => (map.getCanvas().style.cursor = ""));
}

// the values an obec has, in the order of the map's layers (no cloud for the obce)
const OBEC_LAYERS = ["temperature", "precipitation", "wind"];

// the scale's colour, darkened to read as text on the light map, lightened on the dark one
function valueColor(value, layer) {
  const dark = isDark();
  if (value == null) return dark ? "#ece7df" : "#1d2329";
  return mixColor(colorFor(value, rampKey(layer, true)), dark ? "#ffffff" : "#1d2329", dark ? 0.3 : 0.4);
}

/** Draw the obce for `state` (day, part, the values ticked in `shown`); `docs`: [{doc,
 * rows}]; none = hidden; `selected`: the obec whose panel is open (a yellow halo). */
export function paintObce(map, docs, state, selected = null) {
  const features = [];
  const ticked = OBEC_LAYERS.filter((l) => state.shown.includes(l));
  // the main value: the temperature, else the first value ticked; nothing ticked: the name
  const layer = ticked[0] ?? null;
  const others = ticked.slice(1);
  for (const { doc, rows } of docs) {
    for (const place of doc.places) {
      const row = rows.get(place.name)?.get(`${state.day}|${state.part}`);
      if (!row) continue;
      const value = layer ? valueFor(row, layer, state.part) : null;
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [place.lon, place.lat] },
        properties: {
          name: place.name,
          okres: doc.okres,
          elevation: Math.round(place.elevation),
          population: place.population ?? null,
          selected: place.name === selected,
          // the scale's colour, darkened to read as text on the map
          valueColor: valueColor(value, layer),
          label: layer ? labelFor(row, layer, state.part) : "",
          extra: others.map((l) => labelFor(row, l, state.part)).join(" · "),
        },
      });
    }
  }
  painted = features;
  map.getSource("obce-test")?.setData({ type: "FeatureCollection", features });
}
