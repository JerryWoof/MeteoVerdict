// The polling-URL builder of the TRMNL section on the Data page.

export const SITE = "https://jerrywoof.github.io/MeteoVerdict/api/v1";
export const TEMPLATE_URL = `${SITE}/{{ forecast_model }}/{{ okres_code }}.json`;
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

/** The lines to paste into TRMNL: the template (the plugin's form picks okres and forecast),
 * or with an obec both files written out, the okres's and the obec's, of the same forecast. */
export function pollingLines(okres, obec, forecast = "okresy") {
  return obec ? [forecastUrl(forecast, okres), obecUrl(okres, obec.id, forecast)] : [TEMPLATE_URL];
}

/** Wires the builder in the page: okresSelect is the page's okres select, t the translator. */
export function setUpBuilder(okresSelect, t, baseUrl = "") {
  const root = document.getElementById("trmnl-builder");
  if (!root) return;
  const forecast = document.getElementById("trmnl-forecast");
  const obecInput = document.getElementById("trmnl-obec");
  const obecList = document.getElementById("trmnl-obce");
  const obecField = document.getElementById("trmnl-obec-field");
  const obecNote = document.getElementById("trmnl-obec-note");
  const output = document.getElementById("trmnl-lines");
  const test = document.getElementById("trmnl-test");
  forecast.replaceChildren(
    ...[["ai/okresy", "api.modelAi"], ["okresy", "api.modelBlend"]].map(([value, key]) =>
      Object.assign(document.createElement("option"), { value, textContent: t(key) })),
  );
  let index; // undefined: not fetched, null: failed
  let obce = [];
  const okres = () => okresSelect.value || "CZ0100";
  const chosen = () => obce.find((o) => o.name === obecInput.value.trim());

  function render() {
    output.textContent = pollingLines(okres(), chosen(), forecast.value).join("\n");
    const url = forecastUrl(forecast.value, okres());
    test.href = url;
    test.textContent = url;
  }
  function fillObce() {
    obce = obceOf(index, okres());
    obecList.replaceChildren(...obce.map((o) =>
      Object.assign(document.createElement("option"), { value: o.name })));
  }
  async function loadIndex() {
    if (index !== undefined) return;
    index = null;
    try {
      const response = await fetch(`${baseUrl}api/v1/obce/index.json`);
      if (response.ok) index = await response.json();
    } catch { /* hidden below */ }
    if (index) fillObce();
    else {
      obecField.hidden = true;
      obecNote.hidden = false;
    }
    render();
  }
  okresSelect.addEventListener("change", () => {
    obecInput.value = "";
    if (index) fillObce();
    render();
  });
  forecast.addEventListener("change", render);
  obecInput.addEventListener("input", render);
  obecInput.addEventListener("focus", loadIndex, { once: true });
  render();
}
