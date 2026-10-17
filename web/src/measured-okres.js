// The okres panel of the measured-weather page (station.html, layer "Okresy"): what was
// measured in an okres on a day (the mean of its stations, observed.js), the parts of the
// day, what our forecast had said ("forecast vs. measured") and the okres's stations.
// Moved here from the forecast map, which shows the coming days only.
import { iconCanvas } from "./icons.js";
import { borrowedFor, difference } from "./observed.js";
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
  const symbolText = (symbol) => (symbol ? t(`symbol.${symbol}`) : "");
  const symbolMeasured = (symbol) => (symbol ? t(`diary.symbol.${symbol}`) : "");
  // "1 stanice", "3 stanice", "12 stanic" / "1 station", "12 stations"
  const plural = new Intl.PluralRules(language);
  const stationsText = (n) => t(`obs.st.${plural.select(n) === "one" ? "one" : plural.select(n) === "few" ? "few" : "other"}`, { n });

  /** "Jevíčko (okres Svitavy)": a borrowed station with its own okres. */
  const borrowedName = (b) => (b.okres ? t("obs.borrowedName", { name: b.name, okres: b.okres }) : b.name);

  /** Who measured a value: "3 stanice", or "z okolních stanic: Jevíčko (okres Svitavy), …"
   * where the okres has none of its own for it (the nearest of its neighbours). */
  function source(row, n, ...groups) {
    const lent = groups.map((g) => borrowedFor(row, g)).find((list) => list.length);
    return lent ? t("obs.nearby", { list: lent.map(borrowedName).join(", ") }) : stationsText(n);
  }

  /** The measured values of an okres's part of day, each with its number of stations. */
  function measuredFacts(row) {
    const facts = element("ul", null, "facts");
    const add = (text, className) => facts.append(element("li", text, className));
    // a value from the neighbours' stations: marked as such
    const lentClass = (...groups) => (groups.some((g) => borrowedFor(row, g).length) ? "borrowed" : undefined);
    const n = row.counts;
    if (row.symbol) add(symbolMeasured(row.symbol));
    if (n.t) {
      let text = t("obs.temp", { high: fmt(row.tmax), low: fmt(row.tmin), stations: source(row, n.t, "t") });
      if (n.t > 1) text += ` ${t("obs.tempRange", { low: fmt(row.tmin_lo), high: fmt(row.tmax_hi) })}`;
      add(text, lentClass("t"));
    } else add(t("obs.noTemp"), "missing");
    if (n.r) {
      let text = t("obs.rain", { amount: fmt1(row.precipitation), stations: source(row, n.r, "r") });
      if (n.r > 1 && row.precipitation_hi > 0) text += ` ${t("obs.rainMax", { amount: fmt1(row.precipitation_hi) })}`;
      add(text, lentClass("r"));
    } else add(t("obs.noRain"), "missing");
    if (n.w && n.g) {
      add(t("obs.wind", { wind: fmt(row.wind), gust: fmt(row.gust), stations: source(row, Math.max(n.w, n.g), "w", "g") }), lentClass("w", "g"));
    } else if (n.g) {
      // older days (daily values): the gust only
      add(t("obs.gustOnly", { gust: fmt(row.gust), stations: source(row, n.g, "g") }), lentClass("g"));
    } else if (n.w) {
      add(t("obs.windOnly", { wind: fmt(row.wind), stations: source(row, n.w, "w") }), lentClass("w"));
    } else add(t("obs.noWind"), "missing");
    if (n.s) add(t("obs.sunshine", { hours: fmt1(row.sunshine), stations: source(row, n.s, "s") }), lentClass("s"));
    if (n.c) add(t("obs.cloud", { value: fmt(row.cloud), stations: source(row, n.c, "c") }), lentClass("c"));
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

  /** "+1.2°": a difference, signed; empty without one. */
  const signed = (v, digits, unit) => {
    if (v == null) return "";
    const text = v.toLocaleString(language, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    return `${v > 0 ? "+" : ""}${text}${unit}`;
  };

  /** A forecast's row label: "1 day ahead", "same day", with how it came about. */
  function sourceLine(f) {
    if (f.kind === "rebuilt") return t("obs.kind.rebuilt");
    if (f.kind === "stored_sky") return t("obs.kind.storedSky", { time: issuedText(f.issued) ?? "–" });
    return t("obs.kind.stored", { time: issuedText(f.issued) ?? "–" });
  }

  /** One value cell: the value, and below it the difference to the measured one. */
  function valueCell(value, delta, deltaText) {
    const td = element("td", null, "num");
    td.append(element("span", value));
    if (delta != null) {
      const d = element("small", deltaText, "delta");
      d.title = t("obs.deltaHint");
      td.append(d);
    }
    return td;
  }

  /** A row of the comparison: the symbol, temperature, rain and wind (with Δ). */
  function compareRow(label, note, row, measured, part, isMeasured, className) {
    const tr = element("tr", null, className);
    const head = element("th", null, "lead");
    head.scope = "row";
    head.append(element("span", label));
    if (note) head.append(element("small", note));
    tr.append(head);
    const symbol = element("td", null, "sym");
    if (row?.symbol) {
      const text = isMeasured ? symbolMeasured(row.symbol) : symbolText(row.symbol);
      symbol.append(iconCanvas(iconName(row.symbol, part, isMeasured ? row : { dark: part === "night" }), 24, text));
      symbol.title = text;
    } else symbol.textContent = row && !isMeasured && row.precipitation != null ? t("obs.noSky") : "–";
    tr.append(symbol);
    const temp = row ? (part === "night" ? row.tmin : row.tmax) : null;
    const dT = isMeasured ? null : difference(row, measured, "temperature", part);
    const dR = isMeasured ? null : difference(row, measured, "precipitation", part);
    const dW = isMeasured ? null : difference(row, measured, "wind", part);
    tr.append(
      valueCell(temp == null ? "–" : `${Math.round(temp)}°`, dT, signed(dT, 0, "°")),
      valueCell(row?.precipitation == null ? "–" : `${fmt1(row.precipitation)} mm`, dR, signed(dR, 1, "")),
      valueCell(row?.wind == null ? "–" : `${fmt(row.wind)} m/s`, dW, signed(dW, 0, "")),
    );
    return tr;
  }

  /** "Forecast vs. measured" for the part shown: what was measured, then our forecast
   * of the same day (morning run), 1, 2 and 3 days ahead, stored or rebuilt. */
  function compareSection(view, state) {
    const box = element("section", null, "compare");
    box.append(element("h3", t("obs.compareTitle")));
    const forecasts = view.forecasts ?? [];
    const parts = element("div", null, "segmented compare-parts");
    parts.setAttribute("aria-label", t("tv.part"));
    for (const part of view.parts) {
      const button = element("button", t(`part.${part}`));
      button.type = "button";
      button.setAttribute("aria-pressed", String(part === state.part));
      button.addEventListener("click", () => update({ part }));
      parts.append(button);
    }
    if (view.parts.length > 1) box.append(parts);
    const measured = rowFor(view, state.okres, state.day, state.part);
    const shown = forecasts.filter((f) => f.rows.get(`${state.okres}|${state.part}`));
    if (!shown.length) {
      box.append(element("p", t(forecasts.length ? "obs.noForecastOkres" : "obs.noForecast"), "model-note"));
      return box;
    }
    const table = element("table", null, "compare-table matrix");
    const head = element("tr");
    for (const key of ["", "obs.col.symbol", "obs.col.temp", "obs.col.rain", "obs.col.wind"]) head.append(element("th", key ? t(key) : ""));
    table.append(head);
    table.append(compareRow(t("obs.measured"), null, measured, measured, state.part, true, "measured"));
    for (const f of shown) {
      const label = t(`obs.lead.${Math.min(f.lead, 3)}`, { n: f.lead });
      table.append(compareRow(label, sourceLine(f), f.rows.get(`${state.okres}|${state.part}`), measured, state.part, false, f.kind));
    }
    box.append(table);
    const notes = [t("obs.compareNote")];
    if (shown.some((f) => f.kind === "rebuilt")) notes.push(t("obs.rebuiltNote"));
    for (const note of notes) box.append(element("p", note, "model-note"));
    return box;
  }

  /** A station linked to its page (the diary opens on that day). */
  function stationLink(id, name) {
    const a = element("a", name ?? id);
    a.href = stationHref(id);
    a.addEventListener("click", (event) => openStation(id, event));
    return a;
  }

  /** The okres's stations that day, then the stations of its neighbours it borrowed. */
  function stationsSection(view, state) {
    const row = rowFor(view, state.okres, state.day, "day");
    const ids = row?.stations ?? [];
    const box = element("section", null, "obs-stations");
    box.append(element("h3", t("obs.stationsTitle", { stations: stationsText(ids.length) })));
    if (!ids.length) box.append(element("p", t("obs.noStations"), "model-note"));
    else {
      const list = element("ul");
      const names = new Map();
      for (const id of ids) {
        const a = stationLink(id);
        names.set(id, a);
        const li = element("li");
        li.append(a);
        list.append(li);
      }
      stationIndex().then((index) => {
        for (const s of index?.stations ?? []) if (names.has(s.id)) names.get(s.id).textContent = s.name;
      });
      box.append(list);
    }
    const lent = row?.bst ?? [];
    if (lent.length) {
      box.append(element("h3", t("obs.borrowedTitle", { stations: stationsText(lent.length) })));
      const list = element("ul", null, "borrowed");
      for (const b of lent) {
        const li = element("li");
        li.append(stationLink(b.id, b.name), element("span", ` ${t("obs.borrowedWhere", { okres: b.okres ?? "–", km: fmt1(b.km) })}`, "where"));
        list.append(li);
      }
      box.append(list, element("p", t("obs.borrowedNote"), "model-note"));
    }
    return box;
  }

  /** Draw the panel of `state.okres` (none: empty) from a measured day's `view`. */
  function render(view, state) {
    if (!state.okres || !view) {
      panel.replaceChildren();
      return;
    }
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
    children.push(compareSection(view, state), stationsSection(view, state), element("p", t("obs.panelNote"), "model-note"));
    panel.replaceChildren(...children);
  }

  return { render, stationsText, fmt1 };
}
