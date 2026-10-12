import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_VIEW, availableLeadDays, availableVariables, parseHash, toHash,
} from "./view.js";

test("the URL hash round-trips", () => {
  const view = { variable: "wind_speed_10m", leadDay: 3, window: "jja" };
  assert.deepEqual(parseHash(toHash(view)), view);
});

test("unknown parts of the hash fall back to the default", () => {
  assert.deepEqual(parseHash(""), DEFAULT_VIEW);
  assert.deepEqual(parseHash("#nonsense/9/forever"), DEFAULT_VIEW);
  assert.equal(parseHash("#precipitation_24h/x/all").leadDay, 1);
});

test("variables follow meta.json", () => {
  assert.deepEqual(availableVariables({ variables: ["wind_speed_10m", "temperature_2m", "precipitation"] }), [
    "temperature_2m",
    "wind_speed_10m",
  ]);
  assert.ok(availableVariables(null).includes("precipitation_24h"));
});

test("lead days with data", () => {
  assert.deepEqual(availableLeadDays([{ lead_day: 3 }, { lead_day: 1 }, { lead_day: 3 }]), [1, 3]);
  assert.deepEqual(availableLeadDays([]), [1]);
});
