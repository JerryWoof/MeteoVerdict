import * as Plot from "@observablehq/plot";

import { seriesRows } from "./series.js";

/**
 * Line chart of each model's daily MAE at one station (7-day moving average),
 * or a note when there is nothing to draw.
 */
export function stationChart(doc, view, colors, names) {
  const rows = seriesRows(doc, view.variable, view.leadDay);
  if (rows.length === 0) {
    const note = document.createElement("p");
    note.textContent =
      view.leadDay > 2
        ? "Daily errors are published for D+1 and D+2 only."
        : "No daily errors for this station and variable in the last 90 days.";
    return note;
  }
  const models = [...new Set(rows.map((r) => r.model))];
  return Plot.plot({
    width: 360,
    height: 220,
    marginLeft: 40,
    y: { label: "MAE (7-day mean)", grid: true, zero: true },
    x: { label: null },
    color: {
      domain: models.map((m) => names[m] ?? m),
      range: models.map((m) => colors[m] ?? "#888888"),
      legend: true,
    },
    marks: [
      Plot.lineY(
        rows,
        Plot.windowY(
          { k: 7, anchor: "end" },
          { x: "date", y: "mae", stroke: (r) => names[r.model] ?? r.model, tip: true },
        ),
      ),
    ],
  });
}
