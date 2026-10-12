// A station's daily error series (site/data/series/<id>.json, written by
// `mvd aggregate`) as rows for a chart.

/** [{date, model, mae}] for one variable and lead day; days without a score are skipped. */
export function seriesRows(doc, variable, leadDay) {
  const models = doc?.series?.[variable]?.[String(leadDay)];
  if (!models) return [];
  const first = new Date(`${doc.from}T00:00:00Z`);
  const rows = [];
  for (const [model, values] of Object.entries(models)) {
    values.forEach((mae, i) => {
      if (mae == null) return;
      const date = new Date(first.getTime() + i * 86_400_000);
      rows.push({ date, model, mae });
    });
  }
  return rows;
}
