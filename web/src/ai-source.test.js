import assert from "node:assert/strict";
import { test } from "node:test";

import { AI_FILES, aiPath, aiText } from "./ai-source.js";

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
