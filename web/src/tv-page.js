import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

import { drawIcon, glyph, iconCanvas } from "./icons.js";
import { setUpLanguage } from "./i18n.js";
import {
  COLOURS, LAYERS, NEUTRAL, PARTS, RAMPS, colorFor, currentPart, dayLabel, displayName, ease,
  iconName, labelFor, lerpRow, mixColor, nextColour, okresColours, parseOutlook, parseView,
  placeMarkers, playSteps, rangeText, rowFor, startIndex, sunFor, sunRange, switchColours, summary, today,
  viewHash,
} from "./tv.js";

setWorkerUrl(workerUrl);
const t = setUpLanguage();
const language = document.documentElement.lang;

const BOUNDS = [
  [12.0, 48.5],
  [18.95, 51.1],
];
// hours of each part of the day, shown under its name
const HOURS = { night: "0–6", morning: "6–12", afternoon: "12–18", evening: "18–24", day: "0–24" };

const map = new MapLibreMap({
  container: "map",
  style: {
    version: 8,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": "#f4f1ea" } }],
  },
  bounds: BOUNDS,
  fitBoundsOptions: { padding: 20 },
  attributionControl: { customAttribution: "Boundaries: ČÚZK (CC BY 4.0)" },
});
map.addControl(new NavigationControl({ showCompass: false }));
// registered at once: the map may finish loading while the forecast is still on its way
const mapLoaded = new Promise((resolve) => map.on("load", resolve));

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

const fmt = (v, digits = 0) => (v == null ? "–" : v.toFixed(digits));
const percent = (p) => (p == null ? "–" : `${Math.round(p * 100)} %`);
const symbolText = (symbol) => (symbol ? t(`symbol.${symbol}`) : "");

// --- state, kept in the URL (tv.js parseView / viewHash) ----------------------------
let state = { day: null, part: null, colour: "temperature", shown: [], okres: null };
let playing = null; // "day" or "week" while playing

// the first line of a day tab: "Today", "Tomorrow", "Wednesday"
function dayName(day) {
  const label = dayLabel(day, today(Date.now()), language);
  return label.key ? t(label.key) : label.name;
}

// "Today 10/12", "Wednesday 10/14" (headings, the week in the okres panel)
function dayText(day) {
  return `${dayName(day)} ${dayLabel(day, today(Date.now()), language).short}`;
}

// sunrise and sunset with their glyphs: "↑ 07:03–07:28 ↓ 17:59–18:23" (a range or a time)
// (`key` the tooltip's text)
function sunLine(rise, set, key) {
  const line = element("span", null, "sun");
  line.append(glyph("sunrise", 13), element("span", rise), glyph("sunset", 13), element("span", set));
  line.title = t(key, { rise, set });
  return line;
}

// --- when: days and parts of the day (above the map) --------------------------------
function renderWhen(outlook) {
  const days = document.getElementById("days");
  days.setAttribute("aria-label", t("tv.day"));
  days.replaceChildren(
    ...outlook.days.map((day) => {
      const button = element("button", null, "daytab");
      button.type = "button";
      button.setAttribute("aria-pressed", String(day === state.day));
      // always two lines: "Today" / "Mon, 10/12", "Wednesday" / "Wed, 10/14"
      button.append(element("strong", dayName(day)), element("small", dayLabel(day, today(Date.now()), language).date));
      button.addEventListener("click", () => update({ day }));
      return button;
    }),
  );
  const parts = document.getElementById("parts");
  parts.setAttribute("aria-label", t("tv.part"));
  parts.replaceChildren(
    ...PARTS.map((part) => {
      const button = element("button", null);
      button.type = "button";
      button.setAttribute("aria-pressed", String(part === state.part));
      button.append(element("span", t(`part.${part}`)), element("small", HOURS[part]));
      button.addEventListener("click", () => update({ part }));
      return button;
    }),
  );
  for (const scope of ["day", "week"]) {
    const button = document.getElementById(`play-${scope}`);
    button.textContent = playing === scope ? t("tv.pause") : t(`tv.play.${scope}`);
    button.setAttribute("aria-pressed", String(playing === scope));
    button.title = t(`tv.playHint.${scope}`);
  }
}

