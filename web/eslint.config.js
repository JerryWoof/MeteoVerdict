// Catches names that are used but never defined (a removed function or variable left
// behind, as in #222 and #237), which otherwise only fail in the browser.
import globals from "globals";

export default [
  { ignores: ["dist/", "public/", "node_modules/"] },
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser, ...globals.node },
    },
    rules: { "no-undef": "error" },
  },
];
