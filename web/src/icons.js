// Weather symbols drawn on a canvas (no image files, no third-party icon set).
// Names: clear, partly, cloudy, showers, rain, sleet, snow, and clear-night,
// partly-night, showers-night with a moon instead of the sun.

const SUN = "#f2b01e";
const MOON = "#e7c95a";
const CLOUD = "#ffffff";
const CLOUD_DARK = "#c9ced3";
const OUTLINE = "#7b8791";
const RAIN = "#2b7bd1";
const SNOW = "#6aa9d8";

export const ICONS = [
  "clear", "partly", "cloudy", "showers", "rain", "sleet", "snow",
  "clear-night", "partly-night", "showers-night",
];

function sun(ctx, x, y, r) {
  ctx.strokeStyle = SUN;
  ctx.lineWidth = r * 0.22;
  ctx.lineCap = "round";
  for (let i = 0; i < 8; i += 1) {
    const a = (i * Math.PI) / 4;
    ctx.beginPath();
    ctx.moveTo(x + Math.cos(a) * r * 1.3, y + Math.sin(a) * r * 1.3);
    ctx.lineTo(x + Math.cos(a) * r * 1.75, y + Math.sin(a) * r * 1.75);
    ctx.stroke();
  }
  ctx.fillStyle = SUN;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fill();
}

function moon(ctx, x, y, r) {
  // a disc with an offset disc cut out of it (drawn first, before any cloud)
  ctx.save();
  ctx.fillStyle = MOON;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fill();
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.arc(x + r * 0.55, y - r * 0.35, r * 0.8, 0, 2 * Math.PI);
  ctx.fill();
  ctx.restore();
}

function cloud(ctx, x, y, w, dark) {
  // x, y: centre of the cloud's base; w: width
  const h = w * 0.32;
  ctx.beginPath();
  ctx.moveTo(x - w / 2 + h / 2, y);
  ctx.arc(x - w / 2 + h / 2, y - h / 2, h / 2, Math.PI / 2, (3 * Math.PI) / 2);
  ctx.arc(x - w * 0.12, y - h * 0.95, w * 0.2, Math.PI, 1.85 * Math.PI);
  ctx.arc(x + w * 0.17, y - h * 0.85, w * 0.16, 1.25 * Math.PI, 2 * Math.PI);
  ctx.arc(x + w / 2 - h / 2, y - h / 2, h / 2, (3 * Math.PI) / 2, Math.PI / 2);
  ctx.closePath();
  ctx.fillStyle = dark ? CLOUD_DARK : CLOUD;
  ctx.fill();
  ctx.strokeStyle = OUTLINE;
  ctx.lineWidth = w * 0.035;
  ctx.stroke();
}

function drops(ctx, x, y, s, n) {
  ctx.strokeStyle = RAIN;
  ctx.lineWidth = s * 0.06;
  ctx.lineCap = "round";
  for (let i = 0; i < n; i += 1) {
    const dx = x + (i - (n - 1) / 2) * s * 0.2;
    ctx.beginPath();
    ctx.moveTo(dx + s * 0.04, y);
    ctx.lineTo(dx - s * 0.04, y + s * 0.16);
    ctx.stroke();
  }
}

function flake(ctx, x, y, r) {
  ctx.strokeStyle = SNOW;
  ctx.lineWidth = r * 0.3;
  ctx.lineCap = "round";
  for (let i = 0; i < 3; i += 1) {
    const a = (i * Math.PI) / 3;
    ctx.beginPath();
    ctx.moveTo(x - Math.cos(a) * r, y - Math.sin(a) * r);
    ctx.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r);
    ctx.stroke();
  }
}