// --- what: values at the markers and the map colour (box on the map) ------------------
function renderShow() {
  const values = document.getElementById("values");
  values.replaceChildren(
    ...LAYERS.map((layer) => {
      const label = element("label", null, "check");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = state.shown.includes(layer);
      box.addEventListener("change", () => {
        const shown = box.checked ? [...state.shown, layer] : state.shown.filter((l) => l !== layer);
        update({ shown: LAYERS.filter((l) => shown.includes(l)) });
      });
      label.append(box, glyph(layer), element("span", t(`layer.${layer}`)));
      return label;
    }),
  );
  const colours = document.getElementById("colours");
  colours.replaceChildren(
    ...COLOURS.map((colour) => {
      const label = element("label", null, "check");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "colour";
      radio.checked = colour === state.colour;
      radio.addEventListener("change", () => update({ colour }));
      label.append(radio, element("span", t(`layer.${colour}`)));
      return label;
    }),
  );
  renderScale();
}

function renderScale() {
  const box = document.getElementById("scale");
  const ramp = RAMPS[state.colour];
  if (!ramp) {
    box.replaceChildren();
    return;
  }
  const [low, high] = [ramp[0][0], ramp.at(-1)[0]];
  const stops = ramp.map(([v]) => `${colorFor(v, state.colour)} ${((v - low) / (high - low)) * 100}%`);
  const bar = element("div", null, "bar");
  bar.style.background = `linear-gradient(to right, ${stops.join(", ")})`;
  const show = (v) =>
    ({ temperature: `${v}°`, precipitation: `${v * 100} %`, wind: `${v} m/s`, cloud: `${v} %` })[state.colour];
  box.replaceChildren(
    element("div", t(`scale.${state.colour}`), "scale-title"),
    bar,
    element("div", `${show(low)} … ${show(high)}`, "scale-ends"),
  );
}

// --- markers: built once, their content updated in place (also between two states) --
const markers = new Map(); // okres → {marker, el, lngLat, canvas, icon, temp, chips}

function markerElement(o) {
  const el = element("button", null, "wx-marker");
  el.type = "button";
  el.title = displayName(o.name);
  const top = element("span", null, "wx-top");
  const canvas = iconCanvas("", 30);
  const temp = element("span", "", "wx-temp");
  top.append(canvas, temp);
  const chipBox = element("span", null, "wx-chips");
  const chips = {};
  for (const layer of LAYERS.filter((l) => l !== "temperature")) {
    const chip = element("span", null, `wx-chip ${layer}`);
    const text = element("span", "");
    chip.append(glyph(layer, 11), text);
    chipBox.append(chip);
    chips[layer] = { chip, text };
  }
  el.append(top, chipBox);
  el.addEventListener("click", (event) => {
    event.stopPropagation();
    update({ okres: o.code });
  });
  return { el, canvas, temp, chips, chipBox, icon: null };
}

/** Show a row (possibly between two states) in a marker. */
function setMarker(entry, row, part, shown) {
  entry.el.style.display = row ? "" : "none";
  if (!row) return;
  const icon = iconName(row.symbol, part, row);
  if (icon !== entry.icon) {
    entry.icon = icon;
    const ctx = entry.canvas.getContext("2d");
    if (icon) drawIcon(ctx, icon, entry.canvas.width);
    else ctx.clearRect(0, 0, entry.canvas.width, entry.canvas.height);
  }
  entry.temp.hidden = !shown.includes("temperature");
  entry.temp.textContent = labelFor(row, "temperature", part);
  let any = false;
  for (const [layer, { chip, text }] of Object.entries(entry.chips)) {
    chip.hidden = !shown.includes(layer);
    any ||= !chip.hidden;
    text.textContent = labelFor(row, layer, part);
  }
  entry.chipBox.hidden = !any;
}

function buildMarkers(outlook) {
  for (const o of outlook.okresy) {
    const parts = markerElement(o);
    const marker = new Marker({ element: parts.el }).setLngLat([o.lon, o.lat]).addTo(map);
    markers.set(o.code, { ...parts, marker, lngLat: [o.lon, o.lat] });
  }
}

function paintMarkers(outlook) {
  for (const [code, entry] of markers) {
    setMarker(entry, rowFor(outlook, code, state.day, state.part), state.part, state.shown);
  }
  declutter();
}

