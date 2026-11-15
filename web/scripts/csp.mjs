// Last build step: the full Content-Security-Policy of every built page, as a <meta> right
// after <meta charset> (a meta policy only covers what comes after it). GitHub Pages cannot
// send headers, so this is the only place. Inline scripts (theme, English text, analytics
// loader, speculation rules) differ per page: each page gets the hashes of its own.
// Hosts: the map tiles and glyphs (OpenFreeMap), the relief tiles (AWS terrain tiles), the
// radar's live frames and the data page's pictures (raw.githubusercontent.com) and the
// cookieless Cloudflare analytics. Inline styles stay allowed (MapLibre and the charts set them).
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SKIP = new Set(["data", "api", "radar", "assets"]); // folders without pages (and large)

export const HOSTS = {
  img: ["https://raw.githubusercontent.com", "https://tiles.openfreemap.org", "https://s3.amazonaws.com"],
  connect: ["https://tiles.openfreemap.org", "https://raw.githubusercontent.com", "https://s3.amazonaws.com", "https://cloudflareinsights.com"],
  script: ["https://static.cloudflareinsights.com"],
};

const INLINE = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;

/** The hashes of a page's inline scripts (not JSON-LD, which is data, nor external ones). */
export function inlineHashes(html) {
  const out = new Set();
  for (const [, attrs, body] of html.matchAll(INLINE)) {
    if (/\bsrc=/.test(attrs) || /application\/ld\+json/.test(attrs)) continue;
    out.add(`'sha256-${createHash("sha256").update(body, "utf8").digest("base64")}'`);
  }
  return [...out];
}

export function policy(hashes) {
  return [
    "default-src 'self'",
    `script-src 'self' ${[...HOSTS.script, ...hashes].join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${HOSTS.img.join(" ")}`,
    "font-src 'self' data:",
    `connect-src 'self' ${HOSTS.connect.join(" ")}`,
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

/** The page with its policy: any earlier CSP meta removed, the new one first in <head>. */
export function withPolicy(html) {
  if (!/<meta charset="[^"]*"\s*\/?>/i.test(html)) return html;
  const clean = html.replace(/\s*<meta http-equiv="Content-Security-Policy"[^>]*>/gi, "");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${policy(inlineHashes(clean))}" />`;
  return clean.replace(/(<meta charset="[^"]*"\s*\/?>)/i, `$1\n    ${meta}`);
}

function pages(dir) {
  return readdirSync(dir).flatMap((name) => {
    const file = join(dir, name);
    if (statSync(file).isDirectory()) return SKIP.has(name) ? [] : pages(file);
    return name.endsWith(".html") ? [file] : [];
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
  const files = pages(dist);
  for (const file of files) writeFileSync(file, withPolicy(readFileSync(file, "utf8")));
  console.log(`CSP: ${files.length} pages`);
}
