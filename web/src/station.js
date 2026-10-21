// Helpers of the Stations tab (station-page.js): the station search and number format.
import { displayName } from "./tv.js";

/** A number in the page's language ("1 600" in Czech, "1,600" in English); without a
 * language in English format, as the older pages. */
export function formatNumber(value, language = "en-US") {
  if (value == null || Number.isNaN(value)) return "–";
  return minus(new Intl.NumberFormat(language, { maximumFractionDigits: 2 }).format(value || 0));
}

// a true minus sign (−), as the rest of the site writes negative values
const minus = (text) => text.replace(/^-/, "−");

/** A value with fixed decimals in the page's language ("0,5" in Czech, "0.5" in English):
 * never "-0" (a value rounding to zero is 0), and a true minus sign. */
export function formatFixed(value, language, digits = 0) {
  if (value == null || Number.isNaN(value)) return "–";
  const rounded = Number(value.toFixed(digits)) || 0;
  return minus(rounded.toLocaleString(language, { minimumFractionDigits: digits, maximumFractionDigits: digits }));
}

/** A difference with its sign ("+1", "−0,5", "0"); empty without one. */
export function formatSigned(value, language, digits = 0) {
  if (value == null || Number.isNaN(value)) return "";
  const text = formatFixed(value, language, digits);
  return Number(value.toFixed(digits)) > 0 ? `+${text}` : text;
}

const fold = (s) => (s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Stations of the index whose name (or WSI) matches the query, without diacritics. The
 * best first: the exact name, then names starting with the query (those in the okres of
 * that name first: "praha" lists Praha's stations before "Praha, Brdy" in okres Příbram),
 * then a later word of the name starting with it, then the rest. */
export function searchStations(stations, query, limit = 20) {
  const q = fold(query).trim();
  if (!q) return [];
  const hits = stations.filter((s) => fold(s.name).includes(q) || s.id.includes(q));
  const rank = (s) => {
    const name = fold(s.name);
    if (name === q || s.id === q) return 0;
    if (name.startsWith(q)) return fold(displayName(s.okres ?? "")).startsWith(q) ? 1 : 2;
    return name.split(/[\s,.-]+/).some((word) => word.startsWith(q)) ? 3 : 4;
  };
  return hits
    .map((s) => ({ s, r: rank(s) }))
    .sort((a, b) => a.r - b.r || a.s.name.localeCompare(b.s.name, "cs"))
    .slice(0, limit)
    .map(({ s }) => s);
}
