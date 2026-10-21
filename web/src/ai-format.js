// Numbers, dates and backend texts of the AI tab (ai-extras.js, ai-verify-view.js) in the
// page's language. data/scores/ai/ai.json now carries the card texts finished per language
// (`texts.cs` / `texts.en`, see experimentTexts); an older ai.json has only English number
// formats, ISO dates and some "cs / en" labels, and these helpers turn what can be parsed
// safely into the page's language and leave anything else as it came.

const MINUS = "−";

/** "1,23" / "1.23" with fixed decimals, a real minus and never "−0,00" ("–" when unknown). */
export function numText(value, digits = 2, language = "en") {
  if (value == null || !Number.isFinite(value)) return "–";
  const factor = 10 ** digits;
  const rounded = Math.round(Math.abs(value) * factor) / factor;
  const text = rounded.toLocaleString(language, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return value < 0 && rounded !== 0 ? `${MINUS}${text}` : text;
}

/** Like numText, with "+" in front of a positive value (a difference). */
export function signedText(value, digits = 2, language = "en") {
  const text = numText(value, digits, language);
  return value > 0 && Math.round(value * 10 ** digits) !== 0 ? `+${text}` : text;
}

// day and month as in the rest of the site's sentences ("19. října", "19 October"): a date
// ending in a period ("19. 10.") would double the period at the end of a sentence
const dayMonth = (language) =>
  new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { day: "numeric", month: "long", timeZone: "UTC" });

const isoDate = (iso) => new Date(`${iso}T00:00:00Z`);

/** "2026-10-19" → "19. října" / "19 October". */
export function dateText(iso, language = "en") {
  return dayMonth(language).format(isoDate(iso));
}

/** "19.–21. října" / "19–21 October" (a single date when both are the same day). */
export function dateRangeText(from, to, language = "en") {
  if (!to || from === to) return dateText(from, language);
  // by hand: Intl's formatRange falls back to "19.–21. 10." in Czech in some engines
  if (from.slice(0, 7) === to.slice(0, 7)) {
    const day = Number(from.slice(8, 10));
    return `${day}${language === "cs" ? "." : ""}–${dateText(to, language)}`;
  }
  return `${dateText(from, language)} – ${dateText(to, language)}`;
}

/** The page's half of a "Teplota / Temperature" label; anything else as it is. */
export function pickLang(text, language = "en") {
  if (typeof text !== "string") return text;
  const parts = text.split(" / ");
  // exactly one separator and no numbers: a label pair, not "0.11°/0.25°" or a ratio
  if (parts.length !== 2 || /\d/.test(text) || !parts[0] || !parts[1]) return text;
  return language === "cs" ? parts[0] : parts[1];
}

const NUM = String.raw`[+-]?\d+(?:\.\d+)?`;
const INTERVAL = new RegExp(String.raw`^(${NUM}) \[(${NUM}), (${NUM})\]$`);
const NAMED_VALUE = new RegExp(String.raw`^(.+) (${NUM})$`);
const NAMED_WORST = new RegExp(String.raw`^(.+) (${NUM}) (°C|m/s|mm) \(worst (${NUM}), (.+)\)$`);

/** "−0,07 [−0,10; −0,03]" from the engine's "-0.07 [-0.10, -0.03]" (null: not that shape). */
export function intervalText(text, language = "en") {
  const m = INTERVAL.exec(text);
  if (!m) return null;
  const [diff, low, high] = m.slice(1).map(Number);
  const sep = language === "cs" ? "; " : ", ";
  return `${signedText(diff, 2, language)} [${signedText(low, 2, language)}${sep}${signedText(high, 2, language)}]`;
}

/**
 * One cell of an experiment's table: a number with the column's decimals, a "cs / en" pair
 * as one language, a raw key through `translate` (null: unknown), the engine's "-0.07 [...]"
 * and "Model 1.195" / "Model 1.06 °C (worst 1.63, Other)" texts re-formatted; else as it is.
 */
export function cellText(value, { digits = 2, language = "en", translate = () => null, worst = "worst" } = {}) {
  if (value == null) return "–";
  if (typeof value === "number") return numText(value, digits, language);
  const text = String(value);
  const known = translate(text);
  if (known) return known;
  const interval = intervalText(text, language);
  if (interval) return interval;
  let m = NAMED_WORST.exec(text);
  if (m) return `${m[1]} ${numText(Number(m[2]), 2, language)} ${m[3]} (${worst} ${numText(Number(m[4]), 2, language)}, ${m[5]})`;
  // a model's name and its error; a name ending in a whole number of its own ("ICON 13") stays
  m = NAMED_VALUE.exec(text);
  if (m && m[2].includes(".")) return `${m[1]} ${numText(Number(m[2]), 2, language)}`;
  return pickLang(text, language);
}

