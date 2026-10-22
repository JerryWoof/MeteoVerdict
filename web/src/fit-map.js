// The map pages (home, forecast, radar, heatmap) fit the window on a desktop or tablet:
// header, controls, map and footer fill the height, so the footer is visible without scrolling
// the page. This sets --map-height (which the map and its panels use) to what is left under
// the controls. On phones, and when the window is too low, the map keeps its usual height
// (the footer then follows the page).

const MIN_WIDTH = 701;
const MIN_HEIGHT = 560;
const MIN_MAP = 420;
const MAX_MAP = 1100;

/** The map's height for a window of ``viewport`` px: what is left after the part of the page
 * above the map (``top``) and the part below it (``below``, with the footer). */
export function fitMapHeight(viewport, top, below) {
  return Math.min(MAX_MAP, Math.max(MIN_MAP, Math.floor(viewport - top - below)));
}

function fit() {
  const root = document.documentElement;
  const wrap = document.querySelector("main .map-wrap");
  const footer = document.querySelector("body > footer");
  if (!wrap || !footer || window.innerWidth < MIN_WIDTH || window.innerHeight < MIN_HEIGHT) {
    root.style.removeProperty("--map-height");
    return;
  }
  const main = wrap.closest("main");
  const top = wrap.getBoundingClientRect().top + window.scrollY;
  let below = footer.offsetHeight + parseFloat(getComputedStyle(footer).marginTop) + parseFloat(getComputedStyle(main).paddingBottom);
  for (let n = wrap.nextElementSibling; n; n = n.nextElementSibling) {
    if (!n.hidden) below += n.offsetHeight + parseFloat(getComputedStyle(n).marginTop) + parseFloat(getComputedStyle(n).marginBottom);
  }
  root.style.setProperty("--map-height", `${fitMapHeight(window.innerHeight, top, below)}px`);
}

if (typeof document !== "undefined" && document.querySelector("main .map-wrap")) {
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      fit();
    });
  };
  window.addEventListener("resize", schedule);
  const watch = new ResizeObserver(schedule);
  const wrap = document.querySelector("main .map-wrap");
  // the part above the map (title, intro, controls) changes with the language and the window width
  for (let n = wrap.previousElementSibling; n; n = n.previousElementSibling) watch.observe(n);
  const header = document.querySelector("body > header");
  if (header) watch.observe(header);
  watch.observe(document.querySelector("body > footer"));
  schedule();
}
