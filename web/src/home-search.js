// The home page's top: "Najít místo" and "Předpověď pro moji polohu", both leading to the
// detailed forecast of the place (home-place.js).
import { OUTSIDE_KM, forecastLink, locateErrorKey, nearestPlace, okresOf } from "./home-place.js";
import { nearestObec } from "./obce-map.js";
import { placeSearch } from "./place-search.js";
import { placesLoader } from "./places.js";
import placesUrl from "./data/obce.json?url";

async function getJson(path) {
  try {
    const response = await fetch(path);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export function setUpHomeSearch(t) {
  const box = document.getElementById("home-find");
  if (!box) return;
  const loadPlaces = placesLoader(placesUrl);
  const note = document.getElementById("home-note");
  let outlook = null;

  async function go(place) {
    note.textContent = "";
    outlook ??= getJson("data/scores/outlook.json");
    const okres = okresOf(place, (await outlook)?.okresy ?? []);
    if (!okres) {
      note.textContent = t("home.noForecast");
      return;
    }
    const doc = await getJson(`data/scores/forecast/obce-${okres.code}.json`);
    const obec = nearestObec(doc, place.lat, place.lon);
    window.location.href = forecastLink(okres.code, obec?.name);
  }

  document.getElementById("home-search").replaceChildren(placeSearch({ t, load: loadPlaces, choose: go, placeholder: t("home.placeholder") }));

  const button = document.getElementById("home-locate");
  button.addEventListener("click", () => {
    if (!navigator.geolocation) {
      note.textContent = t("locate.unsupported");
      return;
    }
    note.textContent = t("radar.point.locating");
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        const places = await loadPlaces();
        const place = nearestPlace(places, coords.latitude, coords.longitude, OUTSIDE_KM);
        if (!places.length) note.textContent = t("radar.place.unavailable");
        else if (!place) note.textContent = t("home.outside");
        else await go(place);
      },
      (error) => {
        note.textContent = t(locateErrorKey(error));
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 },
    );
  });
}
