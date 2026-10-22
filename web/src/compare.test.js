import assert from "node:assert/strict";
import { test } from "node:test";

import { readFileSync } from "node:fs";

import {
  biasByElevation, blendTestLines, blendTestRows, blendTestVariable, blendVerdict, blendVerdicts, fmt, singleModelVerdicts,
  okresVerdictCounts, intervalRows, isAladin, leadHourBasis, leadHourLines, leadHourRanking, leadHourRunHours,
  leadHourVariable, levelOf, maeByLead, rankingTable, regionList, regionSummary, unpublishedHours,
  RANK_BY, STATION_SETS, hasValues, sortByEts, dayTick, numberTick, tipText, compareHash, compareIsStep, compareViewFromHash,
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

test("a model with too short a record comes last, unranked and out of the charts", () => {
  const withShort = [
    ...CZ.map((r) => ({ ...r, short_record: false, coverage: 1 })),
    { region: "cz", lead_day: 1, model: "new", stations: 450, days: 10, mae: 0.9, bias: 0, rmse: 1.1, rank: null, short_record: true, coverage: 0.25 },
  ];
  const table = rankingTable(withShort, 1);
  assert.deepEqual(table.map((r) => r.model), ["icon", "ifs", "blend", "new"]);
  assert.equal(table.at(-1).short, true);
  assert.equal(table.at(-1).coverage, 0.25);
  assert.equal(table[0].short, false);
  assert.ok(!intervalRows(table).some((r) => r.model === "new"));
  assert.ok(!maeByLead(withShort).some((r) => r.model === "new"));
  // files from before the rule have no short_record: nothing changes
  assert.deepEqual(rankingTable(CZ, 1).map((r) => r.short), [false, false, false]);
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
  assert.equal(fmt(-0.5, true), "−0.50");
  assert.equal(fmt(null), "–");
  assert.equal(fmt(1.234, false, "cs"), "1,23");
  assert.equal(fmt(1234.5, true, "cs"), "+1234,50");
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
    runs: 18, models: 2, stations: null, first: "2026-10-09 02 CEST", last: "2026-10-13 08 CEST", days: 4.3,
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

// --- does our forecast beat the best model? -----------------------------------------
const BLEND_TEST = {
  test_days: 24,
  units: { temperature_2m: "°C" },
  groups: {
    columns: ["level", "region", "region_name", "variable", "lead_day", "days", "best_oos", "mae_combined",
      "mae_best_oos", "mae_best_hindsight", "mae_blend", "diff_combined", "low_combined", "high_combined"],
    rows: [
      ["cz", "cz", "Česko", "wind_speed_10m", 1, 24, "icon", 1.02, 0.99, 0.98, 1.2, 0.03, 0.001, 0.06],
      ["cz", "cz", "Česko", "temperature_2m", 2, 23, "icon", 1.33, 1.38, 1.33, 1.36, -0.05, -0.09, -0.01],
      ["cz", "cz", "Česko", "temperature_2m", 1, 24, "icon", 1.22, 1.24, null, 1.25, -0.02, -0.06, 0.02],
      ["okres", "CZ0201", "Benešov", "temperature_2m", 1, 20, "ifs", 1.1, 1.3, 1.1, 1.2, -0.2, -0.3, -0.1],
      ["okres", "CZ0202", "Beroun", "temperature_2m", 1, 20, "ifs", 1.4, 1.3, 1.2, 1.2, 0.1, 0.05, 0.2],
    ],
  },
};

test("blend test: page variables map to the tested ones", () => {
  assert.equal(blendTestVariable("temperature_2m_06utc"), "temperature_2m");
  assert.equal(blendTestVariable("temperature_max"), "temperature_2m");
  assert.equal(blendTestVariable("precipitation_24h"), "precipitation_daily");
  assert.equal(blendTestVariable("wind_speed_10m_hourly"), "wind_speed_10m");
});

test("blend test verdicts: better, same, worse with intervals in the verdict's direction", () => {
  assert.deepEqual(blendVerdict({ diff_combined: -0.05, low_combined: -0.09, high_combined: -0.01 }),
    { verdict: "better", amount: 0.05, low: 0.01, high: 0.09 });
  assert.equal(blendVerdict({ diff_combined: -0.02, low_combined: -0.06, high_combined: 0.02 }).verdict, "same");
  assert.equal(blendVerdict({ diff_combined: 0.03, low_combined: 0.001, high_combined: 0.06 }).verdict, "worse");
  assert.equal(blendVerdict({ diff_combined: null }), null);
  assert.equal(blendVerdict(undefined), null);
  const v = blendVerdicts(blendTestRows(BLEND_TEST, "cz"));
  assert.deepEqual(v.map((r) => [r.variable, r.lead_day, r.verdict]), [
    ["temperature_2m", 1, "same"], ["temperature_2m", 2, "better"], ["wind_speed_10m", 1, "worse"],
  ]);
  assert.deepEqual(blendVerdicts(blendTestRows(null)), []);
});

test("blend test: verdicts against one model for all of Czechia", () => {
  const doc = {
    groups: {
      columns: ["level", "region", "variable", "lead_day", "days", "best_oos", "best_cz_oos", "diff_combined",
        "low_combined", "high_combined", "diff_combined_vs_cz", "low_combined_vs_cz", "high_combined_vs_cz"],
      rows: [["cz", "cz", "temperature_2m", 1, 26, "icon", "aifs", -0.01, -0.03, 0.01, -0.2, -0.25, -0.15]],
    },
  };
  const rows = blendTestRows(doc, "cz");
  assert.deepEqual(blendVerdicts(rows).map((v) => [v.verdict, v.best]), [["same", "icon"]]);
  const [cz] = blendVerdicts(rows, "cz");
  assert.equal(cz.verdict, "better");
  assert.equal(cz.best, "aifs");
  assert.ok(Math.abs(cz.amount - 0.2) < 1e-9 && cz.low === 0.15 && cz.high === 0.25);
  // a file from before best_cz_oos: no such verdicts
  assert.deepEqual(blendVerdicts(blendTestRows(BLEND_TEST, "cz"), "cz"), []);
});

test("blend test: every single model, ALADIN CZ first, then by MAE", () => {
  const columns = ["variable", "lead_day", "model", "mae", "diff", "low", "high", "days", "mae_combined",
    "diff_combined", "low_combined", "high_combined"];
  const doc = {
    single_models: {
      columns,
      rows: [
        ["temperature_2m", 1, "ecmwf_ifs", 1.2, 0.0, null, null, 26, 1.0, -0.2, -0.25, -0.15],
        ["temperature_2m", 2, "ecmwf_ifs", 1.4, 0.0, null, null, 24, 1.2, 0.1, 0.05, 0.15],
        ["temperature_2m", 1, "chmi_aladin_cz_1km", 1.3, 0.1, 0.03, 0.15, 26, 1.0, -0.3, -0.35, -0.2],
        ["temperature_2m", 1, "dwd_icon", 1.1, 0.0, null, null, 8, 1.0, -0.01, -0.05, 0.03],
        ["wind_speed_10m", 1, "dwd_icon", 1.1, 0.0, null, null, 8, 1.0, -0.01, -0.05, 0.03],
      ],
    },
  };
  const out = singleModelVerdicts(doc, "temperature_2m");
  assert.deepEqual(out.map((m) => m.model), ["chmi_aladin_cz_1km", "dwd_icon", "ecmwf_ifs"]);
  const aladin = out[0].cells[1];
  assert.equal(aladin.verdict, "better");
  assert.ok(Math.abs(aladin.pct + 0.3 / 1.3) < 1e-9);
  assert.equal(out[1].cells[1].verdict, "same");
  assert.equal(out[2].cells[2].verdict, "worse");
  assert.equal(out[0].cells[2], undefined);
  // files from before the intervals: nothing to show
  assert.deepEqual(singleModelVerdicts({ single_models: { columns: columns.slice(0, 7), rows: [] } }, "temperature_2m"), []);
  assert.deepEqual(singleModelVerdicts(null, "temperature_2m"), []);
});

test("blend test chart lines and okres counts", () => {
  const lines = blendTestLines(blendTestRows(BLEND_TEST, "cz"), "temperature_2m");
  assert.deepEqual(lines.filter((r) => r.series === "combined").map((r) => [r.lead_day, r.mae]), [[1, 1.22], [2, 1.33]]);
  assert.equal(lines.filter((r) => r.series === "best_hindsight").length, 1); // null left out
  assert.deepEqual(okresVerdictCounts(BLEND_TEST, "temperature_2m", 1), { better: 1, same: 0, worse: 1 });
  assert.deepEqual(okresVerdictCounts(null, "temperature_2m", 1), { better: 0, same: 0, worse: 0 });
});

const RAIN = records({
  columns: ["region", "lead_day", "model", "mae", "rank", "ets_0p1", "ets_1", "pod_1", "far_1", "ets_10", "mae_bc", "short_record"],
  rows: [
    ["cz", 1, "smooth", 1.0, 1, 0.3, 0.20, 0.9, 0.5, 0.05, null, false],
    ["cz", 1, "sharp", 1.2, 2, 0.4, 0.35, 0.7, 0.3, 0.12, null, false],
    ["cz", 1, "none", 1.1, 3, null, null, null, null, null, null, false],
    ["cz", 1, "blend", 0.9, null, 0.3, 0.30, 0.8, 0.4, 0.01, null, false],
    ["cz", 1, "new", 0.8, null, 0.5, 0.50, 0.9, 0.1, 0.20, null, true],
    ["main", 1, "smooth", 0.9, 1, null, null, null, null, null, 0.7, false],
  ],
});

test("the new event scores and the bias-corrected MAE reach the table", () => {
  const table = rankingTable(RAIN, 1);
  const smooth = table.find((r) => r.model === "smooth");
  assert.equal(smooth.ets1, 0.2);
  assert.equal(smooth.pod1, 0.9);
  assert.equal(smooth.ets10, 0.05);
  assert.equal(smooth.maeBc, null);
  assert.equal(hasValues(table, "ets1"), true);
  assert.equal(hasValues(table, "maeBc"), false);
  // the station kinds are regions of the network level
  assert.equal(rankingTable(RAIN, 1, "main")[0].maeBc, 0.7);
  assert.deepEqual(STATION_SETS, ["all", "main", "other"]);
  assert.deepEqual(RANK_BY, ["mae", "ets1", "ets10"]);
});

test("sorting by ETS: higher first, numbered; no score, the mean and short records last", () => {
  const sorted = sortByEts(rankingTable(RAIN, 1), "ets1");
  assert.deepEqual(sorted.map((r) => r.model), ["sharp", "smooth", "none", "blend", "new"]);
  assert.deepEqual(sorted.map((r) => r.etsRank), [1, 2, null, null, null]);
  // the MAE ranking keeps its own order and ranks
  assert.deepEqual(sorted.map((r) => r.rank), [2, 1, 3, null, null]);
  assert.deepEqual(sortByEts(rankingTable(RAIN, 1), "ets10").slice(0, 2).map((r) => r.model), ["sharp", "smooth"]);
});

test("lead bands and lead days: parsing, labels, variables", async () => {
  const { bandVariable, dayVariable, defaultLead, isBand, krajOf, leadLabel, parseLead } = await import("./compare.js");
  assert.equal(parseLead("h13-24"), "h13-24");
  assert.equal(parseLead("2"), 2);
  assert.equal(parseLead("h1-5"), null);
  assert.equal(parseLead("7"), null);
  assert.equal(parseLead(undefined), null);
  assert.equal(leadLabel("h49-72"), "H+49–72");
  assert.equal(leadLabel(3), "D+3");
  assert.ok(isBand("h1-6") && !isBand(1));
  assert.equal(bandVariable("temperature_2m_06utc"), "temperature_2m");
  assert.equal(bandVariable("wind_speed_10m_hourly"), "wind_speed_10m");
  assert.equal(bandVariable("precipitation_24h"), "precipitation");
  assert.equal(bandVariable("wind_gusts_10m"), "wind_gusts_10m");
  const days = ["temperature_2m", "wind_speed_10m", "precipitation_daily"];
  assert.equal(dayVariable("precipitation", days), "precipitation_daily");
  assert.equal(dayVariable("wind_gusts_10m", days), "wind_speed_10m");
  assert.equal(dayVariable("wind_speed_10m", days), "wind_speed_10m");
  assert.equal(krajOf("CZ0642"), "CZ064");
  assert.equal(krajOf("CZ020A"), "CZ020");
  assert.equal(krajOf("CZ064"), "CZ064");
  assert.equal(defaultLead({ default_band: "h13-24" }), "h13-24");
  assert.equal(defaultLead({ default_band: null }), 1);
  assert.equal(defaultLead(null), 1);
});

test("band files read like D+N score records", async () => {
  const { bandBasis, bandRecords, bandSets, bandsIn, maeByBand } = await import("./compare.js");
  const columns = [
    "level", "region", "band", "set", "variable", "model", "rank", "tied", "clear", "mae", "bias", "rmse", "mae_bc",
    "ets_0p1", "ets_1", "pod_1", "far_1", "diff", "diff_low", "diff_high", "n", "n_bc", "runs", "stations", "days",
  ];
  const doc = {
    columns,
    regions: { cz: "Česko" },
    rows: [
      ["cz", "cz", "h13-24", "hourly", "temperature_2m", "a", 1, false, false, 1.2, 0.3, 1.6, 1.1, null, null, null, null, 0, 0, 0, 100, 90, 340, 98, 20],
      ["cz", "cz", "h13-24", "hourly", "temperature_2m", "b", 2, true, false, 1.25, 0.1, 1.7, 1.0, null, null, null, null, 0.05, -0.01, 0.1, 100, 90, 340, 98, 20],
      ["cz", "cz", "h1-6", "6h", "temperature_2m", "a", 1, false, true, 1.0, 0.3, 1.6, 1.1, null, null, null, null, 0, 0, 0, 100, 90, 340, 98, 20],
    ],
  };
  const rows = bandRecords(doc);
  assert.equal(rows[0].lead_day, "h13-24");
  assert.equal(rows[0].region_name, "Česko");
  assert.equal(rows[1].tied_with_best, true);
  assert.equal(rows[1].diff_ci_high, 0.1);
  const table = rankingTable(rows.filter((r) => r.set === "hourly"), "h13-24");
  assert.deepEqual(table.map((r) => [r.model, r.tied]), [["a", false], ["b", true]]);
  assert.equal(table[0].maeBc, 1.1);
  assert.deepEqual(bandSets(rows, "temperature_2m"), ["hourly", "6h"]);
  assert.deepEqual(bandsIn(rows), ["h1-6", "h13-24"]);
  assert.deepEqual(bandBasis(rows, "h13-24", "cz"), { runs: 340, stations: 98, days: 20, preliminary: true });
  assert.equal(bandBasis(rows, "h13-24", "CZ010"), null);
  assert.deepEqual(maeByBand(rows.filter((r) => r.set === "hourly")).map((r) => [r.model, r.lead_day]), [["a", 3], ["b", 3]]);
});

test("chart text in the page language", () => {
  const tick = numberTick("cs");
  assert.deepEqual([0, 0.5, 1].map((v, i, all) => tick(v, i, all)), ["0,0", "0,5", "1,0"]);
  assert.equal(tick(-2, 0, [-2, 0, 2]), "−2");
  assert.equal(numberTick("en")(1.5, 0, [1, 1.5]), "1.5");
  assert.equal(dayTick("cs")(new Date("2026-09-13T12:00:00Z")), "13. září");
  assert.equal(dayTick("en")(new Date("2026-09-13T12:00:00Z")), "Sep 13");
  assert.equal(tipText("A", null, "", "B"), "A\nB");
});

test("compareViewFromHash / compareHash: the view in the URL, back and forth", () => {
  const view = compareViewFromHash("#wind_speed_10m/3/90d/CZ0642/temperature_2m/main/ets1/6h");
  assert.equal(compareHash(view), "#wind_speed_10m/3/90d/CZ0642/temperature_2m/main/ets1/6h");
  assert.equal(view.leadGiven, true);
  // the last three only when not the defaults; an old link gets the blend test at its variable
  assert.equal(compareHash(compareViewFromHash("#precipitation_24h/2/all")), "#precipitation_24h/2/all/cz/precipitation_daily");
  // a band of hours with a band-only variable
  const band = compareViewFromHash("#wind_gusts_10m/h13-24/all/cz");
  assert.equal(band.variable, "wind_gusts_10m");
  assert.equal(band.leadDay, "h13-24");
  // garbage: the defaults, no lead given (the page picks the data's default lead)
  const bogus = compareViewFromHash("#bogus");
  assert.equal(bogus.leadGiven, false);
  assert.equal(bogus.region, "cz");
  assert.equal(compareHash(bogus), compareHash(compareViewFromHash("")));
  assert.equal(compareViewFromHash("#temperature_2m/1/90d/cz/x/y/z/w").stations, "all");
});

test("compareIsStep: a new variable or region is a history step, the rest is not", () => {
  const a = compareViewFromHash("#temperature_2m/1/90d/cz");
  assert.equal(compareIsStep(null, a), false);
  assert.equal(compareIsStep(a, { ...a, leadDay: 2, window: "all", stations: "main" }), false);
  assert.equal(compareIsStep(a, { ...a, region: "CZ0642" }), true);
  assert.equal(compareIsStep(a, { ...a, variable: "wind_speed_10m" }), true);
});
