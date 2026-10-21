// Inline markup of the text pages (pages-text.js, data-text.js): [link](url), **bold** and `code`.

/** "text with [a link](url), **bold** (links inside too) and `code`" → [{text, href?, bold?, code?}], never HTML. */
export function parseInline(text) {
  const parts = [];
  const re = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index) });
    if (m[3] != null) {
      // bold may hold links ("**[Předpověď](forecast.html)**"): its parts, each bold
      for (const inner of parseInline(m[3])) parts.push({ ...inner, bold: true });
    } else {
      parts.push(m[1] != null ? { text: m[1], href: m[2] } : { text: m[4], code: true });
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}
