import assert from "node:assert/strict";
import { test } from "node:test";

import { firstOfLastDays, modelsByMae, okresyByName, pickModel, startOkres } from "./ai-verify.js";

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

test("the last days of the times", () => {
  const times = ["2026-10-01T00:00Z", "2026-10-01T12:00Z", "2026-10-02T00:00Z", "2026-10-02T12:00Z", "2026-10-03T00:00Z"];
  assert.equal(firstOfLastDays(times, 1), 3);
  assert.equal(firstOfLastDays(times, 14), 0);
  assert.equal(firstOfLastDays(times, 0), 0);
});

test("okresy by name and the one to start with", () => {
  const okresy = { CZ0100: "Praha", CZ0201: "Benešov", CZ0642: "Brno-město" };
  assert.deepEqual(okresyByName(okresy).map(([code]) => code), ["CZ0201", "CZ0642", "CZ0100"]);
  assert.equal(startOkres(okresy, "CZ0642"), "CZ0642");
  assert.equal(startOkres(okresy, "CZ9999"), "CZ0100");
  assert.equal(startOkres(okresy, null), "CZ0100");
  assert.equal(startOkres({ CZ0201: "Benešov" }, null), "CZ0201");
});
