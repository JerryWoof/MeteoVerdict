// Test (forecast for a place): the obce on the forecast map from okres zoom on (the files
// of the okresy in view, obce-test.js): per obec its name and its value for the day and
// part shown, the bigger places first. Only with
// our combination (the obce have no single-model parts).
import { obecTimes } from "./obce-test.js";
import { colorFor, labelFor, mixColor, rampKey, valueFor } from "./tv.js";

// from about the zoom where one okres fills the map
export const MIN_ZOOM = 8.5;
// from this population a place is a town: larger text
const TOWN = 5000;
const PARTS = { night: [0, 6], morning: [6, 12], afternoon: [12, 18], evening: [18, 24] };
// as the outlook (outlook.py MIN_PART_HOURS, MIN_DAY_HOURS)
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
  for (const place of doc.places) {
    const acc = new Map();
    const entry = (day, part) => {
      const key = `${day}|${part}`;
      if (!acc.has(key)) acc.set(key, { t: [], w: [], p: 0, pn: 0 });
      return acc.get(key);
    };
    times.forEach((_, i) => {
      const temp = place.temperature_2m[i];
      const wind = place.wind_speed_10m[i];
      for (const part of [partOf(at[i].hour), "day"]) {
        const e = entry(at[i].day, part);
        if (temp != null) e.t.push(temp);
        if (wind != null) e.w.push(wind);
      }
      const rain = place.precipitation[i];
      if (rain != null) {
        for (const part of [partOf(before[i].hour), "day"]) {
          const e = entry(before[i].day, part);
          e.p += rain;
          e.pn += 1;
        }
      }
    });
    const rows = new Map();
    for (const [key, e] of acc) {
      const enough = key.endsWith("|day") ? MIN_DAY_HOURS : MIN_PART_HOURS;
      if (e.t.length < enough) continue;
      rows.set(key, {
        tmin: Math.min(...e.t),
        tmax: Math.max(...e.t),
        wind: e.w.length ? Math.max(...e.w) : null,
        precipitation: e.pn ? e.p : null,
        single: true,
      });
    }
    out.set(place.name, rows);
  }
  return out;
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
      "text-field": [
        "case",
        ["==", ["get", "extra"], ""],
        [
          "format",
          ["get", "name"], { "font-scale": 0.62, "text-color": "#4b5863" },
          "\n", {},
          ["get", "label"], { "text-font": ["literal", ["Noto Sans Bold"]], "text-color": ["get", "valueColor"] },
        ],
        [
          "format",
          ["get", "name"], { "font-scale": 0.62, "text-color": "#4b5863" },
          "\n", {},
          ["get", "label"], { "text-font": ["literal", ["Noto Sans Bold"]], "text-color": ["get", "valueColor"] },
          "\n", {},
          ["get", "extra"], { "font-scale": 0.62, "text-color": "#1f5f8b" },
        ],
      ],
      "text-font": ["Noto Sans Regular"],
      "text-size": ["case", [">=", ["coalesce", ["get", "population"], 0], TOWN], 19, 16],
      "text-anchor": "center",
      "text-line-height": 1.05,
      "text-max-width": 9,
      "text-padding": 6,
      "symbol-sort-key": ["-", ["coalesce", ["get", "population"], 0]],
    },
    paint: {
      "text-halo-color": ["case", ["get", "selected"], "#ffe08a", "rgba(255,255,255,0.92)"],
      "text-halo-width": ["case", ["get", "selected"], 3, 1.6],
    },
  });
  map.on("click", "obce-test-label", (event) => {
    const p = event.features[0].properties;
    onPick(p.okres, p.name);
  });
  map.on("mouseenter", "obce-test-label", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "obce-test-label", () => (map.getCanvas().style.cursor = ""));
}

// the values an obec has, in the order of the map's layers (no cloud for the obce)
const OBEC_LAYERS = ["temperature", "precipitation", "wind"];

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
          valueColor: value == null ? "#1d2329" : mixColor(colorFor(value, rampKey(layer, true)), "#1d2329", 0.4),
          label: layer ? labelFor(row, layer, state.part) : "",
          extra: others.map((l) => labelFor(row, l, state.part)).join(" · "),
        },
      });
    }
  }
  painted = features;
  map.getSource("obce-test")?.setData({ type: "FeatureCollection", features });
}
