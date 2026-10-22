// Helpers of the AI file's further variables (ai-model.js extraSeries) for the forecast detail page.

import { localDay } from "./forecast.js";

/** Display series: fog probability 0–1 as %, and the snow variables only when any value is > 0. */
export function extraDisplay(series) {
  const out = [];
  for (const e of series) {
    if (["snowfall", "snow_depth", "snow_depth_water_equivalent"].includes(e.variable) && !e.values.some((v) => v != null && v > 0)) continue;
    if (e.variable === "fog_probability") {
      out.push({ ...e, unit: "%", series: e.values.map((v) => (v == null ? null : Math.round(v * 1000) / 10)) });
    } else {
      out.push({ ...e, series: e.values });
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
