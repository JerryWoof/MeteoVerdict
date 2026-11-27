// Helpers of the heatmap page (heatmap.html): temperature text, the nearest village and the pixel
// of an image under a point. (The older day-part maps and the single 100 m image are gone.)

/** "2,9 °C" (cs) / "2.9 °C" (en). */
export function temp100mFormat(value, language, unit = "°C") {
  return `${new Intl.NumberFormat(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value)} ${unit}`;
}

/** The place of `places` ({lat, lon, ...}) nearest to lat/lon with its distance in km, or null. */
export function nearestPlaceOf(places, lat, lon) {
  const cos = Math.cos((lat * Math.PI) / 180);
  let best = null;
  let bestD = Infinity;
  for (const place of places) {
    const dy = place.lat - lat;
    const dx = (place.lon - lon) * cos;
    const d = dx * dx + dy * dy;
    if (d < bestD) { bestD = d; best = place; }
  }
  return best ? { place: best, km: Math.sqrt(bestD) * 111.2 } : null;
}

// --- the pixel under the pointer ---------------------------------------------------------

const mercatorY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

/**
 * The image pixel {x, y} under lng/lat for an image of `width` x `height` covering `bounds`
 * [west, south, east, north] (x linear in longitude, y linear in Web-Mercator Y), or null
 * outside the image.
 */
export function temp100mPixel(lng, lat, bounds, width, height) {
  const [west, south, east, north] = bounds;
  if (!(lng >= west && lng <= east && lat >= south && lat <= north)) return null;
  const yTop = mercatorY(north);
  const x = Math.min(width - 1, Math.floor(((lng - west) / (east - west)) * width));
  const y = Math.min(height - 1, Math.floor(((yTop - mercatorY(lat)) / (yTop - mercatorY(south))) * height));
  return { x, y };
}
