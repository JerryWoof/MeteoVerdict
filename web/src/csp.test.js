import assert from "node:assert/strict";
import test from "node:test";
import { inlineHashes, withPolicy } from "../scripts/csp.mjs";

test("the policy goes first in <head> with the hashes of the page's own inline scripts", () => {
  const html = `<head><meta charset="UTF-8" /><script>a()</script><script type="application/ld+json">{}</script>`
    + `<script type="module" src="/x.js"></script><meta http-equiv="Content-Security-Policy" content="old" /></head>`;
  const out = withPolicy(html);
  assert.equal(inlineHashes(html).length, 1);
  assert.match(out, /^<head><meta charset="UTF-8" \/>\s*<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' https:\/\/static\.cloudflareinsights\.com 'sha256-[^']+'; /);
  assert.equal(out.match(/Content-Security-Policy/g).length, 1);
  assert.doesNotMatch(out, /content="old"/);
});
