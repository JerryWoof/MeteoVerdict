// "Forecast for my place": a place (search or position) → the detailed forecast of its okres,
// at the obec nearest to it. Pure helpers; the radar page uses locateErrorKey.

/** The outlook's okres for a place of obce.json (ČÚZK names Prague's okres the city). */
export function okresOf(place, okresy) {
  return (
    okresy.find((o) => o.name === place.okres) ??
    (place.okres === "Hlavní město Praha" ? okresy.find((o) => o.code === "CZ0100") : null) ??
    null
  );
}

// farther than this from every obec the position is not in Czechia (no point in Czechia is
// more than about 5 km from an obec's centre), and its nearest obec would be a wrong answer
export const OUTSIDE_KM = 30;

/** The place of `places` nearest to a position (flat-earth distance, fine within Czechia);
 * null when none is within `maxKm`. */
export function nearestPlace(places, lat, lon, maxKm = Infinity) {
  let best = null;
  let distance = Infinity;
  const scale = Math.cos((lat * Math.PI) / 180);
  for (const place of places) {
    const d = (place.lat - lat) ** 2 + ((place.lon - lon) * scale) ** 2;
    if (d < distance) [best, distance] = [place, d];
  }
  return Math.sqrt(distance) * 111.2 <= maxKm ? best : null;
}

/** Our own sentence for a failed geolocation: the browser's message is English (and
 * technical) whatever the page's language. */
export function locateErrorKey(error) {
  if (error?.code === 1) return "locate.denied";
  if (error?.code === 3) return "locate.timeout";
  return "locate.unavailable";
}

/** The forecast page's map with an okres and an obec in it selected (panel open). */
export const forecastLink = (code, obec) =>
  `forecast.html#${code}${obec ? `/${encodeURIComponent(obec)}` : ""}`;
