// The AI forecast tab below the map (data/scores/ai/ai.json, computed daily):
// MeteoVerdict AI against our blend (the combined forecast) per lead day since its launch, with the
// 95 % interval of the difference, the best public model only as context, and the cards of the
// experiments that work, that are not verified yet and that are still under evaluation.

const VARIABLES = ["temperature_2m", "wind_speed_10m"];
const UNITS = { temperature_2m: "°C", wind_speed_10m: "m/s" };
// the day MeteoVerdict AI went live: scores count from here on
const LAUNCH = "2026-10-19";

const lang = () => document.documentElement.lang;

function fmt(value, digits = 2) {
  return value == null || Number.isNaN(value)
    ? "–"
    : value.toLocaleString(lang(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function dateText(iso) {
  return new Intl.DateTimeFormat(lang(), { day: "numeric", month: "numeric", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
}

function cell(tag, text, className) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
}

/** How much smaller the AI's error is than the best public model's, in % (null: unknown); context only. */
export function improvement(row) {
  if (row.mae_ai == null || !row.mae_best) return null;
  return ((row.mae_best - row.mae_ai) / row.mae_best) * 100;
}

/** "+24 %", "−3 %" in the page's language. */
export function improvementText(p, language = "en") {
  if (p == null) return "–";
  const n = Math.round(p);
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toLocaleString(language)} %`;
}

/** The sections of the experiments, in order: status, section and box ids. */
export const SECTIONS = [
  ["works", "ai-exp-section", "ai-experiments"],
  ["unverified", "ai-unverified-section", "ai-unverified"],
  ["testing", "ai-testing-section", "ai-testing"],
];

/** The experiments of one status ("works", "unverified", "testing"), tables as published (our blend included). */
export function experimentsWith(experiments, status) {
  return (experiments ?? []).filter((e) => e.status === status);
}

/** "−0.11 [−0.15, −0.07]": the AI minus our blend with its 95 % interval ("–" when unknown). */
export function blendDiffText(row, language = "en") {
  if (row?.diff_blend == null) return "–";
  const f = (v) => {
    const s = Math.abs(v).toLocaleString(language, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}`;
  };
  const sep = language === "cs" ? "; " : ", ";
  return row.low_blend != null && row.high_blend != null
    ? `${f(row.diff_blend)} [${f(row.low_blend)}${sep}${f(row.high_blend)}]`
    : f(row.diff_blend);
}

/** "better" when the whole interval is below zero, "worse" above, else "tie". */
export function blendVerdict(row) {
  if (row?.high_blend != null && row.high_blend < 0) return "better";
  if (row?.low_blend != null && row.low_blend > 0) return "worse";
  return "tie";
}

function renderScores(doc, t, names) {
  const box = document.getElementById("ai-scores");
  const parts = [];
  for (const variable of VARIABLES) {
    const rows = doc.scores.filter((r) => r.variable === variable).sort((a, b) => a.lead_day - b.lead_day);
    if (!rows.length) continue;
    const unit = UNITS[variable];
    const table = cell("table", null, "data-table ai-score-table");
    const head = cell("tr");
    head.append(
      cell("th", t("ai.colLead")),
      cell("th", `${t("ai.colAi")} (${unit})`, "num"),
      cell("th", `${t("ai.colBlend")} (${unit})`, "num"),
      cell("th", t("ai.colDiff"), "num"),
      cell("th", `${t("ai.colBest")} (${unit})`),
    );
    table.append(head);
    for (const row of rows) {
      const verdict = blendVerdict(row);
      const best = cell("td", null, "ai-best");
      const name = row.best_model_name ?? names[row.best_model] ?? row.best_model;
      if (name) best.append(cell("span", name), " ");
      best.append(cell("b", fmt(row.mae_best)));
      const tr = cell("tr");
      tr.append(
        cell("td", `D+${row.lead_day}`),
        cell("td", fmt(row.mae_ai), "num"),
        cell("td", fmt(row.mae_blend), "num"),
        cell("td", blendDiffText(row, lang()), `num ai-gain${verdict === "tie" ? "" : ` ${verdict}`}`),
        best,
      );
      table.append(tr);
    }
    parts.push(cell("h3", t(`variable.${variable}`)), table);
  }
  box.replaceChildren(...parts);
  return parts.length > 0;
}

/** An experiment's own result table ({columns: [{key, cs, en}], rows}). */
function resultTable(table) {
  const el = cell("table", null, "data-table ai-result-table");
  const head = cell("tr");
  head.append(...table.columns.map((c) => cell("th", c[lang()] ?? c.en ?? c.key)));
  const rows = table.rows.map((row) => {
    const tr = cell("tr");
    const values = Array.isArray(row) ? row : table.columns.map((c) => row[c.key]);
    tr.append(
      ...values.map((v, i) => {
        const td = cell("td", typeof v === "number" ? fmt(v, Number.isInteger(v) ? 0 : 2) : String(v ?? "–"));
        // a phone shows each row as a list of "column: value" (style.css)
        const c = table.columns[i];
        td.dataset.label = c ? c[lang()] ?? c.en ?? c.key : "";
        return td;
      }),
    );
    return tr;
  });
  el.replaceChildren(head, ...rows);
  return el;
}

function renderExperiments(box, experiments, t) {
  box.replaceChildren(
    ...experiments.map((e) => {
      const card = cell("article", null, `ai-card ${e.status}`);
      const title = cell("h3");
      title.append(cell("span", t(`ai.exp.${e.id}.name`)), " ", cell("span", t(`ai.status.${e.status}`), `ai-status ${e.status}`));
      card.append(title, cell("p", t(`ai.exp.${e.id}.what`)));
      if (e.headline?.[lang()]) card.append(cell("p", e.headline[lang()], "ai-result"));
      if (e.table?.columns?.length && e.table.rows?.length) {
        card.append(resultTable(e.table));
        card.classList.add("wide");
      }
      if (e.tech) card.append(cell("p", t("ai.tech", { tech: e.tech }), "ai-tech"));
      return card;
    }),
  );
}

/** Fill the AI tab's sections below the map; each stays hidden without its data. */
export async function renderAiExtras(t, getJson) {
  const [doc, meta] = await Promise.all([getJson("data/scores/ai/ai.json"), getJson("data/scores/meta.json")]);
  if (!doc) return;
  // scored on live data since the launch; until the first measured days only a note
  const test = doc.test ?? {};
  const intro = document.getElementById("ai-score-intro");
  if (doc.scores?.length && renderScores(doc, t, { ...meta?.models })) {
    intro.textContent = t("ai.scoreIntro", {
      range: test.from && test.to ? `${dateText(test.from)}–${dateText(test.to)}` : "–",
      days: test.days ?? "–",
    });
  } else {
    document.getElementById("ai-scores").replaceChildren();
    intro.textContent = t("ai.scoreNone", { launch: dateText(doc.launch ?? test.from ?? LAUNCH) });
  }
  // the rule behind the labels ("works" only against our blend, with the whole interval below zero)
  const rule = document.getElementById("ai-score-rule");
  if (rule && doc.rule?.[lang()]) rule.textContent = doc.rule[lang()];
  document.getElementById("ai-score-section").hidden = false;
  for (const [status, section, box] of SECTIONS) {
    const shown = experimentsWith(doc.experiments, status);
    if (!shown.length) continue;
    renderExperiments(document.getElementById(box), shown, t);
    document.getElementById(section).hidden = false;
  }
}
