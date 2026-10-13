import assert from "node:assert/strict";
import { test } from "node:test";

import { readFileSync } from "node:fs";

import {
  biasByElevation, fmt, intervalRows, isAladin, leadHourBasis, leadHourLines, leadHourRanking, leadHourRunHours,
  leadHourVariable, levelOf, maeByLead, rankingTable, regionList, regionSummary, unpublishedHours,
} from "./compare.js";
import { records } from "./data.js";

const CZ = records({
  columns: ["region", "lead_day", "model", "stations", "days", "mae", "bias", "rmse", "rank", "diff_ci_low", "diff_ci_high", "tied_with_best"],
  rows: [
    ["cz", 1, "ifs", 450, 90, 1.3, 0.2, 1.7, 2, 0.02, 0.15, false],
    ["cz", 1, "blend", 450, 90, 1.1, 0.0, 1.4, null, -0.3, -0.1, true],
    ["cz", 1, "icon", 450, 90, 1.2, -0.1, 1.6, 1, 0, 0, false],
    ["cz", 2, "icon", 450, 90, 1.5, -0.1, 1.9, 1, 0, 0, false],
  ],
});

test("ranked models first, the blend last, differences to the best", () => {
  const table = rankingTable(CZ, 1);
  assert.deepEqual(table.map((r) => r.model), ["icon", "ifs", "blend"]);
  assert.equal(table[0].diff, 0);
  assert.ok(Math.abs(table[1].diff - 0.1) < 1e-9);
  assert.ok(table[2].diff < 0);
  assert.deepEqual(table[1].ci, [0.02, 0.15]);
});

test("bias by elevation class, in order, without the blend", () => {
  const rows = records({
    columns: ["region", "lead_day", "model", "bias"],
    rows: [
      ["mountain", 1, "icon", -0.8],
      ["lowland", 1, "icon", 0.1],
      ["lowland", 1, "blend", 0.0],
      ["upland", 2, "icon", 0.3],
    ],
  });
  assert.deepEqual(biasByElevation(rows, 1), [
    { elevation: "lowland", model: "icon", bias: 0.1 },
    { elevation: "mountain", model: "icon", bias: -0.8 },
  ]);
});

test("number format", () => {
  assert.equal(fmt(1.234), "1.23");
  assert.equal(fmt(0.5, true), "+0.50");
  assert.equal(fmt(-0.5, true), "-0.50");
  assert.equal(fmt(null), "–");
});

// real okres scores: 06-06 precipitation, last 90 days, Litoměřice and Benešov
const OKRES = records(JSON.parse(readFileSync(new URL("./fixtures/scores-90d-okres-precipitation_24h.json", import.meta.url))));

test("levels of region codes", () => {
  assert.equal(levelOf("cz"), "cz");
  assert.equal(levelOf("CZ064"), "kraj");
  assert.equal(levelOf("CZ0642"), "okres");
  assert.equal(levelOf("CZ020A"), "okres");
});

test("ranking of one okres, with skill against the mean and event scores", () => {
  const table = rankingTable(OKRES, 1, "CZ0423");
  assert.equal(table[0].rank, 1);
  assert.equal(table.at(-1).model, "blend");
  assert.equal(table.at(-1).skill, null);
  const blend = table.at(-1);
  for (const r of table.slice(0, -1)) {
    assert.ok(Math.abs(r.skill - (1 - r.mae / blend.mae)) < 1e-12);
  }
  assert.ok(table.every((r) => r.ets == null || (r.ets >= -1 / 3 && r.ets <= 1)));
  assert.ok(table.every((r) => r.stations >= 3));
  assert.deepEqual(rankingTable(OKRES, 1, "CZ9999"), []);
});

test("interval rows: the best at zero, ties reach zero", () => {
  const rows = intervalRows(rankingTable(OKRES, 1, "CZ0423"));
  assert.equal(rows[0].diff, 0);
  assert.deepEqual([rows[0].low, rows[0].high], [0, 0]);
  for (const r of rows.slice(1)) assert.equal(r.tied, r.low <= 0 && r.high >= 0);
  assert.ok(!rows.some((r) => r.model === "blend"));
});

test("MAE by lead day and the region summary", () => {
  const lines = maeByLead(OKRES, "CZ0201");
  const leads = [...new Set(lines.map((r) => r.lead_day))].sort();
  assert.deepEqual(leads, [1, 2, 3, 4, 5]);
  const s = regionSummary(OKRES, 1, "CZ0201");
  assert.equal(s.name, "Benešov");
  assert.equal(s.model, rankingTable(OKRES, 1, "CZ0201")[0].model);
  assert.ok(s.days > 0 && s.stations >= 3);
  assert.equal(regionSummary(OKRES, 1, "CZ9999"), null);
  assert.deepEqual(regionList(OKRES).map((r) => r.name), ["Benešov", "Litoměřice"]);
});

