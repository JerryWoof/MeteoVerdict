// Text pages (About, Methodology, Collaboration): the text lives in pages-text.js, one block
// list per page and language, and is built here with DOM calls only.
import "./style.css";

import { setUpLanguage } from "./i18n.js";
import { parseInline } from "./inline-text.js";
import { FILE as LOSO_FILE, losoBlocks, losoSummary } from "./obce-loso.js";
import { PAGES } from "./pages-text.js";

function inline(parent, text) {
  for (const part of parseInline(text)) {
    if (part.href) {
      const a = document.createElement("a");
      a.href = part.href;
      a.textContent = part.text;
      parent.append(a);
    } else if (part.bold) {
      const b = document.createElement("strong");
      b.textContent = part.text;
      parent.append(b);
    } else {
      parent.append(part.text);
    }
  }
  return parent;
}

function make(tag, text, attrs = {}) {
  const e = document.createElement(tag);
  if (text != null) inline(e, text);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

/** Blocks: ["h", text, id?], ["p", text], ["note", text], ["ul", [text, …]],
 * ["table", {head: [..], rows: [[..], …]}], ["code", text], ["slot", id] (an empty
 * section the page fills from data, `fillSlots`). */
export function renderBlocks(container, blocks) {
  for (const [kind, body, id] of blocks) {
    if (kind === "h") container.append(make("h2", body, id ? { id } : {}));
    else if (kind === "p") container.append(make("p", body));
    else if (kind === "note") container.append(make("p", body, { class: "note" }));
    else if (kind === "code") container.append(make("pre", body, { class: "code" }));
    else if (kind === "slot") container.append(make("section", null, { id: body, class: "slot" }));
    else if (kind === "ul") {
      const ul = document.createElement("ul");
      for (const item of body) ul.append(make("li", item));
      container.append(ul);
    } else if (kind === "table") {
      const wrap = make("div", null, { class: "scroll" });
      const table = make("table", null, { class: "doc-table data-table" });
      const row = (cells, tag) => {
        const tr = document.createElement("tr");
        for (const c of cells) tr.append(make(tag, c));
        table.append(tr);
      };
      row(body.head, "th");
      for (const r of body.rows) row(r, "td");
      wrap.append(table);
      container.append(wrap);
    }
  }
}

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

// the sections built from data: the obec forecast's leave-one-station-out test
async function fillSlots(t, language) {
  const loso = document.getElementById("obce-loso");
  if (!loso) return;
  renderBlocks(loso, losoBlocks(losoSummary(await getJson(LOSO_FILE)), language, t));
}

function scrollToHash() {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (id) document.getElementById(id)?.scrollIntoView();
}

function main() {
  const t = setUpLanguage();
  const main = document.getElementById("info");
  const page = PAGES[main.dataset.page];
  const text = page[document.documentElement.lang] ?? page.cs;
  document.title = `MeteoVerdict: ${text.title}`;
  document.getElementById("info-title").textContent = text.title;
  renderBlocks(main, text.blocks);
  // a link to a section (#contact) is built after the load: scroll to it now, and again
  // once the sections from data are there
  scrollToHash();
  fillSlots(t, document.documentElement.lang).then(scrollToHash);
}

if (typeof document !== "undefined" && document.getElementById("info")) main();
