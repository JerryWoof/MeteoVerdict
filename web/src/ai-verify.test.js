import assert from "node:assert/strict";
import { test } from "node:test";

import { chartRows, measuredHours, modelsByMae, okresyByName, pickModel, startOkres } from "./ai-verify.js";

const names = { a: "Alpha", b: "Beta", c: "Gamma" };

test("public models sorted by their MAE, only those with data and a name", () => {
  const series = { models: { a: [1], b: [2], c: [3], blend: [4] }, mae: { ai: 0.5, a: 1.4, b: 0.9, blend: 0.1 } };
  assert.deepEqual(modelsByMae(series, names).map((m) => m.id), ["b", "a", "c"]);
  assert.equal(modelsByMae(series, names)[2].mae, null);
  assert.deepEqual(modelsByMae(undefined, names), []);
});

test("the preselected model if it has data here, else the best", () => {
  const ranked = [{ id: "b" }, { id: "a" }];
  assert.equal(pickModel(ranked, "a"), "a");
  assert.equal(pickModel(ranked, "c"), "b");
  assert.equal(pickModel([], "a"), null);
});

test("rows with the differences from the measurement", () => {
  const times = ["2026-10-19T06:00Z", "2026-10-19T07:00Z"];
  const series = { measured: [10, null], ai: [11, 12], models: { a: [9.5, null] } };
  const rows = chartRows(times, series, "a");
  assert.equal(rows[0].dAi, 1);
  assert.equal(rows[0].dModel, -0.5);
  assert.equal(rows[1].dAi, null);
  assert.equal(rows[1].model, null);
  assert.equal(chartRows(times, undefined, "a")[1].ai, null);
});

test("measured hours", () => {
  assert.equal(measuredHours({ measured_hours: 0, measured: [1] }), 0);
  assert.equal(measuredHours({ measured: [1, null, 2] }), 2);
  assert.equal(measuredHours(undefined), 0);
});

test("models without any MAE yet: alphabetical", () => {
  assert.deepEqual(modelsByMae({ models: { c: [], a: [], b: [] }, mae: {} }, names).map((m) => m.id), ["a", "b", "c"]);
});

test("okresy by name and the one to start with", () => {
  const okresy = { CZ0100: "Praha", CZ0201: "Benešov", CZ0642: "Brno-město" };
  assert.deepEqual(okresyByName(okresy).map(([code]) => code), ["CZ0201", "CZ0642", "CZ0100"]);
  // Praha by its short name, in Czech order (Ch after H)
  const real = { CZ0100: "území Hlavního města Prahy", CZ0209: "Praha-východ", CZ0411: "Cheb", CZ0631: "Havlíčkův Brod", CZ0321: "Domažlice" };
  assert.deepEqual(okresyByName(real).map(([, name]) => name), ["Domažlice", "Havlíčkův Brod", "Cheb", "Praha", "Praha-východ"]);
  assert.equal(startOkres(okresy, "CZ0642"), "CZ0642");
  assert.equal(startOkres(okresy, "CZ9999"), "CZ0100");
  assert.equal(startOkres(okresy, null), "CZ0100");
  assert.equal(startOkres({ CZ0201: "Benešov" }, null), "CZ0201");
});
