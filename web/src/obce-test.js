// Test (forecast for a place): the forecast for every obec of an okres that has one
// (obce.zip, Litoměřice for now), shown on the forecast page in place of the
// okres's. One file per okres: data/scores/forecast/obce-<code>.json.

const docs = new Map();

// the okres's obce file, or null where there is none (fetched once per okres)
export function obceFor(code, getJson) {
  if (!docs.has(code)) docs.set(code, getJson(`data/scores/forecast/obce-${code}.json`));
  return docs.get(code);
}

// the hours as ms, like models.js's parsed times
export function obecTimes(doc) {
  return doc.times.map((s) => Date.parse(s));
}

export function placeOf(doc, name) {
  return doc?.places?.find((p) => p.name === name) ?? null;
}

// the page's `forecast` (every model's temperature; rain and wind only combined) and
// `combined` series for one obec
export function obecSeries(doc, place) {
  return {
    forecast: {
      times: obecTimes(doc),
      values: { temperature_2m: place.models ?? {}, precipitation: {}, wind_speed_10m: {} },
    },
    combined: {
      temperature_2m: place.temperature_2m,
      precipitation: place.precipitation,
      wind_speed_10m: place.wind_speed_10m,
    },
  };
}

// the picker: "whole okres" first, then the obce by name
export function fillObce(select, doc, chosen, wholeLabel) {
  const option = (value, text) => {
    const element = document.createElement("option");
    element.value = value;
    element.textContent = text;
    element.selected = value === (chosen ?? "");
    return element;
  };
  const names = (doc?.places ?? []).map((p) => p.name).sort((a, b) => a.localeCompare(b, "cs"));
  select.replaceChildren(option("", wholeLabel), ...names.map((n) => option(n, n)));
}
