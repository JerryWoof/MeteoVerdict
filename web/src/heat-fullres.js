// When the heatmap needs the full-resolution images (about 30 MB) instead of the coarse ones
// (about 2 MB). Pure functions; the page (heatmap-page.js) does the loading.

/** A coarse pixel wider than this many CSS pixels on screen looks blocky: the full images are worth it. */
export const COARSE_PIXEL_LIMIT = 1.5;
/** After the first picture, wait this long (ms) before the idle prefetch. */
export const IDLE_DELAY = 4000;

/**
 * The zoom (MapLibre, 512 px tiles) from which the coarse set's pixels are wider than `limit` CSS pixels:
 * the set covers its longitude span in `width` pixels. Infinity when the set is unusable.
 */
export function coarseZoomLimit(coarse, limit = COARSE_PIXEL_LIMIT) {
  const span = coarse?.bounds?.[2] - coarse?.bounds?.[0];
  if (!(span > 0) || !(coarse.width > 0)) return Infinity;
  const degreesPerPixel = span / coarse.width;
  // a degree of longitude is 512·2^zoom / 360 CSS pixels
  return Math.log2((limit * 360) / (512 * degreesPerPixel));
}

/** True when the connection asks for little data (Save-Data or 2G); `connection` is navigator.connection. */
export function isSlowConnection(connection) {
  if (!connection) return false;
  return connection.saveData === true || connection.effectiveType === "2g" || connection.effectiveType === "slow-2g";
}

/**
 * Whether to start loading the full images now. `reason`: "zoom" (the map's zoom is `zoom`), "point"
 * (a place was chosen: its panel wants the precise value), "idle" (nothing happened for a while).
 */
export function wantFullImages({ reason, zoom = 0, coarse, connection = null, haveFull = false }) {
  if (haveFull) return false;
  if (reason === "point") return true;
  if (reason === "zoom") return zoom >= coarseZoomLimit(coarse);
  if (reason === "idle") return !isSlowConnection(connection);
  return false;
}
