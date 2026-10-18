// Test (forecast for a place): the obce of the okresy that have an obce file
// (obce-test.js, Litoměřice) on the forecast map from okres zoom on, a dot per obec
// coloured and labelled like the okres markers for the day and part shown. Only with
// our combination (the obce have no single-model parts).
import { obecTimes } from "./obce-test.js";
import { colorFor, labelFor, rampKey, valueFor } from "./tv.js";

export const OBCE_OKRESY = ["CZ0423"];
// from about the zoom where one okres fills the map
export const MIN_ZOOM = 8.5;
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

/** Whether any obce are drawn for the day and part shown (else their okres keeps its marker). */
export const obceDrawn = () => painted.length > 0;

/** The obec chosen in the picker: the map goes there (its panel opens beside). */
export function goToObec(map, name) {
  const feature = painted.find((f) => f.properties.name === name);
  // the user's own choice: counts as their move (panel-room.js userMoved), so the map
  // stays there when the panel opens or closes
  if (feature) {
    map.easeTo({ center: feature.geometry.coordinates, zoom: Math.max(map.getZoom(), 10.5) }, { originalEvent: "obce-picker" });
  }
}

/** The source and layers (once the map has loaded); a click on a dot calls `onPick(okres, name)`. */
export function addObceLayers(map, onPick) {
  map.addSource("obce-test", { type: "geojson", data: empty });
  map.addLayer({
    id: "obce-test-dot",
    type: "circle",
    source: "obce-test",
    minzoom: MIN_ZOOM,
    paint: {
      "circle-color": ["get", "color"],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], MIN_ZOOM, 4, 11, 7],
      "circle-stroke-color": "#1d2329",
      "circle-stroke-width": 0.8,
    },
  });
  map.addLayer({
    id: "obce-test-label",
    type: "symbol",
    source: "obce-test",
    minzoom: MIN_ZOOM,
    layout: {
      "text-field": ["get", "label"],
      "text-font": ["Noto Sans Regular"],
      "text-size": 11,
      "text-offset": [0, 1.1],
      "text-anchor": "top",
    },
    paint: { "text-color": "#1d2329", "text-halo-color": "#ffffff", "text-halo-width": 1.4 },
  });
  // the names from where they fit beside the values
  map.addLayer({
    id: "obce-test-name",
    type: "symbol",
    source: "obce-test",
    minzoom: 9.5,
    layout: {
      "text-field": ["get", "name"],
      "text-font": ["Noto Sans Regular"],
      "text-size": 10,
      "text-offset": [0, -0.9],
      "text-anchor": "bottom",
      "text-max-width": 8,
    },
    paint: { "text-color": "#4b5863", "text-halo-color": "#ffffff", "text-halo-width": 1.2 },
  });
  map.on("click", "obce-test-dot", (event) => {
    const p = event.features[0].properties;
    onPick(p.okres, p.name);
  });
  map.on("mouseenter", "obce-test-dot", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "obce-test-dot", () => (map.getCanvas().style.cursor = ""));
}

/** Draw the obce for `state` (day, part, colour); `docs`: [{doc, rows}]; none = hidden;
 * `selected`: the obec whose panel is open (a thicker ring). */
export function paintObce(map, docs, state, selected = null) {
  const features = [];
  const layer = state.colour;
  for (const { doc, rows } of docs) {
    for (const place of doc.places) {
      const row = rows.get(place.name)?.get(`${state.day}|${state.part}`);
      if (!row) continue;
      const value = layer === "cloud" ? null : valueFor(row, layer, state.part);
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [place.lon, place.lat] },
        properties: {
          name: place.name,
          okres: doc.okres,
          elevation: Math.round(place.elevation),
          color: colorFor(value, rampKey(layer, true)),
          label: labelFor(row, layer === "cloud" ? "temperature" : layer, state.part),
        },
      });
    }
  }
  painted = features;
  if (!map.getLayer("obce-test-dot")) return;
  map.getSource("obce-test").setData({ type: "FeatureCollection", features });
  map.setPaintProperty("obce-test-dot", "circle-stroke-width", ["case", ["==", ["get", "name"], selected ?? ""], 3, 0.8]);
}
