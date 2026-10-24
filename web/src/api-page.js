import "./style.css";

import { dataBlocks, exampleBlocks } from "./data-text.js";
import { setUpLanguage } from "./i18n.js";
import { renderBlocks } from "./info-page.js";
import { displayName } from "./tv.js";
import { SITE, docPreview, snippet } from "./api.js";
import { obceOf } from "./trmnl.js";

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

/** The text below the picker, and a link to a section (#releases) opens its fold. */
function showText() {
  const language = document.documentElement.lang;
  const blocks = dataBlocks(language);
  renderBlocks(document.getElementById("doc-example"), exampleBlocks(language));
  renderBlocks(document.getElementById("doc-api"), blocks.api);
  renderBlocks(document.getElementById("doc-more"), blocks.more);
  const id = decodeURIComponent(window.location.hash.slice(1));
  const target = id && !/^CZ/.test(id) ? document.getElementById(id) : null;
  if (!target) return;
  const fold = target.closest("details");
  if (fold) fold.open = true;
  target.scrollIntoView();
}

async function main() {
  showText();
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
  const links = document.getElementById("links");
  const preview = document.getElementById("preview");
  const tabs = document.getElementById("tabs");
  let tab = "url";
  let file = ""; // the shown file's address, for the code tabs
  function showTab() {
    for (const button of tabs.querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.tab === tab));
    links.hidden = tab !== "url";
    preview.hidden = tab === "url";
    if (tab === "preview") preview.textContent = preview.dataset.doc ?? "";
    else if (tab !== "url") preview.textContent = snippet(tab, `${SITE}/${file}`);
  }
  async function show(okresCode, remember = true) {
    const ai = model.value === "ai";
    const obec = obecSelect.value;
    const href = obec
      ? `api/v1/${ai ? "ai/obce" : "obce"}/${okresCode}/${obec}.json`
      : `api/v1/${ai ? "ai/okresy" : "okresy"}/${okresCode}.json`;
    file = href;
    links.replaceChildren(linkItem("JSON", href),
      ...(obec ? [Object.assign(document.createElement("li"), { textContent: t("api.obecNote") })] : []));
    preview.dataset.doc = docPreview(await get(href));
    showTab();
    if (remember) window.history.replaceState(null, "", `#${okresCode}${obec ? `/${obec}` : ""}`);
  }
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    tab = button.dataset.tab;
    showTab();
  });
  const [wanted, wantedObec = ""] = decodeURIComponent(window.location.hash.slice(1)).split("/");
  const known = okresy.some((o) => o.code === wanted);
  select.value = known ? wanted : (okresy.find((o) => o.code === "CZ0100") ?? okresy[0]).code;
  await fillObce(select.value, known ? wantedObec : "");
  select.addEventListener("change", async () => { await fillObce(select.value); show(select.value); });
  obecSelect.addEventListener("change", () => show(select.value));
  model.addEventListener("change", () => show(select.value));
  // a link to a section (#releases) keeps its address
  await show(select.value, !wanted || known);
}

main();
