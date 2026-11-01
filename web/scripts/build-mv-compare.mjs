// Turn the engine's same-sample comparison files (public/data/scores/ai/fc/compare/<region>.json,
// from ai.zip) into score files with MeteoVerdict's own models ranked among the public ones:
// public/data/scores/mv/<okres|kraj>/<variable>.json (src/mv-compare.js). Without the files it
// writes nothing, and the page hides the "Include MeteoVerdict models" choice.
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MV_COLUMNS, regionRows } from "../src/mv-compare.js";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const scores = join(web, "public", "data", "scores");
const from = join(scores, "ai", "fc", "compare");
const out = join(scores, "mv");

rmSync(out, { recursive: true, force: true });
if (!existsSync(join(from, "index.json"))) {
  console.log("no same-sample comparison files: no MeteoVerdict models in the comparison");
  process.exit(0);
}
const read = (path) => JSON.parse(readFileSync(path, "utf-8"));
const index = read(join(from, "index.json"));
const meta = existsSync(join(scores, "meta.json")) ? read(join(scores, "meta.json")) : {};
const minStations = meta.min_stations ?? 3;
const sample = { from: index.from ?? null, to: index.to ?? null, days: index.test_days ?? null };

const files = new Map(); // "level/variable" → rows
for (const name of readdirSync(from)) {
  if (!/^CZ\w+\.json$/.test(name)) continue;
  const doc = read(join(from, name));
  if (doc.level !== "okres" && doc.level !== "kraj") continue;
  for (const [variable, rows] of regionRows(doc, minStations)) {
    const key = `${doc.level}/${variable}`;
    files.set(key, [...(files.get(key) ?? []), ...rows]);
  }
}
for (const [key, rows] of files) {
  const path = join(out, `${key}.json`);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify({ columns: MV_COLUMNS, rows, sample }));
}
console.log(`MeteoVerdict models in the comparison: ${files.size} files (${sample.from} to ${sample.to})`);
