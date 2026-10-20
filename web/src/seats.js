// The forecast detail per okres town (sídlo okresu 1960–2002): the town an okres is named
// after, "Praha", "Brno", "Ostrava" and "Plzeň" for the city okresy, and the five okresy
// whose seat lies outside them (around Praha, Brno and Plzeň) shown as that city.

/** The okresy whose seat is a city in another okres → that city's okres. */
export const SEAT_OKRES = { CZ0209: "CZ0100", CZ020A: "CZ0100", CZ0643: "CZ0642", CZ0324: "CZ0323", CZ0325: "CZ0323" };

/** The okres whose detail shows a link's okres (itself unless its seat is elsewhere). */
export const seatOkres = (code) => SEAT_OKRES[code] ?? code;

/** The town's name for an okres's code and name. */
export function seatName(code, name) {
  if (code === "CZ0100") return "Praha";
  return name.replace(/-(město|venkov|jih|sever|východ|západ)$/, "");
}
