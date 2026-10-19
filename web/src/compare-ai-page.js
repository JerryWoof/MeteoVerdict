import "./style.css";

import { setUpAiCompare } from "./compare-ai-view.js";
import { setUpLanguage } from "./i18n.js";
import { statusText } from "./status.js";

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

main();
