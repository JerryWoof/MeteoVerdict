// When the data are refreshed (UTC), shown on the Data page in Prague time.
// schedule.test.js checks daily, runs and chmi against the workflow files.

/** Outlook (the forecast, four times a day), Daily (the scores: daily.yml) and the other
 * schedules shown on the Data page. */
export const SCHEDULE = {
  outlook: ["04:50", "10:50", "16:50", "22:50"],
  daily: ["05:17"],
  runs: ["04:20", "10:20", "16:20", "22:20"], // single runs (runs.yml)
  chmi: ["01:41", "13:41"], // ČHMÚ station archive (chmi-archive.yml)
  sun: ["04:05"], // sunshine, cloud and gust corrections
};

/** "04:50" UTC on `date`'s day as clock time in Prague (CEST in summer, CET in winter). */
export function pragueClock(utc, date = new Date(), locale = "cs-CZ") {
  const [h, m] = utc.split(":").map(Number);
  const when = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), h, m));
  return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Prague", hourCycle: "h23" }).format(when);
}

export const pragueClocks = (times, date, locale) => times.map((t) => pragueClock(t, date, locale)).join(", ");
