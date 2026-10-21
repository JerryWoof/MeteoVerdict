import assert from "node:assert/strict";
import { test } from "node:test";

import { cellText, columnDigits, dateRangeText, dateText, intervalText, numText, pickLang, proseText, signedText } from "./ai-format.js";

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
