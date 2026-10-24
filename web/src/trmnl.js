// The URLs of the okres and obec files of api/v1.

export const SITE = "https://meteoverdict.cz/api/v1";
export const FORECASTS = ["okresy", "ai/okresy"];

/** The resolved forecast file of one okres: forecast is "okresy" (combined) or "ai/okresy". */
export function forecastUrl(forecast, okres) {
  return `${SITE}/${FORECASTS.includes(forecast) ? forecast : "okresy"}/${okres}.json`;
}

/** The obec file of one obec: from the AI (forecast "ai/okresy") or the combination. */
export function obecUrl(okres, id, forecast = "okresy") {
  return `${SITE}/${forecast === "ai/okresy" ? "ai/obce" : "obce"}/${okres}/${id}.json`;
}

/** The obce of one okres from the index, sorted by name; an obec is { id, name }. */
export function obceOf(index, okres) {
  return (index?.obce ?? [])
    .filter((row) => row[0] === okres)
    .map((row) => ({ id: row[1], name: row[2] }))
    .sort((a, b) => a.name.localeCompare(b.name, "cs"));
}