const LEADS = {
  first_run: "2026-10-09T00:00Z",
  last_run: "2026-10-13T06:00Z",
  models: {
    cz1: { runs: 18, pairs: 100, publication_delay_h: null },
    lamb: { runs: 17, pairs: 100, publication_delay_h: null },
  },
  columns: ["region", "run_hour", "model", "variable", "lead_h", "runs", "stations", "n", "mae", "bias", "rmse"],
  rows: [
    ["cz", "all", "lamb", "temperature_2m", 2, 15, 290, 4000, 1.1, 0.3, 1.5],
    ["cz", "all", "lamb", "temperature_2m", 1, 14, 290, 4000, 1.0, 0.3, 1.4],
    ["cz", "all", "cz1", "temperature_2m", 1, 14, 290, 4000, 0.9, 0.2, 1.3],
    ["cz", "06", "cz1", "temperature_2m", 1, 4, 290, 1000, 0.8, 0.2, 1.2],
    ["cz", "all", "cz1", "precipitation", 1, 14, 430, 6000, 0.1, 0.0, 0.2],
    ["CZ010", "all", "cz1", "temperature_2m", 1, 14, 5, 70, 0.7, 0.1, 0.9],
  ],
};

test("lead-hour variable for the page variables", () => {
  assert.equal(leadHourVariable("temperature_2m_06utc"), "temperature_2m");
  assert.equal(leadHourVariable("temperature_max"), "temperature_2m");
  assert.equal(leadHourVariable("wind_speed_10m_hourly"), "wind_speed_10m");
  assert.equal(leadHourVariable("precipitation_24h"), "precipitation");
});

test("MAE by lead hour for Czechia, one run hour", () => {
  const lines = leadHourLines(LEADS, "temperature_2m");
  assert.deepEqual(lines.map((r) => [r.model, r.lead_h, r.mae]), [
    ["cz1", 1, 0.9],
    ["lamb", 1, 1.0],
    ["lamb", 2, 1.1],
  ]);
  assert.deepEqual(leadHourLines(LEADS, "temperature_2m", "06").map((r) => r.mae), [0.8]);
  assert.deepEqual(leadHourLines(null, "temperature_2m"), []);
});

test("history behind the lead-hour chart and the unpublished hours", () => {
  assert.deepEqual(leadHourBasis(LEADS), {
    runs: 18, models: 2, stations: null, first: "2026-10-09 00 UTC", last: "2026-10-13 06 UTC", days: 4.3,
  });
  assert.equal(leadHourBasis({}), null);
  assert.equal(unpublishedHours(LEADS), 4);
  const measured = { models: { a: { publication_delay_h: 3.4 }, b: { publication_delay_h: 4.4 } } };
  assert.equal(unpublishedHours(measured), 4.4);
});

// leads.json from the single runs: no region column, every model, H+1 to H+120
const RUNS = {
  first_run: "2026-07-15T00:00Z",
  last_run: "2026-10-13T00:00Z",
  stations: 99,
  region: "cz",
  models: {
    chmi_aladin_cz_1km: { runs: 3, publication_delay_h: 4.4 },
    dwd_icon_d2: { runs: 3, publication_delay_h: null },
    ncep_gfs_global: { runs: 4, publication_delay_h: null },
  },
  columns: ["run_hour", "model", "variable", "lead_h", "runs", "stations", "n", "mae", "bias", "rmse"],
  rows: [
    ["all", "chmi_aladin_cz_1km", "temperature_2m", 1, 3, 99, 290, 1.0, 0.1, 1.2],
    ["all", "dwd_icon_d2", "temperature_2m", 1, 3, 99, 290, 0.8, 0.1, 1.1],
    ["all", "ncep_gfs_global", "temperature_2m", 1, 3, 99, 290, 2.0, 0.1, 2.5],
    ["all", "chmi_aladin_cz_1km", "temperature_2m", 2, 3, 99, 290, 1.1, 0.1, 1.2],
    ["all", "dwd_icon_d2", "temperature_2m", 2, 3, 99, 290, 1.2, 0.1, 1.4],
    ["all", "ncep_gfs_global", "temperature_2m", 2, 3, 99, 290, 1.5, 0.1, 2.0],
    ["all", "ncep_gfs_global", "temperature_2m", 100, 2, 99, 190, 2.5, 0.1, 3.0],
    ["00", "ncep_gfs_global", "temperature_2m", 1, 2, 99, 190, 2.1, 0.1, 2.6],
  ],
};

test("lead-hour lines from the single runs (no region column)", () => {
  const lines = leadHourLines(RUNS, "temperature_2m");
  assert.equal(lines.length, 7);
  assert.deepEqual(lines.filter((r) => r.model === "ncep_gfs_global").map((r) => r.lead_h), [1, 2, 100]);
  assert.deepEqual(leadHourRunHours(RUNS), ["all", "00"]);
  assert.deepEqual(leadHourRunHours(LEADS), ["all", "06"]);
  assert.deepEqual(leadHourRunHours(null), []);
  assert.equal(leadHourBasis(RUNS).stations, 99);
  assert.equal(leadHourBasis(RUNS).models, 3);
  assert.equal(unpublishedHours(RUNS), 4.4);
});

test("best models by their mean rank over the lead hours", () => {
  const ranking = leadHourRanking(leadHourLines(RUNS, "temperature_2m"));
  // H+1: d2 0, aladin 0.5, gfs 1; H+2: aladin 0, d2 0.5, gfs 1; H+100: gfs alone (not ranked)
  assert.deepEqual(ranking.map((r) => [r.model, r.score, r.leads]), [
    ["chmi_aladin_cz_1km", 0.25, 2],
    ["dwd_icon_d2", 0.25, 2],
    ["ncep_gfs_global", 1, 2],
  ]);
  assert.deepEqual(leadHourRanking([]), []);
  assert.ok(isAladin("chmi_aladin_central_europe_2km"));
  assert.ok(!isAladin("dwd_icon_d2"));
});
