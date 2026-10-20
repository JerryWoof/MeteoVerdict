// Write the open data files (src/api.js) into public/api/v1 from the data that
// scripts/copy-data.mjs put into public/data/scores. Without the data (a local build
// before any forecast) it writes nothing and says so.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { SCORE_VARIABLES, VERSION, aiOkresDoc, indexDoc, obceDocs, obceIndexDoc, okresCsv, okresDoc } from "../src/api.js";
import { records } from "../src/data.js";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const data = join(web, "public", "data", "scores");
const out = join(web, "public", "api", VERSION);
const read = (path) => (existsSync(join(data, path)) ? JSON.parse(readFileSync(join(data, path), "utf-8")) : null);

rmSync(join(web, "public", "api"), { recursive: true, force: true });
const outlook = read("outlook.json");
const hourly = read("outlook-hourly.json");
const points = read("forecast/okresy.json");
if (!outlook || !points) {
  console.log("no outlook or okres points in public/data/scores: no open data files");
  process.exit(0);
}
const meta = read("meta.json");
const scores = Object.fromEntries(SCORE_VARIABLES.map((v) => [v, records(read(`90d/okres/${v}.json`))]));
mkdirSync(join(out, "okresy"), { recursive: true });
const okresy = records(points);
// the AI files (published daily with the release ai-latest, served under data/scores/ai)
const aiForecast = read("ai/ai-forecast.json");
const aiOutlook = read("ai/fc/outlook.json");
const withAi = Boolean(aiForecast && aiOutlook);
if (withAi) mkdirSync(join(out, "ai", "okresy"), { recursive: true });
else console.log("no ai/ai-forecast.json or ai/fc/outlook.json in public/data/scores: no AI files");
const obceRows = [];
let obceCount = 0;
let aiCount = 0;
for (const okres of okresy) {
  const doc = okresDoc({ okres, outlook, hourly, weightsDoc: read(`forecast/${okres.code}.json`), scores, meta });
  writeFileSync(join(out, "okresy", `${okres.code}.json`), JSON.stringify(doc));
  writeFileSync(join(out, "okresy", `${okres.code}.csv`), okresCsv(doc));
  if (withAi) {
    const ai = aiOkresDoc({ okres, outlook, hourly, aiForecast, aiOutlook, meta });
    if (ai) {
      writeFileSync(join(out, "ai", "okresy", `${okres.code}.json`), JSON.stringify(ai));
      aiCount++;
    }
  }
  // the obce (a test): one file each; a broken okres file must not fail the build
  const obceFile = read(`forecast/obce-${okres.code}.json`);
  if (obceFile) {
    try {
      mkdirSync(join(out, "obce", okres.code), { recursive: true });
      for (const { id, doc: obec } of obceDocs({ okresDoc: doc, obceFile, meta })) {
        writeFileSync(join(out, "obce", okres.code, `${id}.json`), JSON.stringify(obec));
        obceRows.push([okres.code, id, obec.obec.name, obec.obec.lat, obec.obec.lon]);
        obceCount++;
      }
    } catch (e) {
      console.log(`obce of ${okres.code} skipped: ${e.message}`);
    }
  }
}
const generated = hourly?.generated ?? outlook.generated;
writeFileSync(join(out, "index.json"), JSON.stringify(indexDoc(okresy, meta, generated), null, 1));
if (obceCount) writeFileSync(join(out, "obce", "index.json"), JSON.stringify(obceIndexDoc(obceRows, generated)));
console.log(`open data: ${okresy.length} okresy, ${aiCount} AI files, ${obceCount} obce → ${out}`);
