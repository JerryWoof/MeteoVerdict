// "My location": an icon-only MapLibre control under the zoom buttons, the same on the
// forecast, radar and heatmap maps, plus the small blue dot that marks the position.
// The page decides what a position means (onFix); this file does the browser's part:
// asking, the loading / denied / outside states as a small note on the map (no alert()),
// and remembering the last position for the tab's session only (never stored for good).
import { Marker } from "maplibre-gl";
import { OUTSIDE_KM, locateErrorKey, nearestPlace } from "./home-place.js";

const KEY = "mv-last-position";
const FRESH_MS = 10 * 60 * 1000;
const NOTE_MS = 6000;

// Tabler "current-location"
const ICON =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/><path d="M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0 -16 0"/>' +
  '<path d="M12 2l0 2"/><path d="M12 20l0 2"/><path d="M20 12l2 0"/><path d="M2 12l2 0"/></svg>';

function lastPosition() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY));
    if (saved && Date.now() - saved.at < FRESH_MS) return saved;
  } catch {
    // no session storage: ask again
  }
  return null;
}

function remember(lat, lon) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ lat, lon, at: Date.now() }));
  } catch {
    // fine without
  }
}

function currentPosition() {
  const known = lastPosition();
  if (known) return Promise.resolve(known);
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        remember(coords.latitude, coords.longitude);
        resolve({ lat: coords.latitude, lon: coords.longitude });
      },
      reject,
      { enableHighAccuracy: false, timeout: 15000, maximumAge: FRESH_MS },
    );
  });
}

/** The small blue dot of a position; stays on the map (and through the radar animation). */
export function locationDot(map) {
  let marker = null;
  return {
    show(lon, lat) {
      if (!marker) {
        const el = document.createElement("div");
        el.className = "my-location-dot";
        marker = new Marker({ element: el });
      }
      marker.setLngLat([lon, lat]).addTo(map);
    },
    hide: () => marker?.remove(),
  };
}

class LocateControl {
  constructor({ t, places, onFix }) {
    this.t = t;
    this.places = places;
    this.onFix = onFix;
  }

  onAdd(map) {
    this.map = map;
    this.box = document.createElement("div");
    this.box.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "mv-locate";
    this.button.innerHTML = ICON;
    const label = this.t("locate.button");
    this.button.setAttribute("aria-label", label);
    this.button.title = label;
    this.button.addEventListener("click", () => this.locate());
    this.box.append(this.button);
    // the note sits at the map's top, centred: clear of the controls, legends and credits
    this.note = document.createElement("div");
    this.note.className = "locate-note";
    this.note.setAttribute("role", "status");
    this.note.hidden = true;
    map.getContainer().append(this.note);
    return this.box;
  }

  onRemove() {
    this.note.remove();
    this.box.remove();
  }

  say(text) {
    clearTimeout(this.timer);
    this.note.textContent = text ?? "";
    this.note.hidden = !text;
    if (text) this.timer = setTimeout(() => this.say(null), NOTE_MS);
  }

  async locate() {
    if (this.busy) return;
    if (!navigator.geolocation) {
      this.say(this.t("locate.unsupported"));
      return;
    }
    this.busy = true;
    this.button.classList.add("loading");
    this.button.setAttribute("aria-busy", "true");
    this.say(this.t("radar.point.locating"));
    try {
      let fix;
      try {
        fix = await currentPosition();
      } catch (error) {
        // our own sentence: the browser's error text is English whatever the page language
        this.say(this.t(locateErrorKey(error)));
        return;
      }
      const places = await this.places();
      if (!nearestPlace(places, fix.lat, fix.lon, OUTSIDE_KM)) {
        this.say(this.t("locate.outside"));
        return;
      }
      this.say(null);
      await this.onFix({ ...fix, places });
    } catch (error) {
      console.error(error);
      this.say(this.t("locate.unavailable"));
    } finally {
      this.busy = false;
      this.button.classList.remove("loading");
      this.button.removeAttribute("aria-busy");
    }
  }
}

/** Add the control to the top-right group of `map` (call right after the zoom buttons).
 * `places` loads obce.json; `onFix({lat, lon, places})` runs for a position inside Czechia. */
export function addLocateControl(map, options) {
  map.addControl(new LocateControl(options), "top-right");
}
