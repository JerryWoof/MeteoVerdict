// Text for the status line, from site/data/meta.json (written by `mvd aggregate`).

/** @param {null | {generated?: string, as_of?: string}} meta */
export function statusText(meta) {
  if (!meta || !meta.as_of) {
    return "No scores yet: the daily pipeline fills the map as the history is backfilled.";
  }
  const updated = meta.generated ? meta.generated.slice(0, 10) : "?";
  return `Scores up to ${meta.as_of} · updated ${updated}`;
}
