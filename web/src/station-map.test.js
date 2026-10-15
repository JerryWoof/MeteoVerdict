import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ELEVATION_STOPS, KINDS, KIND_COLORS, classifyStation, colorExpression, elementFor, elevationGradient, filterStations, hasElements,
  kindCounts, measureCounts, measures, nearestStation, stationFeatures, withCoordinates,
} from "./station-map.js";
import { STRINGS } from "./i18n.js";

const LIBUS = {
  id: "0-20000-0-11520", name: "Praha, Libuš", lat: 50.0078, lon: 14.4469, elevation: 302,
  views: ["10min", "1hour", "daily", "monthly"], elements: ["T", "SRA", "SSV", "T10", "SCE"],
};
const AUTO_CLIMATE = { id: "0-203-0-11401", name: "Aš", lat: 50.22, lon: 12.19, elevation: 675, views: ["10min", "daily"], elements: ["T", "SRA"] };
const RAIN = { id: "0-203-0-10803062001", name: "Bavorov", lat: 49.12, lon: 14.08, elevation: 416, views: ["daily", "monthly"], elements: ["SRA", "SCE", "SNO"] };
const ODD = { id: "0-203-0-1", name: "Radiace", lat: 49.5, lon: 16, elevation: null, views: ["10min"], elements: ["RGLB10"] };

test("kinds of station", () => {
  // from the index's network (ČHMÚ metadata)
  const snow = { id: "0-203-0-10102004001", network: "snow", views: ["10min"], elements: ["T", "SCEa"] };
  assert.deepEqual(classifyStation(snow), { kind: "snow", automatic: true });
  assert.deepEqual(classifyStation({ ...RAIN, network: "precipitation" }), { kind: "precipitation", automatic: false });
  assert.deepEqual(classifyStation({ ...LIBUS, network: "main" }), { kind: "main", automatic: true });
  assert.deepEqual(classifyStation({ id: "0-203-0-3", network: "precipitation_auto" }), { kind: "precipitation_auto", automatic: true });
  assert.deepEqual(classifyStation({ id: "0-203-0-4", network: "climate_manual" }), { kind: "climate_manual", automatic: false });
  // an index without networks: guessed from the id, elements and 10-minute values
  assert.deepEqual(classifyStation(LIBUS), { kind: "main", automatic: true });
  assert.deepEqual(classifyStation(AUTO_CLIMATE), { kind: "climate", automatic: true });
  assert.deepEqual(classifyStation(RAIN), { kind: "precipitation", automatic: false });
  assert.deepEqual(classifyStation({ ...RAIN, views: ["10min", "daily"] }), { kind: "precipitation_auto", automatic: true });
  assert.deepEqual(classifyStation({ ...AUTO_CLIMATE, views: ["daily"] }), { kind: "climate_manual", automatic: false });
  assert.deepEqual(classifyStation(ODD), { kind: "other", automatic: true });
  // unknown network: the guess
  assert.deepEqual(classifyStation({ ...RAIN, network: "amateur" }), { kind: "precipitation", automatic: false });
  // an index without elements: only main stations stand out
  assert.deepEqual(classifyStation({ id: "0-203-0-2", views: ["daily"] }), { kind: "station", automatic: false });
  assert.deepEqual(classifyStation({ id: "0-20000-0-11406" }), { kind: "main", automatic: false });
  assert.deepEqual(kindCounts([RAIN, LIBUS, RAIN, AUTO_CLIMATE, snow]), [["main", 1], ["climate", 1], ["snow", 1], ["precipitation", 2]]);
});

test("every kind has a colour and both languages name it", () => {
  for (const kind of KINDS) {
    assert.match(KIND_COLORS[kind], /^#[0-9a-f]{6}$/);
    for (const language of ["cs", "en"]) {
      assert.ok(STRINGS[language][`map.kind.${kind}`], `${language} map.kind.${kind}`);
      assert.ok(STRINGS[language][`map.one.${kind}`], `${language} map.one.${kind}`);
    }
  }
  assert.ok(STRINGS.en["map.network"].includes("no amateur stations"));
});

test("coordinates from the stations table where the index has none", () => {
  const table = {
    columns: ["id", "name", "lat", "lon", "elevation"],
    rows: [["0-203-0-11401", "Aš", 50.22, 12.19, 675], ["0-203-0-9", "X", null, null, 1]],
  };
  const out = withCoordinates([{ id: "0-203-0-11401", name: "Aš" }, { id: "0-203-0-9" }, { id: "0-203-0-8" }, LIBUS], table);
  assert.deepEqual(out.map((s) => s.id), ["0-203-0-11401", LIBUS.id]);
  assert.equal(out[0].lat, 50.22);
  assert.equal(out[0].lon, 12.19);
  assert.equal(out[1], LIBUS); // already placed: kept as it is
  assert.deepEqual(withCoordinates([LIBUS], null), [LIBUS]);
  assert.deepEqual(withCoordinates(null, table), []);
});

test("only stations measuring something", () => {
  const all = [LIBUS, AUTO_CLIMATE, RAIN, ODD];
  assert.ok(hasElements(all));
  assert.ok(!hasElements([...all, { id: "x" }]));
  assert.ok(!hasElements([]));
  assert.ok(measures(RAIN, null));
  assert.ok(measures(RAIN, "snow"));
  assert.ok(!measures(RAIN, "sunshine"));
  assert.ok(!measures({ id: "x" }, "snow"));
  assert.ok(!measures(RAIN, "no-such-group"));
  assert.deepEqual(filterStations(all, "soil").map((s) => s.name), ["Praha, Libuš"]);
  assert.deepEqual(filterStations(all, "temperature").map((s) => s.name), ["Praha, Libuš", "Aš"]);
  assert.equal(filterStations(all, "").length, 4);
  const counts = Object.fromEntries(measureCounts(all));
  assert.equal(counts.precipitation, 3);
  assert.equal(counts.radiation, 1);
  assert.equal(counts.pressure, undefined); // nobody: not offered
  assert.equal(elementFor(LIBUS, "soil"), "T10");
  assert.equal(elementFor(RAIN, "snow"), "SCE");
  assert.equal(elementFor(RAIN, "sunshine"), null);
  assert.equal(elementFor(RAIN, null), null);
});

test("map points", () => {
  const { type, features } = stationFeatures([LIBUS, RAIN, ODD]);
  assert.equal(type, "FeatureCollection");
  assert.deepEqual(features[0].geometry, { type: "Point", coordinates: [14.4469, 50.0078] });
  assert.deepEqual(features[0].properties, { id: LIBUS.id, name: "Praha, Libuš", kind: "main", automatic: 1, elevation: 302 });
  assert.equal(features[1].properties.automatic, 0);
  assert.equal(features[2].properties.elevation, null);
});

test("colours and the nearest station", () => {
  const kind = colorExpression("kind");
  assert.equal(kind[0], "match");
  assert.ok(kind.includes("precipitation"));
  const height = colorExpression("elevation");
  assert.equal(height[0], "case");
  assert.equal(height[3].length, 3 + ELEVATION_STOPS.length * 2);
  assert.match(elevationGradient(), /^linear-gradient\(to right, #1a9850 0%, .* #54278f 100%\)$/);
  assert.equal(nearestStation([LIBUS, AUTO_CLIMATE, RAIN], [14.4, 50.1]), LIBUS);
  assert.equal(nearestStation([LIBUS, AUTO_CLIMATE, RAIN], [12.5, 50]), AUTO_CLIMATE);
  assert.equal(nearestStation([], [14, 50]), null);
});
