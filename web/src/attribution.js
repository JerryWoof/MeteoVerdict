// MapLibre's compact attribution opens itself when the style's attribution arrives and our
// pages folded it again on "load": open for a moment, it was the LCP element of the radar and
// a layout shift when it shrank. Fold it in the same task it opens (the control listens to
// "styledata" before us), once; a later click by the reader opens it as usual.
export function foldAttribution(map) {
  const fold = () => {
    const box = map.getContainer().querySelector(".maplibregl-ctrl-attrib.maplibregl-compact");
    if (!box) return;
    box.classList.remove("maplibregl-compact-show");
    map.off("styledata", fold);
    map.off("resize", fold);
  };
  map.on("styledata", fold);
  map.on("resize", fold);
  fold();
}