/** The decimals of a table column: none when every number in it is whole (counts), else 2. */
export function columnDigits(values) {
  const numbers = values.filter((v) => typeof v === "number" && Number.isFinite(v));
  return numbers.length && numbers.every(Number.isInteger) ? 0 : 2;
}

/**
 * A sentence from the engine in the page's language where that is safe: ISO dates and date
 * ranges as dates, a real minus before numbers, "3–5" for ranges and, in Czech, decimal commas
 * and "; " inside intervals. Numbers that belong to a model's name ("0.25°", "2.3 km") stay.
 */
export function proseText(text, language = "en") {
  if (typeof text !== "string") return text;
  const DATE = String.raw`(\d{4}-\d{2}-\d{2})`;
  let out = text
    .replace(new RegExp(String.raw`${DATE}\s*(?:…|\.\.\.|–| až | to )\s*${DATE}`, "g"), (_, a, b) => dateRangeText(a, b, language))
    .replace(new RegExp(DATE, "g"), (_, a) => dateText(a, language))
    .replace(/(^|[\s([])-(?=\d)/g, `$1${MINUS}`)
    .replace(/(^|[\s(])(\d+)-(\d+)(?=[\s)]| day)/g, "$1$2–$3");
  if (language === "cs") {
    out = out
      .replace(/\[([−+]?\d+(?:\.\d+)?), ([−+]?\d+(?:\.\d+)?)\]/g, "[$1; $2]")
      .replace(/(\d)\.(\d+)(?!\d|°| ?km\b)/g, "$1,$2");
  }
  return out;
}

/** A dict row's value for a column: the raw value first ("temperature_2m" via `translate`), then the language's twin ("regime_cs"), then the column's own. */
function rowValue(row, key, language, translate) {
  const base = key.replace(/_(cs|en)$/, "");
  return translate(row[base]) ?? row[`${base}_${language}`] ?? row[key];
}

/**
 * An old-style experiment table ({columns: [{key, cs, en}], rows as arrays or dicts}) as
 * finished strings in `language`: {columns, rows, numeric}, the shape the engine now writes
 * itself (`texts.<lang>.table`); `numeric` marks the columns of numbers. Null without rows.
 */
export function tableTexts(table, { language = "en", translate = () => null, worst = "worst" } = {}) {
  if (!table?.columns?.length || !table.rows?.length) return null;
  // the engine writes "AI - blend": a minus, not a hyphen
  const columns = table.columns.map((c) => (c[language] ?? c.en ?? c.key).replace(/ - /g, " − "));
  const raw = table.rows.map((row) =>
    Array.isArray(row) ? row : table.columns.map((c) => rowValue(row, c.key, language, translate)),
  );
  // the same decimals down a column: "2,00" next to "1,75", whole counts without any
  const digits = table.columns.map((_, i) => columnDigits(raw.map((r) => r[i])));
  return {
    columns,
    rows: raw.map((values) => values.map((v, i) => cellText(v, { digits: digits[i], language, translate, worst }))),
    numeric: table.columns.map((_, i) => raw.some((r) => typeof r[i] === "number")),
  };
}

/** The engine's finished table when it has the right shape (else null: format the old one). */
function finishedTable(table) {
  const ok =
    Array.isArray(table?.columns) &&
    Array.isArray(table.rows) &&
    table.rows.length > 0 &&
    table.rows.every((r) => Array.isArray(r) && r.length === table.columns.length);
  return ok ? { ...table, numeric: Array.isArray(table.numeric) ? table.numeric : table.columns.map(() => false) } : null;
}

/**
 * An experiment card's headline, technology line and table in `language`: the engine's
 * finished `texts[language]` where it wrote them, else the old fields formatted here
 * (`tech` is then null: the caller has its own wording). Missing parts are null.
 */
export function experimentTexts(e, { language = "en", translate = () => null, worst = "worst" } = {}) {
  const own = e?.texts?.[language] ?? {};
  const headline = e?.headline?.[language];
  return {
    headline: typeof own.headline === "string" ? own.headline : headline ? proseText(headline, language) : null,
    tech: typeof own.tech === "string" ? own.tech : null,
    table: finishedTable(own.table) ?? tableTexts(e?.table, { language, translate, worst }),
  };
}

/** The rule behind the labels in `language`: the engine's finished text, else the old one formatted here. */
export function ruleText(doc, language = "en") {
  const own = doc?.texts?.[language]?.rule;
  if (typeof own === "string") return own;
  return doc?.rule?.[language] ? proseText(doc.rule[language], language) : null;
}
