import assert from "node:assert/strict";
import { test } from "node:test";

import { AI_FILES, aiPath, aiText } from "./ai-source.js";
import { blendDiffText, blendVerdict, experimentsWith, improvement, improvementText, SECTIONS } from "./ai-extras.js";

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

test("experiments by status, tables with our blend kept", () => {
  const all = [
    { id: "a", status: "works", table: { columns: [{ key: "lead" }, { key: "blend" }, { key: "diff", en: "Diff vs combined" }, { key: "mae" }], rows: [[1, 2, 3, 4]] } },
    { id: "b", status: "testing" },
    { id: "c", status: "works" },
    { id: "meteoverdict_ai", status: "unverified" },
  ];
  assert.deepEqual(experimentsWith(all, "testing").map((e) => e.id), ["b"]);
  const shown = experimentsWith(all, "works");
  assert.deepEqual(shown.map((e) => e.id), ["a", "c"]);
  assert.deepEqual(shown[0].table.columns.map((c) => c.key), ["lead", "blend", "diff", "mae"]);
  // a model that is not verified yet keeps its card in a section of its own
  assert.deepEqual(experimentsWith(all, "unverified").map((e) => e.id), ["meteoverdict_ai"]);
  assert.deepEqual(SECTIONS.map(([s]) => s), ["works", "unverified", "testing"]);
});

test("AI minus our blend with its interval", () => {
  const row = { diff_blend: -0.11, low_blend: -0.15, high_blend: -0.07 };
  assert.equal(blendDiffText(row, "en"), "−0.11 [−0.15, −0.07]");
  assert.equal(blendDiffText(row, "cs"), "−0,11 [−0,15; −0,07]");
  assert.equal(blendDiffText({ diff_blend: 0.02 }, "en"), "+0.02");
  assert.equal(blendDiffText({}, "en"), "–");
  assert.equal(blendVerdict(row), "better");
  assert.equal(blendVerdict({ diff_blend: -0.05, low_blend: -0.1, high_blend: 0.01 }), "tie");
  assert.equal(blendVerdict({ diff_blend: 0.1, low_blend: 0.02, high_blend: 0.2 }), "worse");
});
