// When the data are refreshed: the cron times (UTC) of the workflows that produce them,
// shown on the Data page in Prague time. schedule.test.js checks them against the
// workflow files, so this cannot drift from what actually runs.

/** Outlook (the forecast: outlook.yml, four runs a day) and Daily (the scores: daily.yml). */
export const SCHEDULE = {
  outlook: ["04:50", "10:50", "16:50", "22:50"],
  daily: ["05:17"],
};

/** "04:50" UTC on `date`'s day as clock time in Prague (CEST in summer, CET in winter). */
export function pragueClock(utc, date = new Date(), locale = "cs-CZ") {
  const [h, m] = utc.split(":").map(Number);
  const when = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), h, m));
  return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Prague", hourCycle: "h23" }).format(when);
}

export const pragueClocks = (times, date, locale) => times.map((t) => pragueClock(t, date, locale)).join(", ");
