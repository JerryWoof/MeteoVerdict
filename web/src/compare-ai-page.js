import "./style.css";

import { setUpAiCompare } from "./compare-ai-view.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";

// compare.html used to be the model ranking: its old links (#variable/lead/window/region)
// now open that ranking on compare-models.html instead of the AI page with its defaults
const oldRanking = /^#[a-z][a-z0-9_]*\/[^/]+\/[^/]+/.test(window.location.hash);
if (oldRanking) window.location.replace(`compare-models.html${window.location.hash}`);

const t = setUpLanguage();

async function main() {
  let meta = null;
  try {
    const response = await fetch("data/scores/meta.json");
    meta = response.ok ? await response.json() : null;
  } catch {
    meta = null;
  }
  document.getElementById("status").textContent = statusText(meta, t);
  await setUpAiCompare(t, { ...meta?.models }, document.documentElement.lang);
}

if (!oldRanking) main();
