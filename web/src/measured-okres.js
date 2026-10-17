// The okres panel of the measured-weather page (station.html, layer "Okresy"): what was
// measured in an okres on a day (the mean of its stations, observed.js), the parts of the
// day, what our forecast had said ("forecast vs. measured") and the okres's stations.
// Moved here from the forecast map, which shows the coming days only.
import { iconCanvas } from "./icons.js";
import { defaultLead, difference } from "./observed.js";
import { issuedText } from "./picker.js";
import { PARTS, displayName, iconName, labelFor, rowFor } from "./tv.js";

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

/**
 * @param {object} o
 * @param {HTMLElement} o.panel the panel's box
 * @param {Function} o.t i18n
 * @param {string} o.language
 * @param {(day: string) => string} o.dayText "Yesterday 10/16"
 * @param {(change: object) => void} o.update change the page's view ({part}, {okres: null})
 * @param {(id: string) => string} o.stationHref the link of a station on that day
 * @param {(id: string, event: Event) => void} o.openStation a click on a station
 * @param {() => Promise<object>} o.stationIndex the station index (names)
 */
export function createOkresPanel({ panel, t, language, dayText, update, stationHref, openStation, stationIndex }) {
  const fmt = (v, digits = 0) => (v == null ? "–" : v.toFixed(digits));
  const fmt1 = (v) => (v == null ? "–" : v.toLocaleString(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
  const percent = (p) => (p == null ? "–" : `${Math.round(p * 100)} %`);
  const symbolText = (symbol) => (symbol ? t(`symbol.${symbol}`) : "");
  const symbolMeasured = (symbol) => (symbol ? t(`diary.symbol.${symbol}`) : "");
  // "1 stanice", "3 stanice", "12 stanic" / "1 station", "12 stations"
  const plural = new Intl.PluralRules(language);
  const stationsText = (n) => t(`obs.st.${plural.select(n) === "one" ? "one" : plural.select(n) === "few" ? "few" : "other"}`, { n });
  let lead = null; // the forecast lead of the comparison (null: one day before)
  let leadDay = null;

  /** The measured values of an okres's part of day, each with its number of stations. */
  function measuredFacts(row) {
    const facts = element("ul", null, "facts");
    const add = (text, className) => facts.append(element("li", text, className));
    const n = row.counts;
    if (row.symbol) add(symbolMeasured(row.symbol));
    if (n.t) {
      let text = t("obs.temp", { high: fmt(row.tmax), low: fmt(row.tmin), stations: stationsText(n.t) });
      if (n.t > 1) text += ` ${t("obs.tempRange", { low: fmt(row.tmin_lo), high: fmt(row.tmax_hi) })}`;
      add(text);
    } else add(t("obs.noTemp"), "missing");
    if (n.r) {
      let text = t("obs.rain", { amount: fmt1(row.precipitation), stations: stationsText(n.r) });
      if (n.r > 1 && row.precipitation_hi > 0) text += ` ${t("obs.rainMax", { amount: fmt1(row.precipitation_hi) })}`;
      add(text);
    } else add(t("obs.noRain"), "missing");
    if (n.w && n.g) {
      add(t("obs.wind", { wind: fmt(row.wind), gust: fmt(row.gust), stations: stationsText(Math.max(n.w, n.g)) }));
    } else if (n.g) {
      // older days (daily values): the gust only
      add(t("obs.gustOnly", { gust: fmt(row.gust), stations: stationsText(n.g) }));
    } else if (n.w) {
      add(t("obs.windOnly", { wind: fmt(row.wind), stations: stationsText(n.w) }));
    } else add(t("obs.noWind"), "missing");
    if (n.s) add(t("obs.sunshine", { hours: fmt1(row.sunshine), stations: stationsText(n.s) }));
    if (n.c) add(t("obs.cloud", { value: fmt(row.cloud), stations: stationsText(n.c) }));
    if (row.ph?.length) add(t("obs.phenomena", { list: row.ph.map((c) => t(`pheno.${c}`)).join(", ") }));
    return facts;
  }

  function partCell(row, part) {
    const cell = element("div", null, "part");
    cell.append(
      element("span", t(`part.${part}`), "part-name"),
      iconCanvas(row ? iconName(row.symbol, part, row) : "", 34, symbolMeasured(row?.symbol)),
      element("strong", row ? labelFor(row, "temperature", part) : "–"),
      element("span", row?.precipitation == null ? "" : `${fmt(row.precipitation, 1)} mm`, "rain"),
    );
    return cell;
  }

  /** "13° · 1.4 mm" with the symbol: one side of the comparison. */
  function compareCell(row, part, measured) {
    const td = element("td", null, "cmp");
    if (!row) {
      td.textContent = "–";
      return td;
    }
    const symbol = measured ? symbolMeasured(row.symbol) : symbolText(row.symbol);
    td.append(
      iconCanvas(iconName(row.symbol, part, measured ? row : { dark: part === "night" }), 22, symbol),
      element("strong", labelFor({ ...row, measured: true }, "temperature", part)),
      element("span", row.precipitation == null ? "–" : `${fmt1(row.precipitation)} mm`, "rain"),
    );
    if (!measured && row.rain_probability != null) td.title = t("tv.rain", { chance: percent(row.rain_probability), amount: fmt1(row.precipitation) });
    return td;
  }

  /** "Forecast vs. measured": our archived forecast of that day beside the measurements. */
  function compareSection(view, state, rerender) {
    const box = element("section", null, "compare");
    box.append(element("h3", t("obs.compareTitle")));
    const forecasts = view.forecasts ?? [];
    if (!forecasts.length) {
      box.append(element("p", t("obs.noForecast"), "model-note"));
      return box;
    }
    const chosenLead = forecasts.some((f) => f.lead === lead) ? lead : defaultLead(forecasts);
    const chosen = forecasts.find((f) => f.lead === chosenLead);
    if (forecasts.length > 1) {
      const leads = element("div", null, "segmented leads");
      leads.setAttribute("aria-label", t("obs.leadPick"));
      for (const f of forecasts) {
        const button = element("button", t(`obs.lead.${Math.min(f.lead, 3)}`, { n: f.lead }));
        button.type = "button";
        button.setAttribute("aria-pressed", String(f.lead === chosenLead));
        button.addEventListener("click", () => {
          lead = f.lead;
          rerender();
        });
        leads.append(button);
      }
      box.append(leads);
    }
    box.append(element("p", t(`obs.issued.${Math.min(chosenLead, 3)}`, { n: chosenLead, time: issuedText(chosen.issued) ?? "–" }), "model-note"));
    const table = element("table", null, "compare-table");
    const head = element("tr");
    head.append(element("th", ""), element("th", t("obs.forecast")), element("th", t("obs.measured")), element("th", "Δ", "num"));
    head.lastChild.title = t("obs.deltaHint");
    table.append(head);
    for (const part of view.parts) {
      const measured = rowFor(view, state.okres, state.day, part);
      const forecast = chosen.rows.get(`${state.okres}|${part}`);
      const tr = element("tr", null, part === state.part ? "current" : "");
      tr.addEventListener("click", () => update({ part }));
      const delta = difference(forecast, measured, "temperature", part);
      tr.append(
        element("td", t(`part.${part}`)),
        compareCell(forecast, part, false),
        compareCell(measured, part, true),
        element("td", delta == null ? "" : `${delta > 0 ? "+" : ""}${fmt(delta)}°`, "num delta"),
      );
      table.append(tr);
    }
    box.append(table, element("p", t("obs.compareNote"), "model-note"));
    return box;
  }

  /** The okres's stations that day, linked to their pages (the diary opens on that day). */
  function stationsSection(view, state) {
    const ids = rowFor(view, state.okres, state.day, "day")?.stations ?? [];
    const box = element("section", null, "obs-stations");
    box.append(element("h3", t("obs.stationsTitle", { stations: stationsText(ids.length) })));
    if (!ids.length) {
      box.append(element("p", t("obs.noStations"), "model-note"));
      return box;
    }
    const list = element("ul");
    const names = new Map();
    for (const id of ids) {
      const a = element("a", id);
      a.href = stationHref(id);
      a.addEventListener("click", (event) => openStation(id, event));
      names.set(id, a);
      const li = element("li");
      li.append(a);
      list.append(li);
    }
    stationIndex().then((index) => {
      for (const s of index?.stations ?? []) if (names.has(s.id)) names.get(s.id).textContent = s.name;
    });
    box.append(list);
    return box;
  }

  /** Draw the panel of `state.okres` (none: empty) from a measured day's `view`. */
  function render(view, state) {
    if (!state.okres || !view) {
      panel.replaceChildren();
      return;
    }
    if (leadDay !== state.day) {
      lead = null;
      leadDay = state.day;
    }
    const rerender = () => render(view, state);
    panel.classList.add("past");
    const info = view.okresy.find((o) => o.code === state.okres);
    const close = element("button", "×", "close");
    close.type = "button";
    close.setAttribute("aria-label", t("chart.close"));
    close.addEventListener("click", () => update({ okres: null }));
    const when = element("p", null, "when");
    when.append(element("span", t("obs.badge"), "past-badge"), element("span", ` ${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`));
    const head = [close, element("h2", displayName(info?.name ?? state.okres)), when];
    if (view.loading || view.failed) {
      panel.replaceChildren(...head, element("p", t(view.loading ? "obs.loading" : "obs.failed")));
      return;
    }
    const row = rowFor(view, state.okres, state.day, state.part);
    const big = element("div", null, "now");
    big.append(
      iconCanvas(row ? iconName(row.symbol, state.part, row) : "", 64, symbolMeasured(row?.symbol)),
      element("div", row ? labelFor(row, "temperature", state.part) : "–", "big-temp"),
    );
    const children = [...head, big];
    if (row) children.push(measuredFacts(row));
    if (view.parts.length > 1) {
      const strip = element("div", null, "strip");
      strip.append(...PARTS.slice(0, 4).map((p) => partCell(rowFor(view, state.okres, state.day, p), p)));
      children.push(strip);
    } else {
      children.push(element("p", t("obs.dailyNote"), "model-note"));
    }
    children.push(compareSection(view, state, rerender), stationsSection(view, state), element("p", t("obs.panelNote"), "model-note"));
    panel.replaceChildren(...children);
  }

  return { render, stationsText, fmt1 };
}
