// "Find a place" on the radar page: every Czech municipality (obec) with its okres, from
// ČÚZK RÚIAN (CC BY 4.0), built by scripts/build_municipalities.py into data/obce.json:
// {"okresy": [name, ...], "obce": [[name, okres index, lat, lon, population], ...]}.

/** Lower case without diacritics: "Třeboň" → "trebon", "Ústí" → "usti". */
export function fold(text) {
  return String(text ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** "Třeboň (Jindřichův Hradec)". */
export const placeLabel = (place) => (place.okres ? `${place.name} (${place.okres})` : place.name);

/** The places of obce.json, or [] when the data are not what we expect. Rows that are
 * not a name, a known okres and a position in Czechia's surroundings are skipped. */
export function parsePlaces(data) {
  if (!data || !Array.isArray(data.okresy) || !Array.isArray(data.obce)) return [];
  const places = [];
  for (const row of data.obce) {
    if (!Array.isArray(row) || row.length < 4) continue;
    const [name, k, lat, lon, population] = row;
    const okres = data.okresy[k];
    if (typeof name !== "string" || !name || typeof okres !== "string") continue;
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 47 || lat > 52 || lon < 11 || lon > 20) continue;
    const key = fold(name);
    places.push({ name, okres, lat, lon, key, okresKey: fold(okres), population: Number.isFinite(population) ? population : 0 });
  }
  return places;
}

// a town this big whose name starts with what was typed counts as the whole name: "Ústí"
// means Ústí nad Labem rather than the village Ústí, "Hradec" Hradec Králové
const BIG_TOWN = 20000;

/**
 * Up to `limit` places for what was typed, diacritics and case ignored. Best first: the
 * whole name (and big towns starting with it), then names starting with it, then a word
 * of the name starting with it ("labem" finds "Ústí nad Labem"), then anywhere in the
 * name; bigger places first within a group, so "Třeb" + Enter is Třebíč, not a hamlet.
 * "Nová Ves Lit" narrows the many Nová Ves by the okres.
 */
export function searchPlaces(places, query, limit = 8) {
  const q = fold(query);
  if (!q) return [];
  const scored = [];
  for (const place of places) {
    let rank = rankOf(place.key, q);
    if (rank === 1 && place.population >= BIG_TOWN) rank = 0;
    if (rank == null) {
      // the end of the query may be the okres: "nova ves lito"
      for (let cut = q.lastIndexOf(" "); cut > 0; cut = q.lastIndexOf(" ", cut - 1)) {
        const head = rankOf(place.key, q.slice(0, cut));
        if (head != null && place.okresKey.startsWith(q.slice(cut + 1))) {
          rank = head + 0.5;
          break;
        }
      }
    }
    if (rank != null) scored.push({ place, rank });
  }
  scored.sort(
    (a, b) =>
      a.rank - b.rank ||
      b.place.population - a.place.population ||
      a.place.name.length - b.place.name.length ||
      a.place.name.localeCompare(b.place.name, "cs") ||
      a.place.okres.localeCompare(b.place.okres, "cs"),
  );
  return scored.slice(0, limit).map((s) => s.place);
}

function rankOf(key, q) {
  if (key === q) return 0;
  if (key.startsWith(q)) return 1;
  if (key.includes(` ${q}`) || key.includes(`-${q}`)) return 2;
  if (q.length >= 3 && key.includes(q)) return 3;
  return null;
}

/** Load the places once (later calls share the request); [] when it fails, and a later
 * call tries again. */
export function placesLoader(url, fetchImpl = (u) => fetch(u)) {
  let pending = null;
  async function load() {
    try {
      const response = await fetchImpl(url);
      return response.ok ? parsePlaces(await response.json()) : [];
    } catch {
      return [];
    }
  }
  return () => {
    pending ??= load().then((places) => {
      if (!places.length) pending = null;
      return places;
    });
    return pending;
  };
}
