import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cellText,
  columnDigits,
  dateRangeText,
  dateText,
  experimentTexts,
  intervalText,
  numText,
  pickLang,
  proseText,
  ruleText,
  signedText,
  tableTexts,
} from "./ai-format.js";

// Intl puts a no-break space into Czech numbers and ranges; compare with plain spaces
const plain = (s) => s.replace(/[  ]/g, " ");

test("numbers: fixed decimals, real minus, no negative zero", () => {
  assert.equal(numText(1.195, 2, "cs"), "1,20");
  assert.equal(numText(2, 2, "cs"), "2,00");
  assert.equal(numText(-0.45, 2, "en"), "−0.45");
  assert.equal(numText(-0.002, 2, "cs"), "0,00");
  assert.equal(numText(-0, 2, "en"), "0.00");
  assert.equal(plain(numText(13212, 0, "cs")), "13 212");
  assert.equal(numText(null), "–");
  assert.equal(numText(Number.NaN), "–");
  assert.equal(signedText(0.004, 2, "en"), "0.00");
  assert.equal(signedText(0.01, 2, "cs"), "+0,01");
});

test("dates as in the site's sentences, without a period that would double", () => {
  assert.equal(dateText("2026-10-19", "cs"), "19. října");
  assert.equal(dateText("2026-10-19", "en"), "19 October");
  assert.equal(plain(dateRangeText("2026-10-19", "2026-10-21", "cs")), "19.–21. října");
  assert.equal(plain(dateRangeText("2026-08-24", "2026-10-17", "en")), "24 August – 17 October");
  assert.equal(dateRangeText("2026-10-19", "2026-10-19", "en"), "19 October");
});

test("one language of a 'cs / en' label", () => {
  assert.equal(pickLang("Teplota / Temperature", "cs"), "Teplota");
  assert.equal(pickLang("inverze, bezvětří / inversion, calm", "en"), "inversion, calm");
  assert.equal(pickLang("NOAA GFS 0.11°/0.25°", "cs"), "NOAA GFS 0.11°/0.25°");
  assert.equal(pickLang("a / b / c", "cs"), "a / b / c");
});

test("the engine's interval text", () => {
  assert.equal(intervalText("-0.07 [-0.10, -0.03]", "cs"), "−0,07 [−0,10; −0,03]");
  assert.equal(intervalText("-0.08 [-0.18, +0.01]", "en"), "−0.08 [−0.18, +0.01]");
  assert.equal(intervalText("D+1", "en"), null);
});

test("table cells", () => {
  const translate = (v) => ({ point: "v bodě stanice" })[v] ?? null;
  assert.equal(cellText("point", { language: "cs", translate }), "v bodě stanice");
  assert.equal(cellText(2, { digits: 2, language: "cs" }), "2,00");
  assert.equal(cellText(1160, { digits: 0, language: "en" }), "1,160");
  assert.equal(cellText("DWD ICON-D2 1.195", { language: "cs" }), "DWD ICON-D2 1,20");
  assert.equal(cellText("ECMWF AIFS 0.25° 1.455", { language: "cs" }), "ECMWF AIFS 0.25° 1,46");
  assert.equal(
    cellText("ČHMÚ ALADIN Central Europe 2.3 km 1.06 °C (worst 1.63, Météo-France ARPEGE World)", { language: "cs", worst: "nejhorší" }),
    "ČHMÚ ALADIN Central Europe 2.3 km 1,06 °C (nejhorší 1,63, Météo-France ARPEGE World)",
  );
  assert.equal(cellText("Vítr / Wind", { language: "en" }), "Wind");
  assert.equal(cellText("00 UTC", { language: "cs" }), "00 UTC");
  assert.equal(cellText("D+1", { language: "cs" }), "D+1");
  assert.equal(cellText(null), "–");
});

test("decimals per column", () => {
  assert.equal(columnDigits([13212, 13495]), 0);
  assert.equal(columnDigits([1.6, 2, 1.75]), 2);
  assert.equal(columnDigits(["a", null]), 2);
});

test("backend sentences: dates, minus, Czech decimals, model names kept", () => {
  assert.equal(
    plain(proseText("teplota z terénu 1.38 °C MAE (-0.50 °C, 95 % interval -0.70 až -0.33); 1.24 proti 1.69 °C (-0.45 [-0.64, -0.29]). 2026-08-24…2026-10-17, 292 stanic.", "cs")),
    "teplota z terénu 1,38 °C MAE (−0,50 °C, 95 % interval −0,70 až −0,33); 1,24 proti 1,69 °C (−0,45 [−0,64; −0,29]). 24. srpna – 17. října, 292 stanic.",
  );
  assert.equal(proseText("1,20 °C (ECMWF AIFS 0.25°), ALADIN 2.3 km", "cs"), "1,20 °C (ECMWF AIFS 0.25°), ALADIN 2.3 km");
  assert.equal(plain(proseText("2026-09-07 až 2026-10-17 (32 dní)", "cs")), "7. září – 17. října (32 dní)");
  assert.equal(proseText("(3-5 day block bootstrap), ICON-D2, D+1", "en"), "(3–5 day block bootstrap), ICON-D2, D+1");
  assert.equal(proseText("at 12 UTC 0.92 vs 0.98 °C (-0.06 [-0.09, -0.01])", "en"), "at 12 UTC 0.92 vs 0.98 °C (−0.06 [−0.09, −0.01])");
});

