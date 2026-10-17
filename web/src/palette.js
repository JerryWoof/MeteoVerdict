// The colour scales of the maps and their legend: one palette for the forecast map
// (tv.html, tv-page.js) and the measured page (station.html: okres fills and station
// dots, measured-map-view.js, station-page.js), so a value has the same colour on both.

// colour ramps: [value, [r, g, b]] in ascending order
const WIND = [[0, [244, 241, 234]], [4, [199, 233, 192]], [8, [116, 196, 118]], [14, [35, 139, 69]], [20, [0, 68, 27]]];
const CLOUD = [[0, [254, 240, 180]], [50, [220, 220, 215]], [100, [150, 150, 150]]];
/** A gust is about 1.4 times the hourly wind it comes with (gust factor over land). */
export const GUST_FACTOR = 1.4;
/** Hours of sunshine for the clear end of the sunshine scale (a whole part of the day). */
export const SUNNY_HOURS = 6;

export const RAMPS = {
  temperature: [
    [-15, [49, 54, 149]], [-5, [69, 117, 180]], [0, [171, 217, 233]], [5, [224, 243, 248]],
    [10, [254, 224, 144]], [15, [253, 174, 97]], [20, [244, 109, 67]], [25, [215, 48, 39]],
    [32, [165, 0, 38]],
  ],
  precipitation: [[0, [244, 241, 234]], [0.3, [198, 219, 239]], [0.6, [107, 174, 214]], [1, [8, 81, 156]]],
  wind: WIND,
  cloud: CLOUD,
  // a single model's rain total (mm): no probability from one model; also what was measured
  precipitationMm: [[0, [244, 241, 234]], [0.3, [198, 219, 239]], [2, [107, 174, 214]], [10, [8, 81, 156]]],
  // measured only (the forecast map has neither), derived in the forecast's style:
  // the strongest gust takes the wind's colours at GUST_FACTOR times its stops
  gust: WIND.map(([v, rgb]) => [Math.round(v * GUST_FACTOR), rgb]),
  // sunshine the cloud scale turned round: no sun the overcast grey, SUNNY_HOURS and
  // more the clear sky's pale yellow (the sun symbols stay readable on it)
  sunshine: CLOUD.map(([v, rgb]) => [((100 - v) / 100) * SUNNY_HOURS, rgb]).reverse(),
};

/** The colour ramp of a layer: rain in mm for a single model's view and what was measured. */
export const rampKey = (layer, mm) => (layer === "precipitation" && mm ? "precipitationMm" : layer);

/** Fill of an okres without a value (beyond a single model's horizon; nothing measured). */
export const BEYOND = "#c9c9c9";

export const NEUTRAL = "#e9e5db";

const hex = (rgb) => `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;

/** Linear interpolation in a ramp, clamped at its ends. */
export function colorFor(value, layer) {
  const ramp = RAMPS[layer];
  if (value == null) return "#ececec";
  if (value <= ramp[0][0]) return hex(ramp[0][1]);
  for (let i = 1; i < ramp.length; i += 1) {
    const [v1, c1] = ramp[i];
    if (value <= v1) {
      const [v0, c0] = ramp[i - 1];
      const f = (value - v0) / (v1 - v0);
      return hex(c0.map((c, k) => c + f * (c1[k] - c)));
    }
  }
  return hex(ramp.at(-1)[1]);
}

/** A value at the ends of a scale: "-15°", "100 %" (rain probability 0–1), "10 mm". */
export function scaleValue(key, v) {
  if (key === "temperature") return `${v}°`;
  if (key === "precipitation") return `${Math.round(v * 100)} %`;
  const unit = { precipitationMm: "mm", wind: "m/s", gust: "m/s", sunshine: "h", cloud: "%" }[key];
  return `${v} ${unit}`;
}

/** The legend's bar and ends for a ramp: {gradient (CSS), ends ("-15° … 32°")}, or null. */
export function scale(key) {
  const ramp = RAMPS[key];
  if (!ramp) return null;
  const [low, high] = [ramp[0][0], ramp.at(-1)[0]];
  const stops = ramp.map(([v]) => `${colorFor(v, key)} ${((v - low) / (high - low)) * 100}%`);
  return {
    gradient: `linear-gradient(to right, ${stops.join(", ")})`,
    ends: `${scaleValue(key, low)} … ${scaleValue(key, high)}`,
  };
}

/** Fill a legend box (#scale) with a ramp's title, bar and ends; empty without a ramp. */
export function renderScale(box, key, title) {
  const s = scale(key);
  if (!s) {
    box.replaceChildren();
    return;
  }
  const make = (className, text) => {
    const e = document.createElement("div");
    e.className = className;
    if (text != null) e.textContent = text;
    return e;
  };
  const bar = make("bar");
  bar.style.background = s.gradient;
  box.replaceChildren(make("scale-title", title), bar, make("scale-ends", s.ends));
}
