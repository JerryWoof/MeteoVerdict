// A clicked okres's panel floats on the map at its full length (never its own scroll
// box). When it is longer than the map, the space it needs is added under the map, so the
// map keeps its size and Czechia stays where it is when another okres is chosen.

/** Keep room under `frame` for the `panels` (absolutely placed in `wrap`). */
export function keepRoomForPanels(wrap, frame, panels) {
  const fit = () => {
    let bottom = 0;
    for (const panel of panels) {
      if (!panel || panel.hidden || !panel.offsetParent || getComputedStyle(panel).position !== "absolute") continue;
      bottom = Math.max(bottom, panel.offsetTop + panel.offsetHeight);
    }
    const extra = Math.max(0, bottom + 12 - (frame.offsetTop + frame.offsetHeight));
    wrap.style.paddingBottom = extra ? `${extra}px` : "";
  };
  const observer = new ResizeObserver(fit);
  for (const panel of panels) if (panel) observer.observe(panel);
  observer.observe(frame);
  window.addEventListener("resize", fit);
  fit();
  return fit;
}

/** The room a map leaves on the right for an open okres panel (its CSS width, 21rem by default, plus
 * the zoom buttons): fixed, so choosing another okres never moves the map. */
export function panelRoom(widthRem = 21, share = 0, wrapWidth = 0, maxRem = 0) {
  const rem = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  // with a share: that part of the map's width, kept between widthRem and maxRem (when given)
  let width = share ? share * wrapWidth : widthRem * rem;
  if (share && maxRem) width = Math.min(Math.max(width, widthRem * rem), maxRem * rem);
  return Math.round(width + 70);
}

/** Whether someone has moved or zoomed `map` themselves: after that the page never moves it. */
export function userMoved(map) {
  let moved = false;
  map.on("movestart", (event) => {
    if (event.originalEvent) moved = true;
  });
  return () => moved;
}

/** Under the map (a phone, a narrow window: the panel is not floating on it) the page scrolls
 * smoothly to a panel that opens, and back to the map when it closes. */
export function scrollToPanel(panel, open) {
  if (!panel || getComputedStyle(panel).position === "absolute") return;
  setTimeout(() => {
    if (open) panel.scrollIntoView({ block: "start", behavior: "smooth" });
    else panel.parentElement?.querySelector(".map-frame, .maplibregl-map")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, 120);
}
