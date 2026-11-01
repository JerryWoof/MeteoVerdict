import { readdirSync, readFileSync } from "node:fs";
import assert from "node:assert/strict";
import test from "node:test";
import { prerenderI18n } from "../scripts/prerender-i18n.mjs";
import { NAV } from "./nav.js";

const ROOT = new URL("../", import.meta.url);
const PAGES = readdirSync(ROOT).filter((f) => f.endsWith(".html"));
const links = (html) => [...html.match(/<nav class="site-nav"[\s\S]*?<\/nav>/)[0].matchAll(/<a href="([^"]*)"[^>]*>([^<]*)/g)].map((m) => [m[1], m[2]]);
const WANT = NAV.map((n) => [n.href, n.label]);

test("every page's menu in the sources is the shared one (and nothing of the old tabs)", () => {
  assert.ok(PAGES.length >= 10);
  for (const file of PAGES) {
    assert.deepEqual(links(readFileSync(new URL(file, ROOT), "utf8")), WANT, file);
  }
});

test("built pages: the same menu everywhere, exactly the page's own item highlighted", () => {
  for (const file of PAGES) {
    const out = prerenderI18n(readFileSync(new URL(file, ROOT), "utf8"), file);
    assert.deepEqual(links(out), WANT, file);
    const current = [...out.matchAll(/<a href="([^"]*)"[^>]*aria-current="page"/g)].map((m) => m[1]);
    const own = file === "index.html" || file === "forecast-detail.html" ? "./" : file;
    assert.deepEqual(current, NAV.some((n) => n.href === own) ? [own] : [], file);
  }
});

test("the 404 page offers the same four pages", () => {
  const html = readFileSync(new URL("public/404.html", ROOT), "utf8");
  assert.deepEqual([...html.match(/<nav>[\s\S]*?<\/nav>/)[0].matchAll(/>([^<]+)<\/a>/g)].map((m) => m[1]), NAV.map((n) => n.label));
});
