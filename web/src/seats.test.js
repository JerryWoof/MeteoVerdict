import assert from "node:assert/strict";
import { test } from "node:test";

import { seatName, seatOkres } from "./seats.js";

test("seatName: the okres town, the city for the city okresy", () => {
  assert.equal(seatName("CZ0100", "území Hlavního města Prahy"), "Praha");
  assert.equal(seatName("CZ0642", "Brno-město"), "Brno");
  assert.equal(seatName("CZ0806", "Ostrava-město"), "Ostrava");
  assert.equal(seatName("CZ0323", "Plzeň-město"), "Plzeň");
  assert.equal(seatName("CZ0802", "Frýdek-Místek"), "Frýdek-Místek");
  assert.equal(seatName("CZ0201", "Benešov"), "Benešov");
});

test("seatOkres: the okresy with their seat outside show that city", () => {
  assert.equal(seatOkres("CZ0209"), "CZ0100");
  assert.equal(seatOkres("CZ020A"), "CZ0100");
  assert.equal(seatOkres("CZ0643"), "CZ0642");
  assert.equal(seatOkres("CZ0324"), "CZ0323");
  assert.equal(seatOkres("CZ0325"), "CZ0323");
  assert.equal(seatOkres("CZ0201"), "CZ0201");
});
