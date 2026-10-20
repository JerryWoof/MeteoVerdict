// Inline markup of the text pages (pages-text.js, data-text.js): [link](url), **bold** and `code`.

/** "text with [a link](url), **bold** and `code`" → [{text, href?, bold?, code?}], never HTML. */
export function parseInline(text) {
  const parts = [];
  const re = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index) });
    parts.push(m[1] != null ? { text: m[1], href: m[2] } : m[3] != null ? { text: m[3], bold: true } : { text: m[4], code: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}
