// Text for the status line, from site/data/meta.json (written by `mvd aggregate`).

/**
 * @param {null | {generated?: string, as_of?: string}} meta
 * @param {(key: string, params?: object) => string} t
 */
export function statusText(meta, t) {
  if (!meta || !meta.as_of) return t("status.none");
  const updated = meta.generated ? meta.generated.slice(0, 10) : "?";
  return t("status.scores", { asOf: meta.as_of, updated });
}
