import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NO_DATA, TOO_FEW, bestByRegion, fillExpression, modelColors, records,
  regionColor, stationFeatures,
} from "./data.js";


// the layout `mvd aggregate` writes (aggregate.JSON_COLUMNS, a subset)
const DOC = {
  columns: ["region", "region_name", "lead_day", "model", "mae", "enough_stations", "rank", "tied_with_best"],
  rows: [
    ["CZ020", "Středočeský kraj", 1, "icon", 1.2, true, 1, false],
    ["CZ020", "Středočeský kraj", 1, "ifs", 1.25, true, 2, true],
    ["CZ020", "Středočeský kraj", 1, "blend", 1.1, true, null, true],
    ["CZ020", "Středočeský kraj", 2, "ifs", 1.5, true, 1, false],
    ["CZ010", "Praha", 1, "ifs", 1.0, false, 1, false],
  ],
};
const MODELS = { icon: "DWD ICON-D2", ifs: "ECMWF IFS", blend: "Mean of all models" };

test("records", () => {
  assert.deepEqual(records(DOC)[0].region_name, "Středočeský kraj");
  assert.deepEqual(records(null), []);
});

test("colours follow the model order and skip the blend", () => {
  assert.deepEqual(Object.keys(modelColors(MODELS)), ["icon", "ifs"]);
});

test("best model per region at one lead day, with ties but without the blend", () => {
  const best = bestByRegion(records(DOC), 1);
  assert.deepEqual(best.get("CZ020"), {
    name: "Středočeský kraj", model: "icon", mae: 1.2, tied: ["ifs"], enough: true, ranked: true,
    borrowed: 0,
  });
  assert.equal(bestByRegion(records(DOC), 2).get("CZ020").model, "ifs");
});

test("region colours: best model, too few stations, no data", () => {
  const colors = modelColors(MODELS);
  const best = bestByRegion(records(DOC), 1);
  assert.equal(regionColor(best.get("CZ020"), colors), colors.icon);
  assert.equal(regionColor(best.get("CZ010"), colors), TOO_FEW);
  assert.equal(regionColor(undefined, colors), NO_DATA);
  const expression = fillExpression(best, colors);
  assert.deepEqual(expression.slice(0, 4), ["match", ["get", "code"], "CZ020", colors.icon]);
  assert.equal(expression.at(-1), NO_DATA);
  assert.equal(fillExpression(new Map(), colors), NO_DATA);
});

test("station dots only where there are scores", () => {
  const stations = { columns: ["id", "name", "lat", "lon"], rows: [["CZ020", "A", 50, 14], ["x", "B", 49, 15]] };
  const points = stationFeatures(stations, bestByRegion(records(DOC), 1), modelColors(MODELS));
  assert.equal(points.features.length, 1);
  assert.deepEqual(points.features[0].geometry.coordinates, [14, 50]);
});

test("unranked variables take the lowest MAE, never the blend", () => {
  const doc = {
    columns: ["region", "region_name", "lead_day", "model", "mae", "enough_stations", "rank"],
    rows: [
      ["CZ020", "S", 1, "icon", 1.4, true, null],
      ["CZ020", "S", 1, "ifs", 1.3, true, null],
      ["CZ020", "S", 1, "blend", 1.0, true, null],
    ],
  };
  const entry = bestByRegion(records(doc), 1).get("CZ020");
  assert.equal(entry.model, "ifs");
  assert.equal(entry.ranked, false);
});

test("an okres knows how many stations it borrowed", () => {
  const doc = {
    columns: ["region", "region_name", "lead_day", "model", "mae", "enough_stations", "rank", "borrowed"],
    rows: [["CZ0201", "Benešov", 1, "ifs", 1.1, true, 1, 2]],
  };
  const entry = bestByRegion(records(doc), 1).get("CZ0201");
  assert.equal(entry.borrowed, 2);
});

