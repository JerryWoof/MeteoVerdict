import "./style.css";

import { dataBlocks } from "./data-text.js";
import { setUpLanguage } from "./i18n.js";
import { renderBlocks } from "./info-page.js";
import { SCHEDULE, pragueClocks } from "./schedule.js";
import { displayName } from "./tv.js";
import { obecCsvLines } from "./api.js";
import { obceOf, setUpBuilder } from "./trmnl.js";

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
    // the same date and time as in every page's header: "21. 10. 2026 1:32", "21 Oct 2026, 01:32"
    time: new Intl.DateTimeFormat(document.documentElement.lang === "cs" ? "cs-CZ" : "en-GB", {
      dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Prague",
    }).format(new Date(index.generated)),
  });
  const okresy = index.okresy.slice().sort((a, b) => displayName(a.name).localeCompare(displayName(b.name), "cs"));
  select.replaceChildren(
    ...okresy.map((o) => Object.assign(document.createElement("option"), { value: o.code, textContent: `${displayName(o.name)} (${o.code})` })),
  );
  const model = document.getElementById("model");
  model.replaceChildren(
    Object.assign(document.createElement("option"), { value: "blend", textContent: t("api.modelBlend") }),
    Object.assign(document.createElement("option"), { value: "ai", textContent: t("api.modelAi") }),
  );
  const obecSelect = document.getElementById("obec");
  let obceIndex; // api/v1/obce/index.json, fetched once
  async function fillObce(code, wantedId = "") {
    obceIndex ??= (await get("api/v1/obce/index.json")) ?? { obce: [] };
    const obce = obceOf(obceIndex, code);
    obecSelect.replaceChildren(
      Object.assign(document.createElement("option"), { value: "", textContent: t("api.obecWhole") }),
      ...obce.map((o) => Object.assign(document.createElement("option"), { value: o.id, textContent: o.name })),
    );
    obecSelect.value = obce.some((o) => o.id === wantedId) ? wantedId : "";
    obecSelect.disabled = !obce.length;
  }
  const linkItem = (label, href) => {
    const li = document.createElement("li");
    li.append(`${label}: `, Object.assign(document.createElement("a"), { href, textContent: href }));
    return li;
  };
  async function show(code, remember = true) {
    const links = document.getElementById("links");
    const preview = document.getElementById("preview");
    const ai = model.value === "ai";
    const obec = obecSelect.value;
    if (obec) {
      const href = `api/v1/${ai ? "ai/obce" : "obce"}/${code}/${obec}.json`;
      links.replaceChildren(linkItem("JSON", href), Object.assign(document.createElement("li"), { textContent: t("api.obecNote") }));
      const lines = obecCsvLines(await get(href));
      preview.textContent = lines.length ? `${lines.join("\n")}\n…` : "";
    } else {
      const base = `api/v1/${ai ? "ai/okresy" : "okresy"}/${code}`;
      links.replaceChildren(linkItem("JSON", `${base}.json`), linkItem("CSV", `${base}.csv`),
        ...(ai ? [Object.assign(document.createElement("li"), { textContent: t("api.aiNote") })] : []));
      const csv = await get(`${base}.csv`, "text");
      preview.textContent = csv ? `${csv.split("\n").slice(0, 8).join("\n")}\n…` : "";
    }
    if (remember) window.history.replaceState(null, "", `#${code}${obec ? `/${obec}` : ""}`);
  }
  const [wanted, wantedObec = ""] = decodeURIComponent(window.location.hash.slice(1)).split("/");
  const known = okresy.some((o) => o.code === wanted);
  select.value = known ? wanted : (okresy.find((o) => o.code === "CZ0100") ?? okresy[0]).code;
  setUpBuilder(select, t);
  await fillObce(select.value, known ? wantedObec : "");
  select.addEventListener("change", async () => { await fillObce(select.value); show(select.value); });
  obecSelect.addEventListener("change", () => show(select.value));
  model.addEventListener("change", () => show(select.value));
  // a link to a section (#releases) keeps its address
  await show(select.value, !wanted || known);
}

main();
