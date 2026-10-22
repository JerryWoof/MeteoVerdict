// Text for the status line, from site/data/meta.json (written by `mvd aggregate`).

/**
 * @param {null | {generated?: string, as_of?: string}} meta
 * @param {(key: string, params?: object) => string} t
 */
export function statusText(meta, t) {
  if (!meta || !meta.as_of) return t("status.none");
  const updated = meta.generated ? meta.generated.slice(0, 10) : "?";
  return t("status.scores", { asOf: meta.as_of, updated });
}

/** Older than this (hours since the AI run) the heatmap's status line warns: "starší data". */
export const HEAT_STALE_HOURS = 30;

const EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Day and month of a time in Prague. */
function pragueDay(ms) {
  const parts = new Intl.DateTimeFormat("en-US", { day: "numeric", month: "numeric", timeZone: "Europe/Prague" }).formatToParts(ms);
  return { day: Number(parts.find((p) => p.type === "day").value), month: Number(parts.find((p) => p.type === "month").value) };
}

/** The days the map covers, "22.–26. 10." (cs) or "22–26 Oct" (en), across months too. */
function dayRange(from, to, language) {
  const a = pragueDay(from);
  const b = pragueDay(to);
  if (language === "cs") {
    // a word joiner after the dash keeps "21.–26." on one line
    return a.month === b.month ? `${a.day}.–\u2060${b.day}. ${a.month}.` : `${a.day}. ${a.month}.–\u2060${b.day}. ${b.month}.`;
  }
  return a.month === b.month
    ? `${a.day}–${b.day} ${EN_MONTHS[a.month - 1]}`
    : `${a.day} ${EN_MONTHS[a.month - 1]}–${b.day} ${EN_MONTHS[b.month - 1]}`;
}

/**
 * The status line of the heatmap: when the AI run was made (its `issued` time, Prague time) and the
 * days the map covers (its hours), with "starší data" when that run is older than HEAT_STALE_HOURS.
 * @param {null | {issued: number, hours: {time: number}[]}} index parsed heat index (ai-heat.js)
 * @param {(key: string, params?: object) => string} t
 * @param {"cs" | "en"} language
 * @returns {{text: string, stale: boolean}}
 */
export function heatStatus(index, t, language, now = Date.now()) {
  if (!index || !Number.isFinite(index.issued) || !index.hours?.length) return { text: "", stale: false };
  const issued = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", {
    day: "numeric", month: language === "cs" ? "numeric" : "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Europe/Prague",
  }).format(index.issued);
  const days = dayRange(index.hours[0].time, index.hours.at(-1).time, language);
  const stale = now - index.issued > HEAT_STALE_HOURS * 3600e3;
  const text = t("status.heat", { issued, days });
  return { text: stale ? `${text} · ${t("status.stale")}` : text, stale };
}
