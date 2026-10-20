// Helpers of the Stations tab (station-page.js): the station search and number format.

/** Numbers always in English format (decimal point), as on the other pages. */
const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
export function formatNumber(value) {
  return value == null || Number.isNaN(value) ? "–" : NUMBER.format(value);
}

const fold = (s) => (s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Stations of the index whose name (or WSI) matches the query, without diacritics;
 * names starting with the query first. */
export function searchStations(stations, query, limit = 20) {
  const q = fold(query).trim();
  if (!q) return [];
  const hits = stations.filter((s) => fold(s.name).includes(q) || s.id.includes(q));
  const starts = (s) => (fold(s.name).startsWith(q) ? 0 : 1);
  return hits
    .sort((a, b) => starts(a) - starts(b) || a.name.localeCompare(b.name, "cs"))
    .slice(0, limit);
}
