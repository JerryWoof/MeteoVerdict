// How accurate is the obec forecast where there is no station? The leave-one-station-out
// test (`mvd obce-loso`, data/scores/obce-loso.json; docs/methodology.md) on the
// methodology page: the key numbers come from the file, none is written into the text.

export const FILE = "data/scores/obce-loso.json";
export const ANCHOR = "obce-loso";
const VARIABLES = ["temperature_2m", "wind_speed_10m", "precipitation_daily"];

/** The group rows of the station-held-out variant as objects. */
function rows(doc) {
  const columns = doc?.groups?.columns ?? [];
  return (doc?.groups?.rows ?? [])
    .map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i]])))
    .filter((r) => r.variant === "loso");
}

// obec minus another series with its 95 % interval, or null where the file has none
function diff(row, series) {
  if (!row || row[`diff_${series}`] == null) return null;
  return { diff: row[`diff_${series}`], low: row[`low_${series}`], high: row[`high_${series}`] };
}

/**
 * The key numbers per variable: MAE over D+1–5 (and at D+1), obec minus the okres
 * forecast and minus the plain median of the models, the same at the mountain stations,
 * and minus the obec forecast with the corrections at the okres point (before
 * 20 Oct 2026) where the file has it. Null without a usable file.
 */
export function losoSummary(doc) {
  const all = rows(doc);
  const find = (variable, lead, stratum, value) =>
    all.find((r) => r.variable === variable && r.lead_day === lead && r.stratum === stratum && r.value === value) ?? null;
  const variables = VARIABLES.map((variable) => {
    const row = find(variable, "all", "all", "all");
    const mountain = find(variable, "all", "elevation_class", "mountain");
    return row && {
      variable,
      unit: doc.units?.[variable] ?? "",
      stations: row.stations,
      mae: row.mae_obec,
      maeD1: find(variable, "1", "all", "all")?.mae_obec ?? null,
      okres: diff(row, "okres"),
      median: diff(row, "median"),
      point: diff(row, "obec_point"),
      mountain: mountain && { stations: mountain.stations, median: diff(mountain, "median") },
    };
  }).filter(Boolean);
  if (!variables.length) return null;
  return {
    from: doc.from,
    to: doc.to,
    days: doc.test_days,
    stations: Object.keys(doc.names ?? {}).length,
    variables,
  };
}

/** Whether a difference's interval excludes zero. */
export function significant(d) {
  return d != null && d.low != null && d.high != null && (d.low > 0 || d.high < 0);
}

function number(value, language, digits) {
  const text = Math.abs(value).toLocaleString(language === "cs" ? "cs-CZ" : "en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return value < 0 && Number(text.replace(",", ".")) !== 0 ? `−${text}` : text;
}

/** "−0.29 (−0.38 to −0.20)", bold where the interval excludes zero. */
export function diffText(d, language, t, digits = 2) {
  if (!d) return "–";
  const signed = (v) => (v > 0 ? `+${number(v, language, digits)}` : number(v, language, digits));
  const text = t("obceLoso.diff", { diff: signed(d.diff), low: signed(d.low), high: signed(d.high) });
  return significant(d) ? `**${text}**` : text;
}

function dateText(iso, language) {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString(language === "cs" ? "cs-CZ" : "en-GB", {
    day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}

/** The section's blocks (info-page.js `renderBlocks`), or a short note without a file. */
export function losoBlocks(summary, language, t) {
  const heading = ["h", t("obceLoso.title")];
  if (!summary) return [heading, ["note", t("obceLoso.missing")]];
  const name = (v) => t(`obceLoso.var.${v.variable}`);
  const mae = (value, v) => (value == null ? "–" : `${number(value, language, 2)} ${v.unit}`);
  const blocks = [
    heading,
    ["p", t("obceLoso.intro", {
      from: dateText(summary.from, language), to: dateText(summary.to, language),
      days: summary.days, stations: summary.stations,
    })],
    ["table", {
      head: [t("obceLoso.head.variable"), t("obceLoso.head.mae"), t("obceLoso.head.okres"), t("obceLoso.head.median"), t("obceLoso.head.mountain")],
      rows: summary.variables.map((v) => [
        `${name(v)} (${t("obceLoso.stations", { n: v.stations })})`,
        mae(v.mae, v),
        diffText(v.okres, language, t),
        diffText(v.median, language, t),
        v.mountain ? diffText(v.mountain.median, language, t) : "–",
      ]),
    }],
    ["p", t("obceLoso.reading")],
  ];
  // the caveat: where the obec forecast loses to the plain median in the mountains
  const worse = summary.variables.filter((v) => significant(v.mountain?.median) && v.mountain.median.diff > 0);
  if (worse.length) {
    const item = (v) =>
      `${name(v).toLowerCase()} +${number(v.mountain.median.diff, language, 2)} ${v.unit} (${t("obceLoso.stations", { n: v.mountain.stations })})`;
    blocks.push(["p", t("obceLoso.mountain", { list: worse.map(item).join(", ") })]);
  }
  const point = summary.variables.find((v) => v.variable === "temperature_2m")?.point;
  if (point) blocks.push(["p", t("obceLoso.height", { diff: diffText(point, language, t, 3) })]);
  blocks.push(["note", t("obceLoso.limits")]);
  return blocks;
}
