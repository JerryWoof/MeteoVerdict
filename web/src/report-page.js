// The monthly accuracy report: reports/index.json lists the months, reports/YYYY-MM.json
// holds one (`mvd monthly-report`). Bars are plain HTML so that they print and read well.
import "./style.css";

import { setUpLanguage } from "./i18n.js";
import { VARIABLES, barRows, leadsOf, meanVerdict, monthLabel, winnerKind } from "./report.js";

const t = setUpLanguage();
const language = document.documentElement.lang;
const number = (value, digits = 2) =>
  new Intl.NumberFormat(language === "cs" ? "cs-CZ" : "en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function el(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

function headline(report, variable) {
  const lead = report.variables[variable]?.leads?.["1"];
  const unit = report.variables[variable]?.unit ?? "";
  const label = t(`report.var.${variable}`);
  const kind = winnerKind(lead);
  const li = el("li");
  if (kind === "none") {
    li.textContent = t("report.none", { variable: label });
    return li;
  }
  const best = lead.models.find((m) => m.model === lead.best);
  li.textContent = t(kind === "clear" ? "report.clear" : "report.tie", {
    variable: label, model: best.name, mae: number(best.mae), unit, n: lead.tied_with_best.length,
  });
  const verdict = meanVerdict(lead);
  if (verdict) {
    li.append(el("br"), el("span", t(`report.mean.${verdict}`, { mae: number(lead.mean_of_all.mae), unit }), "sub"));
  }
  return li;
}

function chart(report, variable, leadKey) {
  const lead = report.variables[variable]?.leads?.[leadKey];
  const section = el("section", null, "report-chart");
  section.append(el("h3", `${t(`report.var.${variable}`)}: ${t("report.chart", { lead: leadKey })}`));
  const unit = report.variables[variable]?.unit ?? "";
  const rows = barRows(lead);
  if (!rows.length) {
    section.append(el("p", t("report.none", { variable: t(`report.var.${variable}`) })));
    return section;
  }
  const list = el("ol", null, "bars");
  for (const row of rows) {
    const item = el("li", null, row.best ? "best" : row.tied ? "tied" : "");
    const bar = el("span", null, "bar");
    bar.style.width = `${Math.max(2, row.share * 100).toFixed(1)}%`;
    const name = el("span", row.tied ? `≈ ${row.name}` : row.name, "name");
    const value = el("span", `${number(row.mae)} ${unit} / ${row.bias > 0 ? "+" : ""}${number(row.bias)}`, "value");
    item.append(name, el("span", null, "track"), value);
    item.querySelector(".track").append(bar);
    list.append(item);
  }
  section.append(list);
  return section;
}

function wins(report, variable, leadKey) {
  const data = report.wins?.[`${variable}/${leadKey}`];
  const section = el("section", null, "report-chart");
  section.append(el("h3", t(`report.var.${variable}`)));
  if (!data?.models?.length) {
    section.append(el("p", "–"));
    return section;
  }
  const top = Math.max(...data.models.map((m) => m.okresy));
  const list = el("ol", null, "bars");
  for (const m of data.models) {
    const item = el("li");
    const bar = el("span", null, "bar");
    bar.style.width = `${Math.max(2, (m.okresy / top) * 100).toFixed(1)}%`;
    const track = el("span", null, "track");
    track.append(bar);
    item.append(el("span", m.name, "name"), track, el("span", t("report.winsRow", { n: m.okresy, clear: m.clear }), "value"));
    list.append(item);
  }
  section.append(list);
  return section;
}

function render(report) {
  const label = monthLabel(report.month, language);
  document.title = `MeteoVerdict: ${t("report.title", { month: label })}`;
  document.getElementById("report-title").textContent = t("report.title", { month: label });
  document.getElementById("report-intro").textContent = t("report.intro", { month: label });
  const temperature = report.variables.temperature_2m.leads["1"];
  const models = new Set(Object.values(report.variables).flatMap((v) => Object.values(v.leads).flatMap((l) => l.models.map((m) => m.model))));
  document.getElementById("report-facts").textContent = t("report.facts", {
    days: report.scored_days,
    stations: temperature?.stations ?? "?",
    models: models.size,
    generated: new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-GB", { dateStyle: "medium", timeZone: "Europe/Prague" }).format(new Date(report.generated)),
  });
  document.getElementById("headline").replaceChildren(...VARIABLES.map((v) => headline(report, v)));
  const leads = leadsOf(report);
  const select = document.getElementById("lead");
  const wanted = new URLSearchParams(window.location.hash.slice(1)).get("lead");
  const current = leads.includes(wanted) ? wanted : "1";
  select.replaceChildren(...leads.map((l) => Object.assign(el("option", `D+${l}`), { value: l, selected: l === current })));
  const draw = () => {
    const leadKey = select.value;
    document.getElementById("charts").replaceChildren(
      ...VARIABLES.map((v) => chart(report, v, leadKey)),
      el("p", t("report.chartNote"), "note"),
    );
    const winLead = report.wins?.[`${VARIABLES[0]}/${leadKey}`] ? leadKey : "1";
    document.getElementById("wins-title").textContent = t("report.wins", { lead: winLead });
    document.getElementById("wins-note").textContent = t("report.winsNote", {
      total: report.wins?.[`${VARIABLES[0]}/${winLead}`]?.okresy_total ?? "?",
    });
    document.getElementById("wins").replaceChildren(...VARIABLES.map((v) => wins(report, v, winLead)));
  };
  select.addEventListener("change", draw);
  draw();
  document.getElementById("caveats").replaceChildren(...[1, 2, 3, 4, 5, 6].map((k) => el("li", t(`report.caveat${k}`))));
  document.getElementById("report-body").hidden = false;
}

async function downloads(month) {
  const p = document.getElementById("downloads");
  p.replaceChildren(`${t("report.download")}: `);
  const link = (href, text) => Object.assign(el("a", text), { href });
  const pdf = await fetch(`reports/${month}.pdf`, { method: "HEAD" }).then((r) => r.ok).catch(() => false);
  p.append(...(pdf ? [link(`reports/${month}.pdf`, t("report.pdf")), " · "] : []), link(`reports/${month}.json`, t("report.json")));
}

async function main() {
  const message = document.getElementById("report-message");
  const index = await getJson("reports/index.json");
  if (!index?.months?.length) {
    message.textContent = index ? t("report.empty") : t("report.failed");
    return;
  }
  const hashMonth = window.location.hash.slice(1).split("&")[0].split("=")[0];
  const month = index.months.includes(hashMonth) ? hashMonth : index.months[0];
  const report = await getJson(`reports/${month}.json`);
  if (!report) {
    message.textContent = t("report.failed");
    return;
  }
  const picker = document.getElementById("month");
  picker.replaceChildren(...index.months.map((m) => Object.assign(el("option", monthLabel(m, language)), { value: m, selected: m === month })));
  picker.addEventListener("change", () => {
    window.location.hash = picker.value;
    window.location.reload();
  });
  document.getElementById("print").addEventListener("click", () => window.print());
  render(report);
  downloads(month);
}

main();
