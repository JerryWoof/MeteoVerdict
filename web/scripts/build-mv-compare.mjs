// Turn the engine's same-sample comparison files (public/data/scores/ai/fc/compare/<region>.json,
// from ai.zip) into score files with MeteoVerdict's own models ranked among the public ones:
// public/data/scores/mv/<okres|kraj>/<variable>.json (src/mv-compare.js). Without the files it
// writes nothing, and the page hides the "Include MeteoVerdict models" choice.
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MV_COLUMNS, regionRows, windowStart } from "../src/mv-compare.js";

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
const meta = existsSync(join(scores, "meta.json")) ? read(join(scores, "meta.json")) : {};
const minStations = meta.min_stations ?? 3;
const WEEK = 7;

// the periods: "60d" the validation sample (ours and the public models; MeteoVerdict AI is too
// young for it), "week" the last 7 days of the live sample, where the AI is scored too
const index = read(join(from, "index.json"));
const liveDir = join(from, "live");
const periods = [{ name: "60d", dir: from, sample: { from: index.from ?? null, to: index.to ?? null, days: index.test_days ?? null }, week: null }];
if (existsSync(join(liveDir, "index.json"))) {
  const live = read(join(liveDir, "index.json"));
  if (live.to) {
    const week = { from: windowStart(live.to, WEEK), to: live.to };
    periods.push({ name: "week", dir: liveDir, sample: { ...week, days: WEEK }, week });
  }
}

for (const period of periods) {
  const files = new Map(); // "level/variable" → rows
  for (const name of readdirSync(period.dir)) {
    if (!/^CZ\w+\.json$/.test(name)) continue;
    const doc = read(join(period.dir, name));
    if (doc.level !== "okres" && doc.level !== "kraj") continue;
    for (const [variable, rows] of regionRows(doc, minStations, period.week)) {
      const key = `${doc.level}/${variable}`;
      files.set(key, [...(files.get(key) ?? []), ...rows]);
    }
  }
  for (const [key, rows] of files) {
    const path = join(out, period.name, `${key}.json`);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify({ columns: MV_COLUMNS, rows, sample: period.sample }));
  }
  console.log(`MeteoVerdict models, ${period.name}: ${files.size} files (${period.sample.from} to ${period.sample.to})`);
}
