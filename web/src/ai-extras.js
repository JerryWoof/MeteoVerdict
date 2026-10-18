// The AI forecast tab below the map (data/scores/ai/ai.json, computed daily on the DGX
// Spark): MeteoVerdict AI against the best public model per lead day, and the cards of
// the experiments that work and of those still under evaluation. Nothing here compares with our combined forecast.

const VARIABLES = ["temperature_2m", "wind_speed_10m"];
const UNITS = { temperature_2m: "°C", wind_speed_10m: "m/s" };

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

/** How much smaller the AI's error is than the best public model's, in % (null: unknown). */
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

/** The experiments of one status ("works", "testing"), without columns about our combination. */
export function experimentsWith(experiments, status) {
  return (experiments ?? [])
    .filter((e) => e.status === status)
    .map((e) => {
      if (!e.table?.columns) return e;
      const keep = e.table.columns.map((c) => !/combined/i.test(`${c.key} ${c.en ?? ""}`));
      return {
        ...e,
        table: {
          columns: e.table.columns.filter((_, i) => keep[i]),
          rows: (e.table.rows ?? []).map((row) => (Array.isArray(row) ? row.filter((_, i) => keep[i]) : row)),
        },
      };
    });
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
      cell("th", `${t("ai.colBest")} (${unit})`),
      cell("th", t("ai.colGain"), "num"),
    );
    table.append(head);
    for (const row of rows) {
      const gain = improvement(row);
      const best = cell("td", null, "ai-best");
      const name = row.best_model_name ?? names[row.best_model] ?? row.best_model;
      if (name) best.append(cell("span", name), " ");
      best.append(cell("b", fmt(row.mae_best)));
      const tr = cell("tr");
      tr.append(
        cell("td", `D+${row.lead_day}`),
        cell("td", fmt(row.mae_ai), "num"),
        best,
        cell("td", improvementText(gain, lang()), `num ai-gain${gain > 0 ? " better" : gain < 0 ? " worse" : ""}`),
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
  if (doc.scores?.length && renderScores(doc, t, { ...meta?.models })) {
    const test = doc.test ?? {};
    document.getElementById("ai-score-intro").textContent = t("ai.scoreIntro", {
      range: test.from && test.to ? `${dateText(test.from)}–${dateText(test.to)}` : "–",
      days: test.days ?? "–",
    });
    document.getElementById("ai-score-section").hidden = false;
  }
  for (const [status, section, box] of [["works", "ai-exp-section", "ai-experiments"], ["testing", "ai-testing-section", "ai-testing"]]) {
    const shown = experimentsWith(doc.experiments, status);
    if (!shown.length) continue;
    renderExperiments(document.getElementById(box), shown, t);
    document.getElementById(section).hidden = false;
  }
}
