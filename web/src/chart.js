import * as Plot from "@observablehq/plot";

import { HOME_MODEL } from "./compare.js";
import { seriesRows } from "./series.js";

/**
 * Line chart of each model's daily MAE at one station (7-day moving average),
 * or a note when there is nothing to draw.
 */
export function stationChart(doc, view, colors, names, t, preferred = null) {
  const all = seriesRows(doc, view.variable, view.leadDay);
  // the 3 best models and the default one, so the chart stays readable
  const total = new Map();
  for (const r of all) {
    const c = total.get(r.model) ?? { sum: 0, n: 0 };
    total.set(r.model, { sum: c.sum + r.mae, n: c.n + 1 });
  }
  // `preferred`: the okres's best models, when the station was opened from an okres; else the station's own best
  const own = [...total].filter(([m, c]) => m !== "blend" && c.n >= 7).sort((x, y) => x[1].sum / x[1].n - y[1].sum / y[1].n).map(([m]) => m);
  const top = new Set((preferred?.filter((m) => total.has(m)).length ? preferred.filter((m) => total.has(m)) : own).slice(0, 3));
  // the default model (ČHMÚ ALADIN 1 km) is always drawn, when the station has it
  if (total.has(HOME_MODEL)) top.add(HOME_MODEL);
  const rows = all.filter((r) => top.has(r.model));
  if (rows.length === 0) {
    const note = document.createElement("p");
    note.textContent = t(view.leadDay > 2 ? "chart.leadNote" : "chart.empty");
    return note;
  }
  const nameOf = (m) => (m === "blend" ? t("model.blend") : (names[m] ?? m));
  const colorOf = (m) => (m === "blend" ? "#8a8f94" : (colors[m] ?? "#888888"));
  const box = document.createElement("div");
  box.className = "station-chart";
  const caption = document.createElement("p");
  caption.className = "muted small";
  caption.textContent = t("chart.desc");
  const width = Math.max(280, Math.round((document.getElementById("detail")?.clientWidth ?? 360) - 2 * 0.9 * 16));
  const plot = Plot.plot({
    width,
    height: 230,
    marginLeft: 30,
    marginRight: 8,
    marginTop: 8,
    style: { fontSize: "11px", background: "transparent" },
    y: { label: null, grid: true, zero: true },
    x: { label: null, ticks: 4, tickFormat: (d) => d.toLocaleDateString(undefined, { month: "short" }) },
    marks: [
      Plot.lineY(
        rows,
        Plot.windowY(
          { k: 7, anchor: "end" },
          {
            x: "date", y: "mae", z: "model", curve: "monotone-x",
            stroke: (r) => colorOf(r.model),
            strokeWidth: (r) => (r.model === "blend" ? 1.4 : 2),
            strokeDasharray: (r) => (r.model === "blend" ? "4,3" : null),
            channels: { Model: (r) => nameOf(r.model) },
            tip: true,
          },
        ),
      ),
    ],
  });
  // the legend: the models by their mean error over the period (best first), with the number
  const list = document.createElement("ol");
  list.className = "rank-list";
  const mean = (m) => total.get(m)?.sum / total.get(m)?.n;
  const order = [...new Set(rows.map((r) => r.model))].filter((m) => m !== "blend").sort((x, y) => mean(x) - mean(y));
  if (rows.some((r) => r.model === "blend")) order.push("blend");
  order.forEach((m, i) => {
    const li = document.createElement("li");
    const cell = (text, cls) => {
      const e = document.createElement("span");
      e.textContent = text;
      if (cls) e.className = cls;
      return e;
    };
    const dot = cell("", "swatch");
    dot.style.background = colorOf(m);
    const best = mean(order[0]);
    li.append(cell(m === "blend" ? "" : String(i + 1), "pos"), dot, cell(nameOf(m), "name"), cell(mean(m).toFixed(2), "val"), cell(i === 0 || m === "blend" ? "" : `+${(mean(m) - best).toFixed(2)}`, "gap muted"));
    if (i === 0) li.className = "best";
    list.append(li);
  });
  box.append(caption, plot, list);
  return box;
}
