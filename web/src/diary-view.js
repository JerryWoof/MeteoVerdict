// "Weather at the station" on the station page: the day table (the last 14 days, a
// week or a month), its summary, and the course of a clicked day. Logic in diary.js.
import * as Plot from "@observablehq/plot";

import {
  BADGES, CLEAR_SUNSHINE, PARTLY_SUNSHINE, SHOWERS_SUNSHINE, VIEWS, WET_MM, addDays, chunksFor,
  columnsFor, dayCourse, dayRows, daySymbol, daytimeCloud, parseDiaryFile, parseDiaryQuery, periodSummary,
  pragueDayHour, shiftDay, viewRange,
} from "./diary.js";
import { iconCanvas } from "./icons.js";
import { formatNumber } from "./station.js";

const $ = (id) => document.getElementById(id);

function el(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

const fmt = (v, digits = 1) => (v == null ? "–" : formatNumber(Math.round(v * 10 ** digits) / 10 ** digits));

/**
 * The diary of the station page. `dataPath`: the folder of the station files; `t` and
 * `language` from i18n.js. Returns {show(doc), hide()}.
 */
export function createDiary({ dataPath, t, language }) {
  const locale = language === "cs" ? "cs-CZ" : "en-GB";
  const utc = (options) => new Intl.DateTimeFormat(locale, { timeZone: "UTC", ...options });
  const DAY_SHORT = utc({ weekday: "short", day: "numeric", month: "numeric" });
  const DAY_LONG = utc({ weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const DATE = utc({ day: "numeric", month: "numeric", year: "numeric" });
  const MONTH = utc({ month: "long", year: "numeric" });
  const asDate = (iso) => new Date(`${iso}T12:00:00Z`);
  const dateText = (iso) => DATE.format(asDate(iso));
  const rangeText = (from, to) => {
    try {
      return DATE.formatRange(asDate(from), asDate(to));
    } catch {
      return `${dateText(from)} – ${dateText(to)}`;
    }
  };

  const query = parseDiaryQuery(window.location.search);
  let view = query.view ?? "days";
  let day = query.day; // the day the view is anchored to (its last day for 14 days)
  // a day chosen by the reader stays when another station is opened (to compare them);
  // otherwise each station opens on its newest day
  let pinned = Boolean(query.day);
  let selected = null; // the day whose course is open
  let doc = null;
  let cloud = new Map();
  const cache = new Map(); // "WSI/decade" → Promise of the file
  let token = 0;

  const section = $("diary");
  const dateInput = $("diary-date");

  function load(id, decade) {
    const key = `${id}/${decade}`;
    if (!cache.has(key)) {
      const promise = fetch(`${dataPath}/diary/${id}/${decade}.json.gz`)
        .then((r) => {
          if (!r.ok) throw new Error(`${r.status}`);
          return r.arrayBuffer();
        })
        .then(parseDiaryFile);
      promise.catch(() => cache.delete(key)); // try again next time
      cache.set(key, promise);
    }
    return cache.get(key);
  }

  function remember() {
    const url = new URL(window.location.href);
    url.searchParams.set("view", view);
    if (day && day !== doc?.diary?.last) url.searchParams.set("day", day);
    else url.searchParams.delete("day");
    if (view === "days" && !url.searchParams.has("day")) url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  }

  // --- the table ----------------------------------------------------------------------
  function dayCell(row) {
    const td = el("td", null, "diary-daycell");
    const button = el("button", DAY_SHORT.format(asDate(row.day)), "diary-daylink");
    button.type = "button";
    button.setAttribute("aria-pressed", String(row.day === selected));
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectDay(row.day);
    });
    td.append(button);
    if (row.unchecked) {
      const mark = el("span", "*", "diary-unchecked");
      mark.title = t("diary.unchecked");
      td.append(mark);
    }
    return td;
  }

  function precipitationText(row) {
    if (row.r == null) return "–";
    if (row.r === 0) return row.flags.r === "T" ? t("diary.trace") : "0";
    return `${fmt(row.r)} mm`;
  }

  // snow depth in the morning and the new snow ("12 +3"); a dusting or patchy cover
  // that ČHMÚ flags with 0 cm shows as "<1", with the reason in the tooltip
  function snowCell(row) {
    const td = el("td", null, "num");
    const parts = [];
    const title = [];
    if (row.sce > 0 || (row.sce === 0 && row.flags.sce)) {
      parts.push(row.sce > 0 ? fmt(row.sce, 0) : "<1");
      title.push(`${t("diary.snowDepth")}: ${row.sce > 0 ? `${fmt(row.sce, 0)} cm` : t(`diary.flag.sce.${row.flags.sce}`)}`);
    }
    if (row.sno > 0 || (row.sno === 0 && row.flags.sno)) {
      parts.push(row.sno > 0 ? `+${fmt(row.sno, 0)}` : "+<1");
      title.push(`${t("diary.newSnow")}: ${row.sno > 0 ? `${fmt(row.sno, 0)} cm` : t(`diary.flag.sno.${row.flags.sno}`)}`);
    }
    td.textContent = parts.join(" ");
    if (parts.length) td.append(el("span", "\u00a0cm", "unit"));
    if (title.length) td.title = title.join(", ");
    return td;
  }

  function badges(row) {
    const td = el("td", null, "diary-badges");
    for (const code of row.phenomena.filter((c) => BADGES.includes(c))) {
      td.append(el("span", t(`pheno.${code}`), `badge badge-${code}`));
    }
    return td;
  }

  const lat = () => doc?.station?.lat ?? null;

  // the unit in each cell on wide screens, only in the heading on phones (style.css)
  const UNITS = { precipitation: "mm", snow: "cm", sunshine: "h", gust: "m/s" };
  function withUnit(text, unit, className) {
    const td = el("td", text, className);
    td.append(el("span", `\u00a0${unit}`, "unit"));
    return td;
  }

  function cellFor(column, row) {
    switch (column) {
      case "symbol": {
        const symbol = daySymbol(row, lat());
        const td = el("td", null, "diary-symbol");
        if (symbol) {
          const label = t(`diary.symbol.${symbol}`);
          td.append(iconCanvas(symbol, 26, label));
          td.title = label;
        }
        return td;
      }
      case "temperature": {
        const td = el("td", null, "num");
        td.append(el("span", row.tx != null ? `${fmt(row.tx)}°` : "–", "tmax"), " / ", el("span", row.tn != null ? `${fmt(row.tn)}°` : "–", "tmin"));
        return td;
      }
      case "precipitation":
        return row.r ? withUnit(fmt(row.r), "mm", "num rain") : el("td", precipitationText(row), "num rain muted");
      case "snow":
        return snowCell(row);
      case "sunshine":
        return row.ssv != null ? withUnit(fmt(row.ssv), "h", "num") : el("td", "–", "num");
      case "gust":
        return row.g != null ? withUnit(fmt(row.g), "m/s", "num") : el("td", "–", "num");
      case "phenomena":
        return badges(row);
      default:
        return el("td");
    }
  }

  function renderTable(rows) {
    const table = $("diary-table");
    const columns = columnsFor(rows, lat());
    const head = el("tr");
    head.append(el("th", t("diary.col.day")));
    for (const c of columns) {
      const th = el("th", t(`diary.col.${c}`), ["symbol", "phenomena"].includes(c) ? "" : "num");
      if (UNITS[c]) th.append(el("span", ` (${UNITS[c]})`, "head-unit"));
      head.append(th);
    }
    // the latest days newest first; a week or a month in calendar order
    const body = (view === "days" ? [...rows].reverse() : rows).map((row) => {
      const tr = el("tr");
      if (row.day === selected) tr.className = "current";
      tr.addEventListener("click", () => selectDay(row.day));
      tr.append(dayCell(row), ...columns.map((c) => cellFor(c, row)));
      return tr;
    });
    const thead = el("thead");
    thead.append(head);
    const tbody = el("tbody");
    tbody.append(...body);
    table.replaceChildren(thead, tbody);
    table.hidden = !rows.length;
    const unchecked = rows.some((r) => r.unchecked);
    return unchecked;
  }

  // --- the summary --------------------------------------------------------------------
  function renderSummary(rows, title) {
    const s = periodSummary(rows);
    const box = $("diary-summary");
    const items = [];
    const at = (x) => ` (${DAY_SHORT.format(asDate(x.day))})`;
    const add = (key, value, field) => {
      if (value == null) return;
      const dt = el("dt", t(`diary.sum.${key}`));
      const dd = el("dd", value);
      if (field && s.count[field] < s.days) {
        dd.append(el("span", ` · ${t("diary.sum.partial", { n: s.count[field], days: s.days })}`, "muted small"));
      }
      items.push(dt, dd);
    };
    add("tmean", s.tmean != null ? `${fmt(s.tmean)} °C` : null, "t");
    add("tmax", s.tmax ? `${fmt(s.tmax.value)} °C${at(s.tmax)}` : null, "tx");
    add("tmin", s.tmin ? `${fmt(s.tmin.value)} °C${at(s.tmin)}` : null, "tn");
    add("precipitation", s.precipitation != null ? `${fmt(s.precipitation)} mm` : null, "r");
    add("wetDays", s.wetDays != null ? String(s.wetDays) : null);
    add("frostDays", s.frostDays != null ? String(s.frostDays) : null);
    if (s.iceDays) add("iceDays", String(s.iceDays));
    if (s.summerDays) add("summerDays", String(s.summerDays));
    add("sunshine", s.sunshine != null ? `${fmt(s.sunshine)} h` : null, "ssv");
    add("gust", s.gust ? `${fmt(s.gust.value)} m/s${at(s.gust)}` : null, "g");
    if (s.snowDays) add("snowDays", String(s.snowDays));
    if (s.snowMax?.value > 0) add("snowMax", `${fmt(s.snowMax.value, 0)} cm${at(s.snowMax)}`);
    if (s.storms != null) add("storms", String(s.storms));
    if (!items.length) {
      box.replaceChildren();
      return;
    }
    const dl = el("dl");
    dl.append(...items);
    box.replaceChildren(el("h4", `${t("diary.summary")}: ${title} · ${t("diary.sum.days", { n: s.days })}`), dl);
  }

  // --- the course of one day ----------------------------------------------------------
  const hourTick = (d) => `${pragueDayHour(d.getTime()).hour}`;
  // every `hours` hours from the day's local midnight (a 23- or 25-hour day ends off by one)
  const hourTicks = (hours) => {
    const ticks = [];
    for (let ms = course.start.getTime(); ms <= course.end.getTime(); ms += hours * 3_600_000) ticks.push(new Date(ms));
    return ticks;
  };

  function dayChart(points, { kind, label, step, extra }) {
    const main = document.querySelector("main");
    const width = Math.max(280, Math.min(900, main.clientWidth - 8));
    const marks = [];
    if (kind === "bars") {
      marks.push(Plot.rectY(points.filter((p) => p.value != null), {
        x1: (p) => new Date(p.time.getTime() - step), x2: "time", y: "value", fill: "#2b7bd1", inset: 0,
      }));
    } else {
      marks.push(Plot.lineY(points, { x: "time", y: "value", stroke: kind === "temperature" ? "#d0452b" : "#2f8a4a", strokeWidth: 1.5 }));
    }
    if (extra) marks.push(...extra);
    marks.push(Plot.tip(points.filter((p) => p.value != null), Plot.pointerX({
      x: "time",
      y: "value",
      title: (p) => {
        const local = pragueDayHour(p.time.getTime());
        const minutes = String(p.time.getUTCMinutes()).padStart(2, "0");
        return `${local.hour}:${minutes}  ${formatNumber(p.value)}`;
      },
    })));
    if (kind === "bars") marks.push(Plot.ruleY([0]));
    return Plot.plot({
      width,
      height: kind === "bars" ? 110 : 150,
      marginLeft: 44,
      style: { fontSize: "11px" },
      x: { type: "utc", label: null, domain: [course.start, course.end], tickFormat: hourTick, ticks: hourTicks(width < 500 ? 6 : 3) },
      y: { label, grid: true, tickFormat: (v) => formatNumber(v), ...(kind === "bars" ? { domain: [0, Math.max(1, ...points.map((p) => p.value ?? 0))] } : {}) },
      marks,
    });
  }

  let course = null;

  function factsOf(row) {
    const list = el("ul", null, "diary-facts");
    const add = (text) => list.append(el("li", text));
    const symbol = daySymbol(row, lat());
    if (symbol) add(t(`diary.symbol.${symbol}`));
    if (row.tx != null || row.tn != null) add(`${t("diary.col.temperature")}: ${fmt(row.tx)} / ${fmt(row.tn)} °C${row.t != null ? ` · ${t("diary.sum.tmean").toLowerCase()} ${fmt(row.t)} °C` : ""}`);
    if (row.r != null) add(`${t("diary.col.precipitation")}: ${precipitationText(row)}`);
    if (row.sno || row.flags.sno) add(`${t("diary.newSnow")}: ${row.sno ? `${fmt(row.sno, 0)} cm` : t(`diary.flag.sno.${row.flags.sno}`)}`);
    if (row.sce || row.flags.sce) add(`${t("diary.snowDepth")}: ${row.sce ? `${fmt(row.sce, 0)} cm` : t(`diary.flag.sce.${row.flags.sce}`)}`);
    if (row.ssv != null) add(`${t("diary.col.sunshine")}: ${fmt(row.ssv)} h`);
    if (row.g != null) add(`${t("diary.sum.gust")}: ${fmt(row.g)} m/s`);
    if (row.phenomena.length) {
      add(`${t("diary.col.phenomena")}: ${row.phenomena.map((c) => t(`pheno.${c}`)).join(", ")}`);
    }
    if (row.unchecked) add(`* ${t("diary.unchecked")}`);
    return list;
  }

  function renderDay(rows) {
    const box = $("diary-day");
    const row = rows.find((r) => r.day === selected);
    if (!row) {
      box.replaceChildren();
      return;
    }
    const close = el("button", "×", "close");
    close.type = "button";
    close.setAttribute("aria-label", t("diary.day.close"));
    close.addEventListener("click", () => selectDay(null));
    const title = DAY_LONG.format(asDate(row.day));
    const parts = [close, el("h4", title.charAt(0).toLocaleUpperCase(language) + title.slice(1)), factsOf(row)];
    course = dayCourse(doc, row.day);
    if (!course) {
      const fine = doc.series?.["10min"] || doc.series?.["1hour"];
      parts.push(el("p", t(fine ? "diary.day.none" : "diary.day.dailyOnly"), "note"));
    } else {
      const step = course.view === "10min" ? 600_000 : 3_600_000;
      parts.push(el("p", t(`diary.day.${course.view}`), "note"));
      if (course.temperature.length) parts.push(dayChart(course.temperature, { kind: "temperature", label: t("diary.chart.temperature") }));
      if (course.precipitation.some((p) => p.value > 0)) parts.push(dayChart(course.precipitation, { kind: "bars", label: t("diary.chart.precipitation"), step }));
      if (course.wind.length || course.gust.length) {
        const gusts = course.gust.filter((p) => p.value != null);
        const wind = course.wind.length ? course.wind : course.gust.map((p) => ({ ...p, value: null }));
        parts.push(dayChart(wind, {
          kind: "wind",
          label: t("diary.chart.wind"),
          extra: [Plot.dot(gusts, { x: "time", y: "value", r: 1.6, fill: "#2f8a4a", fillOpacity: 0.6 })],
        }));
        parts.push(el("p", t("diary.chart.windLegend"), "muted small"));
      }
    }
    box.replaceChildren(...parts);
  }

  function selectDay(next) {
    selected = next === selected ? null : next;
    render();
    if (selected) $("diary-day").scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // --- the whole section --------------------------------------------------------------
  function renderControls() {
    const { first, last } = doc.diary;
    for (const button of section.querySelectorAll("[data-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.view === view));
    }
    dateInput.min = first;
    dateInput.max = last;
    dateInput.value = day;
    const { from, to } = viewRange(view, day, first, last);
    $("diary-prev").disabled = from <= first;
    $("diary-next").disabled = to >= last;
    $("diary-latest").disabled = day === last && view === "days";
    $("diary-range").textContent = t("diary.range", { first: dateText(first), last: dateText(last) });
  }

  async function render() {
    if (!doc?.diary) return;
    const mine = ++token;
    const { first, last } = doc.diary;
    renderControls();
    const { from, to } = viewRange(view, day, first, last);
    $("diary-period").textContent = view === "month" ? MONTH.format(asDate(from)) : rangeText(from, to);
    const decades = chunksFor(doc.diary, from, to);
    let chunks;
    try {
      if (decades.some((d) => !cache.has(`${doc.station.id}/${d}`))) $("diary-message").textContent = t("diary.loading");
      chunks = await Promise.all(decades.map((d) => load(doc.station.id, d)));
    } catch {
      if (mine === token) $("diary-message").textContent = t("diary.failed");
      return;
    }
    if (mine !== token) return;
    const rows = dayRows(chunks, from, to);
    for (const row of rows) row.cloud = cloud.get(row.day) ?? null;
    const empty = !rows.some((r) => r.phenomena.length || ["tx", "tn", "r", "sce", "ssv", "g"].some((f) => r[f] != null));
    const messages = [];
    if (empty) messages.push(t("diary.empty"));
    const generated = doc.generated?.slice(0, 10);
    if (doc.station.active !== false && generated && last < addDays(generated, -3)) {
      messages.push(t("diary.delay", { last: dateText(last) }));
    }
    const unchecked = renderTable(empty ? [] : rows);
    if (unchecked) messages.push(t("diary.uncheckedNote"));
    $("diary-message").textContent = messages.join(" ");
    const title = view === "month" ? MONTH.format(asDate(from)) : rangeText(from, to);
    if (empty) $("diary-summary").replaceChildren();
    else renderSummary(rows, title);
    renderDay(rows);
    remember();
  }

  function go(next, pin = true) {
    pinned = pin;
    const { first, last } = doc.diary;
    day = next < first ? first : next > last ? last : next;
    if (selected && !viewRangeHas(selected)) selected = null;
    render();
  }

  const viewRangeHas = (d) => {
    const { from, to } = viewRange(view, day, doc.diary.first, doc.diary.last);
    return d >= from && d <= to;
  };

  for (const button of section.querySelectorAll("[data-view]")) {
    button.addEventListener("click", () => {
      view = VIEWS.includes(button.dataset.view) ? button.dataset.view : "days";
      go(day, pinned);
    });
  }
  $("diary-prev").addEventListener("click", () => go(shiftDay(view, day, -1)));
  $("diary-next").addEventListener("click", () => go(shiftDay(view, day, 1)));
  $("diary-latest").addEventListener("click", () => {
    view = "days";
    go(doc.diary.last, false);
  });
  dateInput.addEventListener("change", () => {
    if (dateInput.value) {
      selected = dateInput.value;
      go(dateInput.value);
    }
  });
  $("diary-controls").addEventListener("submit", (event) => event.preventDefault());

  function fillDefinitions() {
    const list = $("diary-defs");
    list.replaceChildren(
      el("li", t("diary.defs.day")),
      ...["temperature", "precipitation", "snow", "sunshine", "gust", "phenomena"].map((k) => el("li", t(`diary.defs.${k}`))),
      el("li", t("diary.defs.symbol", {
        wet: formatNumber(WET_MM),
        showers: Math.round(SHOWERS_SUNSHINE * 100),
        clear: Math.round(CLEAR_SUNSHINE * 100),
        partly: Math.round(PARTLY_SUNSHINE * 100),
      })),
      el("li", t("diary.defs.quality")),
    );
  }
  fillDefinitions();

  return {
    show(next) {
      const sameStation = doc?.station?.id === next?.station?.id;
      doc = next;
      if (!doc?.diary) {
        section.hidden = !doc;
        if (doc) {
          for (const id of ["diary-table", "diary-summary", "diary-day"]) $(id).replaceChildren();
          $("diary-controls").hidden = true;
          $("diary-period").textContent = "";
          $("diary-message").textContent = t("diary.none");
        }
        return;
      }
      section.hidden = false;
      $("diary-controls").hidden = false;
      cloud = daytimeCloud(doc.series?.["1hour"]);
      const { first, last } = doc.diary;
      if (!day || (!sameStation && !pinned)) day = last;
      day = day < first ? first : day > last ? last : day;
      if (!sameStation && selected && (selected < first || selected > last)) selected = null;
      render();
    },
    hide() {
      doc = null;
      section.hidden = true;
    },
  };
}
