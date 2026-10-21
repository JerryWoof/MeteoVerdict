// "Measured weather": the Weather tab of the station page (measured.html), the forecast
// map's look for what ČHMÚ's stations measured, per okres (the mean of its stations), from
// data/scores/observed/<day>.json (`mvd observed-map`, docs/data-sources.md#observed-map).
// Pure helpers; the page is station-page.js, the map measured-map-view.js.

import { CAPITALS, displayName, labelFor, parseView, placeMarkers, valueFor, viewHash } from "./tv.js";

/** The kinds-of-station map (the station page's map before the measured weather). */
export const KINDS_HASH = "#kinds";
/** Day tabs: the last three measured days (yesterday first); any other day through the date field. */
export const MAX_TABS = 3;

/**
 * What the station page shows for a hash: "measured" (the Weather tab: no hash, or
 * "#day/part/colour/values" as on the forecast map), "kinds" (the Stations tab) or "station"
 * (an old link to a station's own page, "#WSI" or "#WSI/element": it opens the Stations tab).
 * An old okres link ("#CZ0631") opens that okres on the Weather tab.
 */
export function pageMode(hash) {
  const h = (hash ?? "").replace(/^#/, "");
  if (!h || /^\d{4}-\d{2}-\d{2}(\/|$)/.test(h) || okresLink(hash)) return "measured";
  if (`#${h}` === KINDS_HASH || h.startsWith("kinds/")) return "kinds";
  return "station";
}

/** An old link to an okres ("#CZ0631", from before the page had days): its code, or null. */
export function okresLink(hash) {
  const m = /^#?(CZ\d{4})$/.exec(hash ?? "");
  return m ? m[1] : null;
}

/** A hash part decoded, or null when it is not valid (a mistyped "%E0%A4%A" must not break the page). */
export function decodePart(text) {
  try {
    return decodeURIComponent(text);
  } catch {
    return null;
  }
}

/** The station open in the Stations view's panel ("#kinds/<id>"), or null. */
export function kindsStation(hash) {
  const m = /^#?kinds\/(.+)$/.exec(hash ?? "");
  return m ? decodePart(m[1]) : null;
}

/**
 * The Weather tab's view from the hash "#day/part/colour/values[/CZxxxx]" (the forecast
 * map's format): {day, part, colour, shown, okres} with `okres` the open okres panel. An old
 * "/okresy" or "/stations" ending (the stations were once a layer) is ignored. `days` the
 * measured days offered, `fallback` {day, part}.
 */
export function parseLanding(hash, days, fallback) {
  // an old okres link: that okres on the newest day
  const code = okresLink(hash);
  if (code) return { ...parseView("", { days, okresy: [] }, fallback), okres: code };
  const h = (pageMode(hash) === "measured" ? hash ?? "" : "").replace(/^#/, "");
  const segments = h.split("/");
  const isExtra = (s) => ["okresy", "stations"].includes(s) || /^CZ/.test(s ?? "");
  const extra = segments[4] ?? (isExtra(segments[3]) ? segments[3] : undefined);
  const forView = isExtra(segments[3]) && !/^CZ/.test(segments[3]) ? segments.slice(0, 3).join("/") : h;
  const { day, part, colour, shown } = parseView(forView, { days, okresy: [] }, fallback);
  return { day, part, colour, shown, okres: /^CZ\d{3,4}$/.test(extra ?? "") ? extra : null };
}

/** The Weather tab's hash (the forecast map's format). */
export function landingHash(view) {
  return viewHash({ ...view, okres: view.okres ?? null });
}

/** The newest measured day before today (the landing opens on it), or null. */
export function defaultDay(index, todayIso) {
  const past = index.days.filter((d) => d.day < todayIso);
  return past.at(-1)?.day ?? null;
}

/**
 * The day tabs, newest first ("Yesterday", "Thursday", "Wednesday", …): the measured days
 * before today with parts of day (at most `count`), then `selected` when it is an older
 * measured day (from the date field).
 */
export function dayTabs(index, todayIso, selected = null, count = MAX_TABS) {
  const past = index.days.filter((d) => d.day < todayIso);
  const tabs = past.filter((d) => d.source !== "daily").slice(-count).map((d) => d.day).reverse();
  if (!tabs.length) tabs.push(...past.slice(-2).map((d) => d.day).reverse());
  if (selected && selected < todayIso && index.byDay.has(selected) && !tabs.includes(selected)) tabs.push(selected);
  return tabs;
}

// --- the okresy's labels on the map -----------------------------------------------------
/** Label priority of a row (smaller first): `selected` first, then the row's own `priority`. */
export function labelPriority(row, selected = null) {
  return row.id === selected ? 0 : row.priority ?? 6;
}

/**
 * The okres rows: one per okres of a measured day's view (observed.js
 * parseObservedDay) with a value in `part`, at the okres's point, as the map's labels
 * take them; the kraj capitals' okresy first when labels collide (as on the forecast map).
 */
export function okresRows(view, part) {
  if (!view?.rows) return [];
  const rows = [];
  for (const o of view.okresy) {
    const row = view.rows.get(`${o.code}|${view.day}|${part}`);
    if (!row || o.lat == null || o.lon == null) continue;
    if (!["tmax", "tmin", "precipitation", "wind", "gust", "sunshine", "cloud"].some((k) => row[k] != null)) continue;
    rows.push({
      ...row, id: o.code, name: displayName(o.name), lat: o.lat, lon: o.lon, okresCode: o.code,
      priority: CAPITALS.includes(o.code) ? 1 : 2,
    });
  }
  return rows;
}

/** Does the row have anything to show for the values chosen (its label would not be empty)? */
export function hasLabel(row, shown, part) {
  return Boolean(row.symbol) || shown.some((layer) => valueFor(row, layer, part) != null);
}

/**
 * The size of a station's label on the map (px), as the forecast map's markers lay it
 * out: the symbol (30 px) and the temperature in a row, the other values as chips
 * below, wrapped at 115 px. An estimate, for placing them without measuring each.
 */
export function labelSize(row, shown, part) {
  const temperature = shown.includes("temperature") && valueFor(row, "temperature", part) != null;
  const topWidth = (row.symbol ? 30 : 0) + (temperature ? 9 * labelFor(row, "temperature", part).length + 4 : 0);
  const topHeight = row.symbol ? 30 : temperature ? 20 : 0;
  const chips = shown
    .filter((l) => l !== "temperature" && valueFor(row, l, part) != null)
    .map((l) => 11 + 6.2 * labelFor(row, l, part).length + 10);
  let rows = 0;
  let width = 0;
  let line = Infinity;
  for (const w of chips) {
    if (line + w > 115) {
      rows += 1;
      line = w;
    } else line += w + 2;
    width = Math.max(width, Math.min(115, line));
  }
  return { w: Math.max(topWidth, width, 12), h: Math.max(topHeight + rows * 15, 12) };
}

/**
 * Which okresy get a label: the rows with something to show, by priority (the kraj
 * capitals first), each placed only
 * where it overlaps no label placed before. `project(row)` → {x, y} on the screen;
 * `width`, `height` the map's size (labels off the map are left out). Returns the ids.
 */
export function pickLabels(rows, { shown, part, project, width, height, selected = null, gap = 3 }) {
  const boxes = rows
    .filter((r) => hasLabel(r, shown, part) || r.id === selected)
    .map((r) => {
      const { x, y } = project(r);
      return { code: r.id, x, y, ...labelSize(r, shown, part), priority: labelPriority(r, selected) };
    })
    .filter((b) => b.x >= -b.w / 2 && b.y >= -b.h / 2 && b.x <= width + b.w / 2 && b.y <= height + b.h / 2)
    .sort((a, b) => (a.code < b.code ? -1 : 1)); // the same stations win every time
  return placeMarkers(boxes, gap);
}

/** A station in the Stations tab: its hash (the model choice added by `withModel`). */
export function stationHref(id, withModel = (hash) => hash) {
  return withModel(`${KINDS_HASH}/${encodeURIComponent(id)}`);
}
