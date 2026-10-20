// The "Forecast" selector of the detailed forecast page and of the okres panel on the
// forecast map: our combination first, then the models by their mean rank in the okres,
// then the models without scores there (forecast.js modelOptions).

import { COMBINED, modelOptions } from "./forecast.js";
import { AI_MODEL } from "./ai-model.js";

function optionText(o, names, t) {
  if (o.model === COMBINED) return t("forecast.pickCombined");
  const model = names[o.model] ?? o.model;
  if (!o.scored) return model;
  const rank = o.rank == null
    ? "–"
    : o.rank.toLocaleString(document.documentElement.lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return t("forecast.pickOption", { position: o.position, model, rank });
}

/**
 * Fill `select` with the options for a weight table and the models that have a forecast
 * (`available`, a Set; null: every model of `names`). Returns the selected model: `selected`
 * when it is offered, else the combination.
 */
export function fillPicker(select, { table, names, available, selected, t }) {
  const options = modelOptions(table, names, available);
  // a choice the okres cannot offer (no AI forecast there) falls back to our combination
  const chosen = options.some((o) => o.model === selected) ? selected : COMBINED;
  const option = (o) => {
    const element = document.createElement("option");
    element.value = o.model;
    element.textContent = optionText(o, names, t);
    element.selected = o.model === chosen;
    return element;
  };
  const group = (key, list) => {
    const element = document.createElement("optgroup");
    element.label = t(key);
    element.append(...list.map(option));
    return element;
  };
  const scored = options.filter((o) => o.scored);
  const unscored = options.filter((o) => !o.scored && o.model !== COMBINED && o.model !== AI_MODEL);
  // MeteoVerdict AI (when the okres has it) first, above our combination, in no group
  const ai = options.find((o) => o.model === AI_MODEL);
  select.replaceChildren(
    ...(ai ? [option(ai)] : []),
    option(options[0]),
    ...(scored.length ? [group("forecast.pickScored", scored)] : []),
    ...(unscored.length ? [group("forecast.pickUnscored", unscored)] : []),
  );
  select.value = chosen;
  return chosen;
}

/** "17. 10. 26 6:58": a time in Prague, short, in the page's language. */
export function issuedText(iso) {
  const at = iso ? new Date(iso) : null;
  if (!at || Number.isNaN(at.getTime())) return null;
  return new Intl.DateTimeFormat(document.documentElement.lang, {
    dateStyle: "short", timeStyle: "short", timeZone: "Europe/Prague",
  }).format(at);
}
