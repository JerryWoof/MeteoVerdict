import assert from "node:assert/strict";
import { test } from "node:test";

import { AI_FILES, aiPath, aiText } from "./ai-source.js";
import { experimentsWith, improvement, improvementText } from "./ai-extras.js";

test("the AI tab reads its own outlook and obce files, everything else is shared", () => {
  assert.equal(aiPath("data/scores/outlook.json"), "data/scores/ai/fc/outlook.json");
  assert.equal(aiPath("data/scores/forecast/obce-CZ0423.json"), "data/scores/ai/fc/forecast/obce-CZ0423.json");
  for (const path of ["data/scores/meta.json", "data/scores/forecast/CZ0423.json", "data/scores/forecast/models/CZ0423.json",
    "data/scores/forecast/models-parts/icon_d2.json", "data/okresy.geojson"]) {
    assert.equal(AI_FILES.test(path), false, path);
    assert.equal(aiPath(path), path);
  }
});

test("MeteoVerdict AI named where our combination is", () => {
  const t = aiText((key, params) => `${key}${params ? JSON.stringify(params) : ""}`);
  assert.equal(t("forecast.pickCombined"), "ai.pickCombined");
  assert.equal(t("tv.bannerFailed", { model: "x" }), 'ai.bannerFailed{"model":"x"}');
  assert.equal(t("tv.detail"), "tv.detail");
});

test("improvement over the best public model", () => {
  assert.equal(Math.round(improvement({ mae_ai: 0.9, mae_best: 1.2 })), 25);
  assert.equal(improvement({ mae_ai: null, mae_best: 1.2 }), null);
  assert.equal(improvementText(25.4), "+25 %");
  assert.equal(improvementText(-3.2), "−3 %");
  assert.equal(improvementText(null), "–");
});

test("experiments by status, without columns about our combination", () => {
  const all = [
    { id: "a", status: "works", table: { columns: [{ key: "lead" }, { key: "combined" }, { key: "diff", en: "Diff vs combined" }, { key: "mae" }], rows: [[1, 2, 3, 4], { lead: 2, mae: 5 }] } },
    { id: "b", status: "testing" },
    { id: "c", status: "works" },
  ];
  assert.deepEqual(experimentsWith(all, "testing").map((e) => e.id), ["b"]);
  const shown = experimentsWith(all, "works");
  assert.deepEqual(shown.map((e) => e.id), ["a", "c"]);
  assert.deepEqual(shown[0].table.columns.map((c) => c.key), ["lead", "mae"]);
  assert.deepEqual(shown[0].table.rows, [[1, 4], { lead: 2, mae: 5 }]);
});
