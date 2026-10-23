// Helpers of the AI file's further variables (ai-model.js extraSeries) for the forecast detail page.

import { localDay } from "./forecast.js";
import { extraSeries } from "./ai-model.js";

// the combination's (MeteoVerdict) own hourly series, in the order the page offers them
const COMBINED_EXTRA = [
  ["relative_humidity_2m", "combined"], ["dew_point_2m", "combined"], ["pressure_msl", "combined"],
  ["wind_direction_10m", "combined"], ["wind_gusts_10m", "combined"], ["cloud_cover", "combined"],
  ["sunshine_duration", "combined"], ["cloud_cover_low", "reference"], ["shortwave_radiation", "reference"],
  ["visibility", "reference"], ["snowfall", "reference"], ["snow_depth", "reference"],
  ["snow_depth_water_equivalent", "reference"],
];
const UNITS = {
  relative_humidity_2m: "%", dew_point_2m: "°C", pressure_msl: "hPa", wind_direction_10m: "° (odkud)",
  wind_gusts_10m: "m/s", cloud_cover: "%", sunshine_duration: "min/h", cloud_cover_low: "%",
  shortwave_radiation: "W/m²", visibility: "km", snowfall: "cm", snow_depth: "cm", snow_depth_water_equivalent: "mm",
};
// model files give visibility in m, snow depth in m, sunshine in s per hour
const SCALE = { visibility: 0.001, snow_depth: 100, sunshine_duration: 1 / 60 };

/**
 * The further variables of one forecast as [{variable, source ("ai"|"combined"|"reference"), unit,
 * times: [ms], series}] in page order: MeteoVerdict AI's from its file (extraSeries, plus its
 * hourly cloud and sunshine), MeteoVerdict's from forecast/models (`combined`, then `reference`).
 * Empty for anything else (a single public model).
 */
export function extraFor(model, { ai, code, parsed }) {
  const scaled = (variable, values) => values.map((v) => (v == null ? null : Math.round(v * (SCALE[variable] ?? 1) * 100) / 100));
  const out = [];
  if (model === "mv_ai") {
    const own = ai?.okresy?.[code];
    if (!own) return out;
    for (const e of extraSeries(ai, code)) out.push({ variable: e.variable, source: e.source, unit: e.unit, times: own.times, series: e.values });
    for (const variable of ["cloud_cover", "sunshine_duration"]) {
      if (own[variable]?.some((v) => v != null)) {
        out.push({ variable, source: "ai", unit: UNITS[variable], times: own.times, series: scaled(variable, own[variable]) });
      }
    }
  } else if (model === "combined") {
    for (const [variable, source] of COMBINED_EXTRA) {
      const values = (source === "combined" ? parsed?.combined : parsed?.reference)?.[variable];
      if (values?.some((v) => v != null)) {
        out.push({ variable, source, unit: UNITS[variable], times: parsed.times, series: scaled(variable, values) });
      }
    }
  }
  return out;
}

/** Display series: fog probability 0–1 as %, and the snow variables only when any value is > 0. */
export function extraDisplay(series) {
  const out = [];
  for (const e of series) {
    const values = e.series ?? e.values;
    if (["snowfall", "snow_depth", "snow_depth_water_equivalent"].includes(e.variable) && !values.some((v) => v != null && v > 0)) continue;
    if (e.variable === "fog_probability") {
      out.push({ ...e, unit: "%", series: values.map((v) => (v == null ? null : Math.round(v * 1000) / 10)) });
    } else {
      out.push({ ...e, series: values });
    }
  }
  return out;
}

/**
 * The prevailing wind direction (° the wind blows from) of a local day: the vector mean of the
 * hourly directions weighted by the wind speed (calm hours, null, are skipped); null without any.
 */
export function dayWindDirection(extra, own, day, timeZone = "Europe/Prague") {
  const dir = extra?.find((e) => e.variable === "wind_direction_10m")?.series;
  if (!dir || !own?.times) return null;
  const speed = own.wind_speed_10m;
  let x = 0;
  let y = 0;
  let n = 0;
  own.times.forEach((time, i) => {
    const d = dir[i];
    if (d == null || localDay(time, timeZone) !== day) return;
    const w = speed?.[i] != null && speed[i] > 0 ? speed[i] : 1;
    x += w * Math.sin((d * Math.PI) / 180);
    y += w * Math.cos((d * Math.PI) / 180);
    n += 1;
  });
  if (!n || Math.hypot(x, y) < 1e-9) return null;
  return (Math.atan2(x, y) * 180 / Math.PI + 360) % 360;
}
