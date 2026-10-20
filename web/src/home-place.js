// The home page's "forecast for my place": a place (search or position) → the detailed
// forecast of its okres, at the obec nearest to it. Pure helpers; home-search.js does the I/O.

/** The outlook's okres for a place of obce.json (ČÚZK names Prague's okres the city). */
export function okresOf(place, okresy) {
  return (
    okresy.find((o) => o.name === place.okres) ??
    (place.okres === "Hlavní město Praha" ? okresy.find((o) => o.code === "CZ0100") : null) ??
    null
  );
}

/** The place of `places` nearest to a position (flat-earth distance, fine within Czechia). */
export function nearestPlace(places, lat, lon) {
  let best = null;
  let distance = Infinity;
  const scale = Math.cos((lat * Math.PI) / 180);
  for (const place of places) {
    const d = (place.lat - lat) ** 2 + ((place.lon - lon) * scale) ** 2;
    if (d < distance) [best, distance] = [place, d];
  }
  return best;
}

/** The forecast page's map with an okres and an obec in it selected (panel open). */
export const forecastLink = (code, obec) =>
  `forecast.html#${code}${obec ? `/${encodeURIComponent(obec)}` : ""}`;
