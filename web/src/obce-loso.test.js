import assert from "node:assert/strict";
import { test } from "node:test";

import { translator } from "./i18n.js";
import { diffText, losoBlocks, losoSummary, significant } from "./obce-loso.js";
import { PAGES } from "./pages-text.js";

const COLUMNS = [
  "variant", "variable", "lead_day", "stratum", "value", "days", "stations", "n",
  "mae_obec", "mae_obec_point", "mae_okres", "mae_nearest", "mae_median",
  "diff_okres", "low_okres", "high_okres", "diff_median", "low_median", "high_median",
  "diff_obec_point", "low_obec_point", "high_obec_point",
];
const row = (variant, variable, lead, stratum, value, stations, mae, okres, median, point) => [
  variant, variable, lead, stratum, value, 41, stations, 1000, mae, null, null, null, null, ...okres, ...median, ...point,
];
// shaped like obce-loso.json, a few rows
const DOC = {
  from: "2026-09-08",
  to: "2026-10-18",
  test_days: 41,
  units: { temperature_2m: "°C", wind_speed_10m: "m/s", precipitation_daily: "mm" },
  names: { a: "A", b: "B", c: "C" },
  groups: {
    columns: COLUMNS,
    rows: [
      row("loso", "temperature_2m", "all", "all", "all", 291, 1.56, [-0.316, -0.4, -0.23], [-0.061, -0.11, 0.004], [-0.025, -0.031, -0.019]),
      row("loso", "temperature_2m", "1", "all", "all", 291, 1.256, [-0.49, -0.55, -0.42], [-0.11, -0.18, -0.04], [-0.018, -0.023, -0.013]),
      row("loso", "temperature_2m", "all", "elevation_class", "mountain", 48, 1.79, [-0.58, -0.9, -0.3], [0.086, 0.02, 0.15], [-0.11, -0.14, -0.08]),
      row("loso", "wind_speed_10m", "all", "all", "all", 208, 1.057, [-0.06, -0.07, -0.05], [-0.131, -0.16, -0.1], [-0.013, -0.017, -0.008]),
      row("loso", "wind_speed_10m", "all", "elevation_class", "mountain", 16, 2.26, [-0.12, -0.15, -0.09], [0.1, -0.01, 0.2], [-0.076, -0.12, -0.03]),
      // the stricter variant is not shown
      row("buffer", "temperature_2m", "all", "all", "all", 293, 1.6, [-0.5, -0.6, -0.4], [-0.02, -0.07, 0.04], [-0.02, -0.03, -0.01]),
    ],
  },
};

test("the key numbers of the station-held-out variant", () => {
  const s = losoSummary(DOC);
  assert.equal(s.stations, 3);
  assert.equal(s.days, 41);
  assert.deepEqual(s.variables.map((v) => v.variable), ["temperature_2m", "wind_speed_10m"]);
  const temperature = s.variables[0];
  assert.equal(temperature.mae, 1.56);
  assert.equal(temperature.maeD1, 1.256);
  assert.equal(temperature.stations, 291);
  assert.deepEqual(temperature.okres, { diff: -0.316, low: -0.4, high: -0.23 });
  assert.deepEqual(temperature.mountain, { stations: 48, median: { diff: 0.086, low: 0.02, high: 0.15 } });
  assert.equal(losoSummary(null), null);
  assert.equal(losoSummary({ groups: { columns: COLUMNS, rows: [] } }), null);
});

test("an older file without obec_point: no before/after line", () => {
  const columns = COLUMNS.filter((c) => !c.includes("obec_point"));
  const rows = DOC.groups.rows.map((r) => r.filter((_, i) => !COLUMNS[i].includes("obec_point")));
  const s = losoSummary({ ...DOC, groups: { columns, rows } });
  assert.equal(s.variables[0].point, null);
  const blocks = losoBlocks(s, "en", translator("en"));
  assert.ok(!blocks.some(([, text]) => typeof text === "string" && text.includes("Since 20 October")));
});

test("differences: sign, decimal comma, interval, bold only where it excludes zero", () => {
  const cs = translator("cs");
  assert.equal(diffText({ diff: -0.316, low: -0.4, high: -0.23 }, "cs", cs), "**−0,32 (−0,40 až −0,23)**");
  assert.equal(diffText({ diff: -0.061, low: -0.11, high: 0.004 }, "en", translator("en")), "−0.06 (−0.11 to +0.00)");
  assert.equal(diffText(null, "en", translator("en")), "–");
  assert.ok(significant({ diff: 0.1, low: 0.02, high: 0.15 }));
  assert.ok(!significant({ diff: 0.1, low: -0.01, high: 0.2 }));
});

test("the section: intro, table, the mountain caveat where it is significant, limits", () => {
  for (const language of ["cs", "en"]) {
    const t = translator(language);
    const blocks = losoBlocks(losoSummary(DOC), language, t);
    assert.deepEqual(blocks.map(([kind]) => kind), ["h", "p", "table", "p", "p", "p", "note"]);
    assert.equal(blocks[0][1], t("obceLoso.title"));
    assert.match(blocks[1][1], /41/);
    const table = blocks[2][1];
    assert.equal(table.head.length, 5);
    assert.equal(table.rows.length, 2);
    assert.equal(table.rows[0][1], language === "cs" ? "1,56 °C" : "1.56 °C");
    // only temperature is significantly worse than the median in the mountains
    const caveat = blocks[4][1];
    assert.match(caveat, language === "cs" ? /teplota \+0,09 °C \(48 stanic\)/ : /temperature \+0\.09 °C \(48 stations\)/);
    assert.doesNotMatch(caveat, /m\/s/);
    assert.match(blocks[5][1], /0[.,]025/);
  }
});

test("without the file: the heading and a note", () => {
  const blocks = losoBlocks(null, "cs", translator("cs"));
  assert.deepEqual(blocks.map(([kind]) => kind), ["h", "note"]);
});

test("the methodology page has the section in both languages", () => {
  for (const language of ["cs", "en"]) {
    const blocks = PAGES.methodology[language].blocks;
    assert.ok(blocks.some(([kind, id]) => kind === "slot" && id === "obce-loso"));
    assert.ok(blocks.some(([, text]) => typeof text === "string" && text.includes("(#obce-loso)")));
  }
});
