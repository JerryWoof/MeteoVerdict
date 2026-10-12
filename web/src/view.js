// What the map shows (variable, lead day, window) and how it is written in the URL.

export const VARIABLES = {
  temperature_2m: "Temperature (2 m), hourly",
  temperature_2m_06utc: "Temperature at 06 UTC (night)",
  temperature_2m_12utc: "Temperature at 12 UTC (afternoon)",
  temperature_max: "Daily maximum temperature",
  wind_speed_10m: "Wind (10 m)",
  precipitation_24h: "Precipitation, 24 h (06-06 UTC, with rain gauges)",
  precipitation_daily: "Precipitation, UTC day",
};

export const WINDOWS = {
  "90d": "Last 90 days",
  season: "This season",
  all: "All time",
  djf: "All winters",
  mam: "All springs",
  jja: "All summers",
  son: "All autumns",
};

export const DEFAULT_VIEW = { variable: "temperature_2m", leadDay: 1, window: "90d" };

/** "#temperature_2m/1/90d" → view; anything unknown falls back to the default */
export function parseHash(hash) {
  const [variable, lead, window] = hash.replace(/^#/, "").split("/");
  const leadDay = Number.parseInt(lead, 10);
  return {
    variable: variable in VARIABLES ? variable : DEFAULT_VIEW.variable,
    leadDay: leadDay >= 1 && leadDay <= 5 ? leadDay : DEFAULT_VIEW.leadDay,
    window: window in WINDOWS ? window : DEFAULT_VIEW.window,
  };
}

export function toHash(view) {
  return `#${view.variable}/${view.leadDay}/${view.window}`;
}

/** Variables offered: those meta.json lists (all, before the first scores exist). */
export function availableVariables(meta) {
  const listed = new Set(meta?.variables ?? Object.keys(VARIABLES));
  return Object.keys(VARIABLES).filter((v) => listed.has(v));
}

/** Lead days that have rows (D+1 if none). */
export function availableLeadDays(rows) {
  const days = [...new Set(rows.map((r) => r.lead_day))].sort((a, b) => a - b);
  return days.length ? days : [1];
}