/** Draw one symbol filling a size × size square. */
export function drawIcon(ctx, name, size) {
  const s = size;
  ctx.clearRect(0, 0, s, s);
  const night = name.endsWith("-night");
  const base = night ? name.slice(0, -6) : name;
  const sky = night ? moon : sun;
  if (base === "clear") {
    sky(ctx, s / 2, s / 2, s * (night ? 0.3 : 0.22));
    return;
  }
  if (base === "partly" || base === "showers") {
    sky(ctx, s * 0.36, s * 0.34, s * (night ? 0.2 : 0.15));
    cloud(ctx, s * 0.56, base === "showers" ? s * 0.66 : s * 0.78, s * 0.66, false);
    if (base === "showers") drops(ctx, s * 0.56, s * 0.74, s, 2);
    return;
  }
  const wet = base !== "cloudy";
  cloud(ctx, s / 2, wet ? s * 0.6 : s * 0.72, s * 0.84, wet);
  if (base === "rain") drops(ctx, s / 2, s * 0.68, s, 3);
  if (base === "snow") {
    flake(ctx, s * 0.36, s * 0.8, s * 0.07);
    flake(ctx, s * 0.64, s * 0.8, s * 0.07);
  }
  if (base === "sleet") {
    drops(ctx, s * 0.4, s * 0.68, s, 1);
    flake(ctx, s * 0.62, s * 0.8, s * 0.07);
  }
}

/** A canvas with the symbol, for the page (not the map). */
export function iconCanvas(name, cssSize, label) {
  const ratio = globalThis.devicePixelRatio ?? 1;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = Math.round(cssSize * ratio);
  canvas.style.width = canvas.style.height = `${cssSize}px`;
  canvas.setAttribute("role", "img");
  if (label) canvas.setAttribute("aria-label", label);
  if (name) drawIcon(canvas.getContext("2d"), name, canvas.width);
  return canvas;
}

/** Register every symbol as a MapLibre image (drawn at twice the size for sharpness). */
export function addIcons(map, cssSize = 30) {
  const size = cssSize * 2;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  for (const name of ICONS) {
    drawIcon(ctx, name, size);
    map.addImage(name, ctx.getImageData(0, 0, size, size), { pixelRatio: 2 });
  }
}

// Small glyphs for the four values (controls, marker chips, panel), as inline SVG.
const GLYPHS = {
  temperature: {
    color: "#d0452b",
    paths: [
      "M10 3a2 2 0 0 1 4 0v10.3a4.5 4.5 0 1 1-4 0z",
      "M12 9v7",
    ],
  },
  precipitation: { color: "#2b7bd1", paths: ["M12 3c3 4.5 5.5 7.6 5.5 11a5.5 5.5 0 0 1-11 0C6.5 10.6 9 7.5 12 3z"] },
  wind: { color: "#2f8a4a", paths: ["M3 9h11a3 3 0 1 0-3-3", "M3 14h15a3 3 0 1 1-3 3", "M3 19h7"] },
  cloud: { color: "#6f7a83", paths: ["M7 18h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 18z"] },
  // measured on the past days: the strongest gust (wind with a burst) and sunshine
  gust: { color: "#1f6b3a", paths: ["M3 8h8a3 3 0 1 0-3-3", "M3 13h12a3 3 0 1 1-3 3", "M18 4l-2 6h4l-2 6"] },
  sunshine: {
    color: "#d98a0b",
    paths: [
      "M12 8.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7z", "M12 2.5v2", "M12 19.5v2", "M2.5 12h2", "M19.5 12h2",
      "M5.3 5.3l1.4 1.4", "M17.3 17.3l1.4 1.4", "M5.3 18.7l1.4-1.4", "M17.3 6.7l1.4-1.4",
    ],
  },
  // half a sun on the horizon, with an arrow up or down
  sunrise: { color: "#d98a0b", paths: ["M2 20h20", "M6.5 20a5.5 5.5 0 0 1 11 0", "M12 11V3", "M9 6l3-3 3 3"] },
  sunset: { color: "#c0632b", paths: ["M2 20h20", "M6.5 20a5.5 5.5 0 0 1 11 0", "M12 3v8", "M9 8l3 3 3-3"] },
};

/** An inline SVG glyph for a value ("temperature", "precipitation", "wind", "cloud", and
 * the measured "gust" and "sunshine"), or for "sunrise" and "sunset". */
export function glyph(layer, size = 14) {
  const spec = GLYPHS[layer];
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("glyph");
  for (const d of spec.paths) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    const colour = `var(--glyph-${layer},${spec.color})`;
    const filled = layer === "precipitation" || layer === "cloud";
    // the dark theme can lighten a glyph with --glyph-<layer> (light mode keeps its colour)
    path.setAttribute("style", `fill:${filled ? colour : "none"};stroke:${colour}`);
    path.setAttribute("stroke-width", "2");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.append(path);
  }
  return svg;
}

export const glyphColor = (layer) => GLYPHS[layer].color;