function declutter() {
  const boxes = [...markers]
    .filter(([, m]) => m.el.style.display !== "none")
    .map(([code, m]) => {
      m.el.hidden = false;
      const p = map.project(m.lngLat);
      return { code, x: p.x, y: p.y, w: m.el.offsetWidth, h: m.el.offsetHeight };
    });
  const shown = placeMarkers(boxes, 4, state.okres);
  for (const [code, m] of markers) {
    m.el.hidden = !shown.has(code);
    m.el.classList.toggle("selected", code === state.okres);
  }
}

// --- headline: follows the values shown --------------------------------------------
function renderHeadline(outlook) {
  const s = summary(outlook, state.day, state.part);
  const box = document.getElementById("headline");
  if (!s) {
    box.replaceChildren(element("p", t("tv.noPart")));
    return;
  }
  const line = (layer, text) => {
    const p = element("p", null, "line");
    p.append(glyph(layer), element("span", text));
    return p;
  };
  const lines = [];
  const shown = (l) => state.shown.includes(l) || state.colour === l;
  // temperature also when nothing else is chosen
  if (shown("temperature") || !LAYERS.some(shown)) {
    const warm = line("temperature", t("tv.warmest", { okres: displayName(s.warmest.name), value: fmt(s.warmest.value) }));
    const cold = line("temperature", t("tv.coldest", { okres: displayName(s.coldest.name), value: fmt(s.coldest.value) }));
    // at night the coldest place comes first
    lines.push(...(state.part === "night" ? [cold, warm] : [warm, cold]));
  }
  if (shown("precipitation")) lines.push(line("precipitation", t("tv.rainy", { n: s.rainy, of: s.okresy })));
  if (shown("wind")) lines.push(line("wind", t("tv.windiest", { okres: displayName(s.windiest.name), value: fmt(s.windiest.value) })));
  if (shown("cloud")) lines.push(line("cloud", t("tv.clearIn", { n: s.clear, of: s.okresy })));
  // the day's sunrise and sunset, earliest to latest over the okresy (about 25 minutes apart)
  const sun = sunRange(outlook, state.day);
  if (sun) {
    for (const [key, times] of [["sunrise", sun.sunrise], ["sunset", sun.sunset]]) {
      const p = line(key, t(`tv.${key}`, { time: rangeText(times) }));
      p.title = t("tv.sunRange", { rise: rangeText(sun.sunrise), set: rangeText(sun.sunset) });
      lines.push(p);
    }
  }
  const heading = element("h2", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`);
  const children = [heading, ...lines];
  if (playing && RAMPS[state.colour]) {
    // while playing the map colour changes every round: say which one it is
    const badge = element("p", null, "playing");
    badge.append(glyph(state.colour), element("span", t("tv.mapShows", { layer: t(`layer.${state.colour}`) })));
    children.splice(1, 0, badge);
  }
  box.replaceChildren(...children);
}

// --- okres panel ------------------------------------------------------------------
function partCell(row, part) {
  const cell = element("div", null, "part");
  cell.append(
    element("span", t(`part.${part}`), "part-name"),
    iconCanvas(row ? iconName(row.symbol, part, row) : "", 34, symbolText(row?.symbol)),
    element("strong", row ? labelFor(row, "temperature", part) : "–"),
    element("span", row ? percent(row.rain_probability) : "", "rain"),
  );
  return cell;
}

// the day's strongest wind and, where the single runs reach, its strongest gust
function windCell(row) {
  if (!row) return element("td", "", "num");
  if (row.gust == null) return element("td", `${fmt(row.wind)} m/s`, "num");
  const td = element("td", `${fmt(row.wind)} / ${fmt(row.gust)} m/s`, row.gust_warning ? "num gust-warning" : "num");
  td.title = t("tv.windGustCell");
  return td;
}

function renderPanel(outlook) {
  const panel = document.getElementById("okres-panel");
  if (!state.okres) {
    panel.replaceChildren();
    return;
  }
  const info = outlook.okresy.find((o) => o.code === state.okres);
  const now = rowFor(outlook, state.okres, state.day, state.part);
  const close = element("button", "×", "close");
  close.type = "button";
  close.setAttribute("aria-label", t("chart.close"));
  close.addEventListener("click", () => update({ okres: null }));
  const big = element("div", null, "now");
  big.append(
    iconCanvas(now ? iconName(now.symbol, state.part, now) : "", 64, symbolText(now?.symbol)),
    element("div", now ? labelFor(now, "temperature", state.part) : "–", "big-temp"),
  );
  const facts = element("ul", null, "facts");
  if (now) {
    for (const text of [
      symbolText(now.symbol),
      t("tv.range", { low: fmt(now.tmin), high: fmt(now.tmax) }),
      t("tv.rain", { chance: percent(now.rain_probability), amount: fmt(now.precipitation, 1) }),
      // gusts from the single runs: null beyond the newest run and in older files
      now.gust != null ? t("tv.windGust", { value: fmt(now.wind), gust: fmt(now.gust) }) : t("tv.wind", { value: fmt(now.wind) }),
      t("tv.cloud", { value: fmt(now.cloud) }),
    ]) {
      facts.append(element("li", text));
    }
    if (now.gust_warning) facts.append(element("li", t("tv.gustWarning"), "gust-warning"));
  }
  const sun = sunFor(outlook, state.okres, state.day);
  if (sun) {
    // the whole day's, whatever part is shown
    const li = element("li");
    li.append(sunLine(sun.sunrise, sun.sunset, "tv.sun"));
    facts.append(li);
  }
  const strip = element("div", null, "strip");
  strip.append(...PARTS.slice(0, 4).map((p) => partCell(rowFor(outlook, state.okres, state.day, p), p)));
  const week = element("table", null, "week");
  for (const day of outlook.days) {
    const row = rowFor(outlook, state.okres, day, "day");
    const tr = element("tr");
    if (day === state.day) tr.className = "current";
    tr.addEventListener("click", () => update({ day }));
    const iconCell = element("td");
    iconCell.append(iconCanvas(row ? iconName(row.symbol, "day", row) : "", 26, symbolText(row?.symbol)));
    tr.append(
      element("td", dayText(day)),
      iconCell,
      element("td", row ? `${fmt(row.tmax)}° / ${fmt(row.tmin)}°` : "–", "num"),
      element("td", row ? percent(row.rain_probability) : "", "num rain"),
      windCell(row),
    );
    week.append(tr);
  }
  const detail = element("a", t("tv.detail"));
  detail.href = `forecast.html#${state.okres}`;
  panel.replaceChildren(
    close,
    element("h2", displayName(info?.name ?? state.okres)),
    element("p", `${dayText(state.day)}, ${t(`part.${state.part}`).toLowerCase()}`, "when"),
    big,
    facts,
    strip,
    week,
    detail,
  );
}

// --- update loop ------------------------------------------------------------------
let outlook = null;
let padding = null;

/** Fit Czechia beside the okres panel on wide screens, and back when it closes. */
function fitView() {
  const right = window.innerWidth > 900 && state.okres ? document.getElementById("okres-panel").offsetWidth + 70 : 20;
  if (padding && padding.right === right) return;
  const first = padding === null;
  padding = { top: 20, bottom: 20, left: 20, right };
  map.fitBounds(BOUNDS, { padding, duration: first ? 0 : 400 });
}

function paintFill(colours) {
  const pairs = [...colours].flat();
  map.setPaintProperty("okresy-fill", "fill-color", pairs.length ? ["match", ["get", "code"], ...pairs, NEUTRAL] : NEUTRAL);
}

/** Draw the current state at once (after a click, or at the end of a transition). */
function update(change = {}, fromPlay = false) {
  if (!fromPlay) stopPlay();
  state = { ...state, ...change };
  window.history.replaceState(null, "", viewHash(state));
  renderWhen(outlook);
  renderShow();
  paintFill(okresColours(outlook, state.day, state.part, state.colour));
  map.setFilter("okres-selected", ["==", ["get", "code"], state.okres ?? ""]);
  paintMarkers(outlook);
  renderHeadline(outlook);
  renderPanel(outlook);
  fitView();
}

// --- play: smooth transitions through the parts of a day (or of every day), each
// round with the next map colour -----------------------------------------------------
const TRANSITION_MS = 1100;
// a change of the map colour (another value) is quicker
const SWITCH_MS = 500;
const HOLD_MS = 1400;
let playToken = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function stopPlay() {
  if (!playing) return;
  playing = null;
  playToken += 1;
  renderWhen(outlook);
  renderHeadline(outlook);
}

/** Move to `target` (a part of state), interpolating colours and values; false if stopped. */
async function transition(target, token) {
  const from = { ...state };
  const to = { ...state, ...target };
  const coloursFrom = okresColours(outlook, from.day, from.part, from.colour);
  const coloursTo = okresColours(outlook, to.day, to.part, to.colour);
  // the labels and boxes already show where we are going
  state = to;
  renderWhen(outlook);
  renderShow();
  renderHeadline(outlook);
  const start = performance.now();
  for (;;) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    if (token !== playToken) return false;
    const elapsed = performance.now() - start;
    const f = ease(Math.min(1, elapsed / TRANSITION_MS));
    // the same value: colours move smoothly; another value: a quick fade through the
    // background, so the two are never mixed
    paintFill(
      from.colour === to.colour
        ? new Map([...coloursTo].map(([code, c]) => [code, mixColor(coloursFrom.get(code) ?? c, c, f)]))
        : switchColours(coloursFrom, coloursTo, Math.min(1, elapsed / SWITCH_MS)),
    );
    for (const [code, entry] of markers) {
      const row = lerpRow(rowFor(outlook, code, from.day, from.part), rowFor(outlook, code, to.day, to.part), f);
      setMarker(entry, row, f < 0.5 ? from.part : to.part, to.shown);
    }
    if (f >= 1) break;
  }
  update({}, true);
  return true;
}

