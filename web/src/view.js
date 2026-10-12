// What the map shows (variable, lead day, window) and how it is written in the URL.

// in the order of the selects; labels are in i18n.js ("variable.<key>", "window.<key>")
export const VARIABLES = [
  "temperature_2m",
  "temperature_2m_06utc",
  "temperature_2m_12utc",
  "temperature_max",
  "temperature_2m_hourly",
  "wind_speed_10m",
  "wind_speed_10m_hourly",
  "precipitation_24h",
  "precipitation_daily",
];

export const WINDOWS = ["90d", "season", "all", "djf", "mam", "jja", "son"];

export const DEFAULT_VIEW = { variable: "temperature_2m", leadDay: 1, window: "90d" };

/** "#temperature_2m/1/90d" → view; anything unknown falls back to the default */
export function parseHash(hash) {
  const [variable, lead, window] = hash.replace(/^#/, "").split("/");
  const leadDay = Number.parseInt(lead, 10);
  return {
    variable: VARIABLES.includes(variable) ? variable : DEFAULT_VIEW.variable,
    leadDay: leadDay >= 1 && leadDay <= 5 ? leadDay : DEFAULT_VIEW.leadDay,
    window: WINDOWS.includes(window) ? window : DEFAULT_VIEW.window,
  };
}

export function toHash(view) {
  return `#${view.variable}/${view.leadDay}/${view.window}`;
}

/** Variables offered: those meta.json lists (all, before the first scores exist). */
export function availableVariables(meta) {
  const listed = new Set(meta?.variables ?? VARIABLES);
  return VARIABLES.filter((v) => listed.has(v));
}

/** Lead days that have rows (D+1 if none). */
export function availableLeadDays(rows) {
  const days = [...new Set(rows.map((r) => r.lead_day))].sort((a, b) => a - b);
  return days.length ? days : [1];
}
