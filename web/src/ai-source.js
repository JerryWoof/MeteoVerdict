// The AI forecast (the forecast page's AI model; old forecast-detail.html?source=ai links): the forecast pages on
// MeteoVerdict AI's forecast instead of our combination. Its files have the same formats
// and relative paths as ours, under data/scores/ai/fc/ (outlook.json, forecast/obce-*.json);
// everything else (meta.json, weights, the models' own forecasts, boundaries) is shared.

/** The files that have an AI version. */
export const AI_FILES = /^data\/scores\/(outlook\.json|forecast\/obce-[^/]+\.json)$/;

/** data/scores/outlook.json → data/scores/ai/fc/outlook.json (other paths unchanged). */
export function aiPath(path) {
  return AI_FILES.test(path) ? path.replace(/^data\/scores\//, "data/scores/ai/fc/") : path;
}

// the texts that name our combination, and their MeteoVerdict AI versions
export const AI_KEYS = {
  "forecast.pickCombined": "ai.pickCombined",
  "tv.bannerBack": "ai.bannerBack",
  "tv.bannerFailed": "ai.bannerFailed",
  "tv.mapModelHint": "ai.mapModelHint",
  "tv.obecNote": "ai.obecNote",
  "tv.none": "ai.fcNone",
  "forecast.note": "ai.detailNote",
  "forecast.legend": "ai.legend",
  "forecast.legendModel": "ai.legendModel",
  "forecast.obecNote": "ai.detailObecNote",
  "forecast.titleFor": "ai.titleFor",
  "forecast.titleForObec": "ai.titleForObec",
};

/** A translator that says "MeteoVerdict AI" where `t` names our combination. */
export function aiText(t) {
  return (key, params) => t(AI_KEYS[key] ?? key, params);
}
