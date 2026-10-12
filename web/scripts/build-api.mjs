// Write the open data files (src/api.js) into public/api/v1 from the data that
// scripts/copy-data.mjs put into public/data/scores. Without the data (a local build
// before any forecast) it writes nothing and says so.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { SCORE_VARIABLES, VERSION, indexDoc, okresCsv, okresDoc } from "../src/api.js";
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
for (const okres of okresy) {
  const doc = okresDoc({ okres, outlook, hourly, weightsDoc: read(`forecast/${okres.code}.json`), scores, meta });
  writeFileSync(join(out, "okresy", `${okres.code}.json`), JSON.stringify(doc));
  writeFileSync(join(out, "okresy", `${okres.code}.csv`), okresCsv(doc));
}
const generated = hourly?.generated ?? outlook.generated;
writeFileSync(join(out, "index.json"), JSON.stringify(indexDoc(okresy, meta, generated), null, 1));
console.log(`open data: ${okresy.length} okresy → ${out}`);
