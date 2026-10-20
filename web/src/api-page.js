import "./style.css";

import { dataBlocks } from "./data-text.js";
import { setUpLanguage } from "./i18n.js";
import { renderBlocks } from "./info-page.js";
import { SCHEDULE, pragueClocks } from "./schedule.js";
import { displayName } from "./tv.js";

const t = setUpLanguage();

async function get(path, as = "json") {
  try {
    const response = await fetch(path);
    if (!response.ok) return null;
    return as === "json" ? await response.json() : await response.text();
  } catch {
    return null;
  }
}

/** The schedule of the workflows in Prague time (CET or CEST), and the page's text below. */
function showSchedule() {
  const language = document.documentElement.lang;
  const locale = language === "cs" ? "cs-CZ" : "en-GB";
  const now = new Date();
  const summer = new Intl.DateTimeFormat("en", { timeZone: "Europe/Prague", timeZoneName: "shortOffset" })
    .formatToParts(now).find((p) => p.type === "timeZoneName")?.value === "GMT+2";
  const zone = language === "cs" ? (summer ? "SELČ" : "SEČ") : (summer ? "CEST" : "CET");
  const clocks = (times) => pragueClocks(times, now, locale);
  document.getElementById("updates").textContent = t("api.when", {
    daily: clocks(SCHEDULE.daily),
    outlook: clocks(SCHEDULE.outlook),
    zone,
  });
  const blocks = dataBlocks(language, {
    outlook: clocks(SCHEDULE.outlook),
    daily: clocks(SCHEDULE.daily),
    runs: clocks(SCHEDULE.runs),
    chmi: clocks(SCHEDULE.chmi),
    sun: clocks(SCHEDULE.sun),
    zone,
  });
  renderBlocks(document.getElementById("doc-api"), blocks.api);
  renderBlocks(document.getElementById("doc-more"), blocks.more);
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (id && !/^CZ/.test(id)) document.getElementById(id)?.scrollIntoView();
}

async function main() {
  showSchedule();
  const index = await get("api/v1/index.json");
  const status = document.getElementById("status");
  const select = document.getElementById("okres");
  if (!index) {
    status.textContent = t("api.none");
    select.disabled = true;
    return;
  }
  status.textContent = t("tv.updated", {
    time: new Intl.DateTimeFormat(document.documentElement.lang, {
      dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague",
    }).format(new Date(index.generated)),
  });
  const okresy = index.okresy.slice().sort((a, b) => displayName(a.name).localeCompare(displayName(b.name), "cs"));
  select.replaceChildren(
    ...okresy.map((o) => Object.assign(document.createElement("option"), { value: o.code, textContent: `${displayName(o.name)} (${o.code})` })),
  );
  async function show(code, remember = true) {
    const okres = okresy.find((o) => o.code === code);
    const links = document.getElementById("links");
    links.replaceChildren(
      ...[["JSON", okres.json], ["CSV", okres.csv]].map(([label, href]) => {
        const li = document.createElement("li");
        const a = Object.assign(document.createElement("a"), { href, textContent: href });
        li.append(`${label}: `, a);
        return li;
      }),
    );
    const csv = await get(`api/v1/okresy/${code}.csv`, "text");
    document.getElementById("preview").textContent = csv ? `${csv.split("\n").slice(0, 8).join("\n")}\n…` : "";
    if (remember) window.history.replaceState(null, "", `#${code}`);
  }
  const wanted = window.location.hash.slice(1);
  select.value = okresy.some((o) => o.code === wanted) ? wanted : (okresy.find((o) => o.code === "CZ0100") ?? okresy[0]).code;
  select.addEventListener("change", () => show(select.value));
  // a link to a section (#releases) keeps its address
  await show(select.value, !wanted || okresy.some((o) => o.code === wanted));
}

main();
