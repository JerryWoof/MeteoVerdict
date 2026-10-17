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