// an experiment as an older ai.json has it (before the engine wrote `texts`)
const OLD = {
  id: "regimes",
  tech: "Weather regimes, own hardware",
  headline: { cs: "Medián 1.38 °C (-0.50), 2026-08-24…2026-10-17.", en: "Median 1.38 °C (-0.50), 2026-08-24…2026-10-17." },
  table: {
    columns: [
      { key: "regime", cs: "Situace", en: "Regime" },
      { key: "variable_cs", cs: "Veličina", en: "Variable" },
      { key: "days", cs: "Dní", en: "Days" },
      { key: "temp", cs: "Nejlepší na teplotu", en: "Best for temperature" },
      { key: "diff", cs: "AI - blend", en: "AI - blend" },
    ],
    rows: [
      { regime: "proměnlivo / changeable", regime_cs: "proměnlivo", regime_en: "changeable", variable: "temperature_2m", variable_cs: "teplota", days: 22, temp: "DWD ICON-D2 1.06 °C (worst 1.63, CMA GRAPES Global)", diff: -0.004 },
      { regime: "inverze / inversion", variable: "temperature_2m", days: 13, temp: "-", diff: 2 },
    ],
  },
};
// the same card as the engine now writes it: finished texts per language next to the old fields
const NEW = {
  ...OLD,
  texts: {
    cs: {
      headline: "Medián 1,38 °C (−0,50), 24. srpna – 17. října.",
      tech: "povětrnostní situace, own hardware",
      table: { columns: ["Situace", "Dní"], rows: [["proměnlivo", "22"]], numeric: [false, true] },
    },
    en: { headline: "Median 1.38 °C (−0.50), 24 August – 17 October." },
  },
};
const translate = (v) => ({ temperature_2m: "Teplota" })[v] ?? null;

test("an experiment's texts: the engine's finished ones first", () => {
  const cs = experimentTexts(NEW, { language: "cs", translate });
  assert.equal(cs.headline, "Medián 1,38 °C (−0,50), 24. srpna – 17. října.");
  assert.equal(cs.tech, "povětrnostní situace, own hardware");
  assert.deepEqual(cs.table, { columns: ["Situace", "Dní"], rows: [["proměnlivo", "22"]], numeric: [false, true] });
  // English has only a headline: the table is formatted from the old fields, no tech of its own
  const en = experimentTexts(NEW, { language: "en" });
  assert.equal(en.headline, "Median 1.38 °C (−0.50), 24 August – 17 October.");
  assert.equal(en.tech, null);
  assert.equal(en.table.rows[0][0], "changeable");
});

test("an experiment's texts from an older ai.json, formatted here", () => {
  const cs = experimentTexts(OLD, { language: "cs", translate, worst: "nejhorší" });
  assert.equal(plain(cs.headline), "Medián 1,38 °C (−0,50), 24. srpna – 17. října.");
  assert.equal(cs.tech, null);
  assert.deepEqual(cs.table.columns, ["Situace", "Veličina", "Dní", "Nejlepší na teplotu", "AI − blend"]);
  assert.deepEqual(cs.table.rows[0], ["proměnlivo", "Teplota", "22", "DWD ICON-D2 1,06 °C (nejhorší 1,63, CMA GRAPES Global)", "0,00"]);
  // a regime without its twins: the Czech half of the pair; a whole 2 among decimals as "2,00"
  assert.deepEqual(cs.table.rows[1], ["inverze", "Teplota", "13", "-", "2,00"]);
  assert.deepEqual(cs.table.numeric, [false, false, true, false, true]);
  assert.equal(experimentTexts(OLD, { language: "en" }).table.rows[0][1], "teplota");
  assert.equal(experimentTexts({ id: "x" }, { language: "cs" }).table, null);
});

test("a malformed finished table falls back to the old one", () => {
  const broken = { ...OLD, texts: { cs: { table: { columns: ["A"], rows: [["1", "2"]] } } } };
  assert.equal(experimentTexts(broken, { language: "cs", translate }).table.columns[0], "Situace");
  assert.equal(tableTexts({ columns: [], rows: [] }), null);
});

test("the rule: the engine's text first, else the old one formatted", () => {
  const rule = { cs: "blokový bootstrap 3 až 5 dní", en: "(3-5 day block bootstrap)" };
  assert.equal(ruleText({ rule, texts: { en: { rule: "(3–5 day block bootstrap)" } } }, "en"), "(3–5 day block bootstrap)");
  assert.equal(ruleText({ rule }, "en"), "(3–5 day block bootstrap)");
  assert.equal(ruleText({}, "cs"), null);
});
