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

// --- what each window covers: meta.json's `windows` {key: {from, to}} -----------------

/** months of the seasonal windows; their meta `from`/`to` span the whole history */
const SEASON_MONTHS = { djf: [12, 1, 2], mam: [3, 4, 5], jja: [6, 7, 8], son: [9, 10, 11] };
const DAY_MS = 86_400_000;
const parseDay = (iso) => new Date(`${iso}T00:00:00Z`);
const isoDay = (date) => date.toISOString().slice(0, 10);

/**
 * The days a window really covers: first and last day and how many (a seasonal window
 * only counts the days of its season). null if meta lists no such window or it is empty.
 */
export function windowSpan(key, windows) {
  const range = windows?.[key];
  if (!range?.from || !range?.to) return null;
  const months = SEASON_MONTHS[key];
  let from = null;
  let to = null;
  let days = 0;
  for (let t = parseDay(range.from).getTime(); t <= parseDay(range.to).getTime(); t += DAY_MS) {
    const day = new Date(t);
    if (months && !months.includes(day.getUTCMonth() + 1)) continue;
    from ??= isoDay(day);
    to = isoDay(day);
    days += 1;
  }
  return days ? { from, to, days } : null;
}

/**
 * Windows worth offering: those with at least one scored day in meta.json (all of them
 * before meta.json exists, so the select is never empty).
 */
export function availableWindows(windows) {
  if (!windows) return [...WINDOWS];
  const listed = WINDOWS.filter((key) => windowSpan(key, windows));
  return listed.length ? listed : [DEFAULT_VIEW.window];
}

/** The window to show: the asked-for one if it has data, else the default, else the first with data. */
export function pickWindow(current, available) {
  if (available.includes(current)) return current;
  return available.includes(DEFAULT_VIEW.window) ? DEFAULT_VIEW.window : available[0];
}

/**
 * The folder holding a window's score files: the Pages build leaves out a window with the
 * same days as an earlier one (e.g. "all" while the history is under 90 days) and names
 * it in meta.json's `aliases` ({"all": "90d"}).
 */
export function filesWindow(key, meta) {
  return meta?.aliases?.[key] ?? key;
}

/** True if the window covers exactly the days of the 90-day window (short history). */
export function sameAs90d(key, windows) {
  if (key === "90d") return false;
  const span = windowSpan(key, windows);
  const base = windowSpan("90d", windows);
  return Boolean(span && base) && span.from === base.from && span.to === base.to && span.days === base.days;
}

const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "23 Aug – 30 Sep 2026" / "23. 8. – 30. 9. 2026"; the year once if both share it. */
export function formatRange(from, to, language) {
  const parts = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return language === "cs" ? [`${d}. ${m}.`, ` ${y}`] : [`${d} ${MONTHS_EN[m - 1]}`, ` ${y}`];
  };
  const [a, ay] = parts(from);
  const [b, by] = parts(to);
  if (from === to) return b + by;
  return ay === by ? `${a} – ${b}${by}` : `${a}${ay} – ${b}${by}`;
}

/** "39 days" / "39 dní" (Czech: 1 den, 2–4 dny, 5+ dní) */
export function dayCount(days, t) {
  const form = days === 1 ? "one" : days >= 2 && days <= 4 ? "few" : "many";
  return t(`window.days.${form}`, { n: days });
}

/**
 * Option text of a window: name, real date range and days; marked when it covers the
 * same days as the 90-day window, or when it has no data yet.
 */
export function windowLabel(key, windows, t, language) {
  const name = t(`window.${key}`);
  const span = windowSpan(key, windows);
  if (!span) return t("window.empty", { name });
  const text = t("window.range", {
    name,
    range: formatRange(span.from, span.to, language),
    days: dayCount(span.days, t),
  });
  return sameAs90d(key, windows) ? `${text} · ${t("window.same90d")}` : text;
}
