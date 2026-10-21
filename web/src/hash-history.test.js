import assert from "node:assert/strict";
import { test } from "node:test";

import { hashHistory } from "./hash-history.js";

/** A window with an address, a history (entries, position) and the two events, as a browser keeps them. */
function fakeWindow(hash = "") {
  const listeners = { hashchange: [], popstate: [] };
  const entries = [hash];
  let at = 0;
  const win = {
    location: { pathname: "/page.html", search: "", hash },
    addEventListener: (type, f) => listeners[type].push(f),
    history: {
      pushState: (_s, _t, url) => {
        entries.splice(at + 1, Infinity, url.replace(/^[^#]*/, ""));
        at += 1;
        win.location.hash = entries[at];
      },
      replaceState: (_s, _t, url) => {
        entries[at] = url.replace(/^[^#]*/, "");
        win.location.hash = entries[at];
      },
    },
    // Back: the browser sends popstate and then hashchange (when the hash differs)
    back() {
      const before = win.location.hash;
      at -= 1;
      win.location.hash = entries[at];
      for (const f of listeners.popstate) f();
      if (before !== win.location.hash) for (const f of listeners.hashchange) f();
    },
    entries: () => [...entries],
  };
  return win;
}

test("hashHistory: push adds an entry, replace changes the current one; Back applies once", () => {
  const win = fakeWindow("#a");
  const applied = [];
  const { write } = hashHistory((hash) => applied.push(hash), win);
  write("#a/1"); // a small change
  write("#b", true); // a big one
  write("#b/2");
  assert.deepEqual(win.entries(), ["#a/1", "#b/2"]);
  assert.deepEqual(applied, []); // the page's own writes are not applied again
  win.back();
  assert.deepEqual(applied, ["#a/1"]);
});

test("hashHistory: an unchanged hash writes nothing; '#' and '' clear the hash", () => {
  const win = fakeWindow("#a");
  const { write } = hashHistory(() => {}, win);
  write("#a", true);
  assert.deepEqual(win.entries(), ["#a"]);
  write("#");
  assert.deepEqual(win.entries(), [""]);
});
