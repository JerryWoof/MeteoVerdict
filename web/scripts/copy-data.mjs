// Copy the data the map needs into public/data (not committed):
// - region boundaries from the Python package (ČÚZK, CC BY 4.0),
// - scores from site/data (the daily workflow commits the summary levels; the deploy
//   workflow adds the okres and station levels from the release data-latest).
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(web, "..");
const out = join(web, "public", "data");

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
for (const name of ["kraje.geojson", "okresy.geojson"]) {
  cpSync(join(repo, "src", "meteoverdict", "data", name), join(out, name));
}
const scores = join(repo, "site", "data");
if (existsSync(scores)) {
  cpSync(scores, join(out, "scores"), { recursive: true });
}
// the monthly accuracy reports (`mvd monthly-report`, committed under site/reports)
const reports = join(repo, "site", "reports");
if (existsSync(reports)) {
  cpSync(reports, join(out, "..", "reports"), { recursive: true });
}
console.log(`copied boundaries${existsSync(scores) ? " and scores" : ""} to ${out}`);