/**
 * Play the parts of the shown day ("day") or of every day ("week"), from the part shown
 * now; after each round start again with the next map colour (temperature → rain →
 * wind → cloud → temperature), which is then also shown at the okresy.
 */
async function play(scope) {
  stopPlay();
  playing = scope;
  const token = ++playToken;
  const chosen = state.shown;
  const steps = playSteps(outlook, scope, state.day);
  if (steps.length === 0) return stopPlay();
  let i = startIndex(steps, state.day, state.part);
  renderWhen(outlook);
  if (!(await transition(steps[i], token))) return;
  for (;;) {
    await sleep(HOLD_MS);
    if (token !== playToken) return;
    i += 1;
    let target = steps[i % steps.length];
    if (i % steps.length === 0) {
      const colour = nextColour(state.colour);
      target = { ...target, colour, shown: LAYERS.filter((l) => chosen.includes(l) || l === colour) };
    }
    if (!(await transition(target, token))) return;
  }
}

function togglePlay(scope) {
  if (playing === scope) stopPlay();
  else play(scope);
}

function addLayers() {
  map.addSource("okresy", { type: "geojson", data: "data/okresy.geojson" });
  map.addSource("kraje", { type: "geojson", data: "data/kraje.geojson" });
  map.addLayer({ id: "okresy-fill", type: "fill", source: "okresy", paint: { "fill-color": "#ececec", "fill-opacity": 0.85 } });
  map.addLayer({ id: "okresy-line", type: "line", source: "okresy", paint: { "line-color": "#ffffff", "line-width": 0.6 } });
  map.addLayer({ id: "kraje-line", type: "line", source: "kraje", paint: { "line-color": "#4b5863", "line-width": 1.2 } });
  map.addLayer({
    id: "okres-selected",
    type: "line",
    source: "okresy",
    filter: ["==", ["get", "code"], ""],
    paint: { "line-color": "#1d2329", "line-width": 2.5 },
  });
  map.on("click", "okresy-fill", (event) => update({ okres: event.features[0].properties.code }));
  map.on("mouseenter", "okresy-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "okresy-fill", () => (map.getCanvas().style.cursor = ""));
  map.on("moveend", declutter);
}

async function main() {
  outlook = parseOutlook(await getJson("data/scores/outlook.json"));
  const status = document.getElementById("status");
  if (outlook.okresy.length === 0) {
    status.textContent = t("tv.none");
    return;
  }
  const generated = outlook.generated ? new Date(outlook.generated) : null;
  status.textContent = generated && !Number.isNaN(generated.getTime())
    ? t("tv.updated", {
      time: new Intl.DateTimeFormat(language, { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague" }).format(generated),
    })
    : "";
  const now = Date.now();
  const first = outlook.days.includes(today(now)) ? today(now) : outlook.days[0];
  state = parseView(window.location.hash, outlook, {
    day: first,
    part: first === today(now) ? currentPart(now) : "afternoon",
  });
  // phones: the box starts folded so the map stays visible
  const show = document.getElementById("show");
  if (window.innerWidth <= 700) show.open = false;
  document.getElementById("play-day").addEventListener("click", () => togglePlay("day"));
  document.getElementById("play-week").addEventListener("click", () => togglePlay("week"));
  await mapLoaded;
  addLayers();
  buildMarkers(outlook);
  update();
}

main();
