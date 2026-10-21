// The text-page blocks (pages-text.js) as an HTML string, for the build-time prerender: crawlers
// without JavaScript read the page text. The same blocks are built with DOM calls in info-page.js
// (renderBlocks), which replaces this markup at load. "slot" blocks (filled from data) are left out.
import { parseInline } from "./inline-text.js";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function inlineHtml(text) {
  return parseInline(text).map((p) => {
    let h = esc(p.text);
    if (p.href) h = `<a href="${esc(p.href)}">${h}</a>`;
    else if (p.code) h = `<code>${h}</code>`;
    return p.bold ? `<strong>${h}</strong>` : h;
  }).join("");
}

export function blocksHtml(blocks) {
  let out = "";
  for (const [kind, body, id] of blocks) {
    if (kind === "h") out += `<h2${id ? ` id="${esc(id)}"` : ""}>${inlineHtml(body)}</h2>\n`;
    else if (kind === "h3") out += `<h3>${inlineHtml(body)}</h3>\n`;
    else if (kind === "p") out += `<p>${inlineHtml(body)}</p>\n`;
    else if (kind === "note") out += `<p class="note">${inlineHtml(body)}</p>\n`;
    else if (kind === "code") out += `<pre class="code">${inlineHtml(body)}</pre>\n`;
    else if (kind === "ul") out += `<ul>${body.map((i) => `<li>${inlineHtml(i)}</li>`).join("")}</ul>\n`;
    else if (kind === "table") {
      const row = (cells, tag) => `<tr>${cells.map((c) => `<${tag}>${inlineHtml(c)}</${tag}>`).join("")}</tr>`;
      out += `<div class="scroll"><table class="doc-table data-table">${row(body.head, "th")}${body.rows.map((r) => row(r, "td")).join("")}</table></div>\n`;
    }
  }
  return out;
}
