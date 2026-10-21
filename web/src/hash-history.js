// The pages' view in the address's hash, with the browser's history: a big change (another
// tab, day, place or region) is a new history entry, so Back returns to the view before it;
// small changes (a slider, a colour, a checkbox) replace the current entry, so Back does not
// step through every one of them. Back/Forward and a link pasted on the open page re-apply the
// view without a reload.

/**
 * `apply(hash)` runs when the hash changes from outside the page's own writes (Back, Forward,
 * a pasted link, `location.hash = …`), once per change: the browser sends both "popstate" and
 * "hashchange" for one Back between two hashes. Returns `write(hash, push)`, which puts the
 * page's view in the address (nothing when it is there already; "" removes the hash).
 */
export function hashHistory(apply, win = window) {
  let last = win.location.hash;
  const run = () => {
    if (win.location.hash === last) return;
    last = win.location.hash;
    apply(last);
  };
  win.addEventListener("hashchange", run);
  win.addEventListener("popstate", run);
  return {
    write(hash, push = false) {
      const next = hash === "#" ? "" : hash;
      if (next === win.location.hash) return;
      const { pathname, search } = win.location;
      win.history[push ? "pushState" : "replaceState"](null, "", `${pathname}${search}${next}`);
      last = win.location.hash;
    },
  };
}
