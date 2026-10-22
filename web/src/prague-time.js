// Every time on the site is Prague's clock time (CET in winter, CEST in summer). Texts that
// name a fixed UTC hour (model runs, ČHMÚ's climate day) write it as "{@06}", the UTC hour,
// and get today's Prague hour for it ("7" in winter, "8" in summer).
const HOUR = new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: "Europe/Prague" });

/** Prague's clock hour of `utcHour` UTC on `when`'s day. */
export function pragueHour(utcHour, when = new Date()) {
  const at = new Date(Date.UTC(when.getUTCFullYear(), when.getUTCMonth(), when.getUTCDate(), utcHour));
  return Number(HOUR.format(at));
}

/** `text` with every "{@HH}" replaced by Prague's hour of HH UTC on `when`'s day. */
export function pragueClock(text, when = new Date()) {
  return text.replace(/\{@(\d{1,2})\}/g, (_, hour) => String(pragueHour(Number(hour), when)));
}
