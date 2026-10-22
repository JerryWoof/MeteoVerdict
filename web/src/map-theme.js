// Dark colours for the MapLibre maps. A "spec" maps layer ids to paint (or "layout:"-prefixed
// layout) properties and their [light, dark] values; `themeMap` applies one to a live map
// (setPaintProperty on the known layers, so data layers survive, unlike setStyle), and
// `withTheme` bakes the current variant into layer definitions at creation. Light values are
// the ones the maps always had.

import { isDark, onThemeChange } from "./theme.js";

// shared [light, dark] pairs
export const PAGE_BG = ["#f4f1ea", "#151412"]; // maps with no base map: plain land
export const INK = ["#1d2329", "#ece7df"]; // outlines of the selected / hovered region, cell tracks
export const EDGE = ["#ffffff", "#151412"]; // thin okres borders and circle strokes: the gap between fills
export const KRAJE = ["#4b5863", "#b5ab9e"]; // kraj borders over the fills
export const NO_FILL = ["#ececec", "#2a2723"]; // okres fill before there is data

/** Pairs of the current theme, e.g. pick(INK) → "#1d2329" or "#ece7df". */
export function pick(pair, dark = isDark()) {
  return pair[dark ? 1 : 0];
}

/** The layers with the `dark` (default: current) values of `spec` set; light: unchanged. */
export function withTheme(layers, spec, dark = isDark()) {
  if (!dark) return layers;
  return layers.map((layer) => {
    const props = spec[layer.id];
    if (!props) return layer;
    const out = { ...layer, paint: { ...layer.paint } };
    if (layer.layout) out.layout = { ...layer.layout };
    for (const [key, pair] of Object.entries(props)) {
      if (key.startsWith("layout:")) (out.layout ??= {})[key.slice(7)] = pair[1];
      else out.paint[key] = pair[1];
    }
    return out;
  });
}

/** Switches `map` live with the page's theme button. Returns `apply(dark = isDark())`; call it
 * once the layers are added (layers that do not exist yet are skipped). */
export function themeMap(map, spec) {
  const apply = (dark = isDark()) => {
    for (const [id, props] of Object.entries(spec)) {
      if (!map.getLayer(id)) continue;
      for (const [key, pair] of Object.entries(props)) {
        const value = pair[dark ? 1 : 0];
        if (key.startsWith("layout:")) map.setLayoutProperty(id, key.slice(7), value);
        else map.setPaintProperty(id, key, value);
      }
    }
  };
  onThemeChange((dark) => apply(dark));
  return apply;
}
