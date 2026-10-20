// The weather symbol of what was measured (an icon of icons.js): sky from the sunshine or
// the cloud cover, rain / sleet / snow from the precipitation. Pure helpers; the okres
// symbols of the Weather tab come from observed.js observedSymbol.

const DAY_MS = 86_400_000;
const toMs = (iso) => Date.parse(`${iso}T00:00:00Z`);

/** A day is wet from this much precipitation (mm). */
export const WET_MM = 0.5;
/** Sky from the sunshine as a share of the day's length: clear, partly cloudy, else cloudy. */
export const CLEAR_SUNSHINE = 0.6;
export const PARTLY_SUNSHINE = 0.25;
/** A wet day with at least this share of sunshine shows showers. */
export const SHOWERS_SUNSHINE = 0.3;
/** Sky from the daytime mean cloud cover (%), as the forecast symbols (models.js). */
export const CLEAR_BELOW = 30;
export const PARTLY_BELOW = 65;
/** Rain, sleet or snow from the temperature when no phenomenon says (models.js). */
export const SNOW_AT_OR_BELOW = 0.5;
export const SLEET_AT_OR_BELOW = 2;
// --- the observed symbol --------------------------------------------------------------
/** Hours from sunrise to sunset at a latitude on a day (the sun's centre 0.833° below
 * the horizon, as for the sunrise times). */
export function dayLength(lat, iso) {
  const start = Date.UTC(Number(iso.slice(0, 4)), 0, 1);
  const n = Math.round((toMs(iso) - start) / DAY_MS) + 1;
  const rad = Math.PI / 180;
  const declination = -23.44 * Math.cos(((2 * Math.PI) / 365) * (n + 10)) * rad;
  const phi = lat * rad;
  const cos = (Math.sin(-0.833 * rad) - Math.sin(phi) * Math.sin(declination)) / (Math.cos(phi) * Math.cos(declination));
  if (cos <= -1) return 24;
  if (cos >= 1) return 0;
  return (2 * Math.acos(cos)) / rad / 15;
}

/** How sunny the day was, 0 … 1, and from what: the sunshine hours as a share of the
 * day's length (or of `daylight`, the hours of daylight of a part of the day, when
 * given), else the daytime mean cloud cover (`row.cloud`, octas); null when the station
 * measures neither. */
export function sunniness(row, lat, daylight = null) {
  if (row.ssv != null && (lat != null || daylight != null)) {
    const hours = daylight ?? dayLength(lat, row.day);
    if (hours > 0) return { share: Math.min(1, row.ssv / hours), from: "sunshine" };
  }
  if (row.cloud != null) return { share: 1 - row.cloud / 8, from: "cloud" };
  return null;
}

/** Rain, sleet or snow: what the observer recorded (rain DE, snow SN, both: sleet), else
 * new snow on the ground, else the day's temperature. */
export function precipitationKind(row) {
  const rain = row.phenomena.includes("DE") || row.phenomena.includes("MS");
  const snow = row.phenomena.includes("SN");
  if (rain && snow) return "sleet";
  if (snow) return "snow";
  if (rain) return "rain";
  if ((row.sno ?? 0) >= 1) return "snow";
  const t = row.t ?? (row.tx != null && row.tn != null ? (row.tx + row.tn) / 2 : null);
  if (t != null && t <= SNOW_AT_OR_BELOW) return "snow";
  if (t != null && t <= SLEET_AT_OR_BELOW) return "sleet";
  return "rain";
}

/**
 * The weather symbol of an observed day (an icon of icons.js), honest about what was
 * measured: precipitation of at least WET_MM gives rain, sleet or snow (showers when the
 * sun shone for at least SHOWERS_SUNSHINE of the day as well); a dry day gets its sky
 * from the sunshine (or cloud cover); null when the station measures neither, or when it
 * measures no precipitation and the day had no sky observation. `daylight`: hours of
 * daylight of a part of the day (the observed map), instead of the day's length.
 */
export function daySymbol(row, lat, daylight = null) {
  const sky = sunniness(row, lat, daylight);
  if (row.r != null && row.r >= WET_MM) {
    const kind = precipitationKind(row);
    return kind === "rain" && sky && sky.share >= SHOWERS_SUNSHINE ? "showers" : kind;
  }
  if (!sky) return null;
  if (sky.from === "cloud") {
    const cloud = (1 - sky.share) * 100;
    return cloud < CLEAR_BELOW ? "clear" : cloud < PARTLY_BELOW ? "partly" : "cloudy";
  }
  return sky.share >= CLEAR_SUNSHINE ? "clear" : sky.share >= PARTLY_SUNSHINE ? "partly" : "cloudy";
}
