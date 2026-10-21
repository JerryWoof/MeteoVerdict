import assert from "node:assert/strict";
import { test } from "node:test";

import { parseInline } from "./inline-text.js";
import { PAGES } from "./pages-text.js";

test("parseInline: links and bold, no HTML", () => {
  assert.deepEqual(parseInline("a [b](https://x.cz) **c** <i>d</i>"), [
    { text: "a " },
    { text: "b", href: "https://x.cz" },
    { text: " " },
    { text: "c", bold: true },
    { text: " <i>d</i>" },
  ]);
});

test("every page has both languages with the same block kinds", () => {
  for (const [name, page] of Object.entries(PAGES)) {
    assert.deepEqual(Object.keys(page).sort(), ["cs", "en"], name);
    const kinds = (lang) => page[lang].blocks.map(([k]) => k).join();
    assert.equal(kinds("cs"), kinds("en"), name);
  }
});

test("parseInline: a link inside bold is a bold link, not raw Markdown", () => {
  assert.deepEqual(parseInline("**[Předpověď](forecast.html)**: dny"), [
    { text: "Předpověď", href: "forecast.html", bold: true },
    { text: ": dny" },
  ]);
  assert.deepEqual(parseInline("**a [b](x.html) c**"), [
    { text: "a ", bold: true },
    { text: "b", href: "x.html", bold: true },
    { text: " c", bold: true },
  ]);
});

test("parseInline: `code`", () => {
  assert.deepEqual(parseInline("a `b.json` c"), [{ text: "a " }, { text: "b.json", code: true }, { text: " c" }]);
});
