// "Find a place": a search over every obec with its okres (places.js, data/obce.json), as
// a combobox; the radar page and the forecast map use it. `load` returns the places,
// `choose(place)` is called with the one picked.
import { placeLabel, searchPlaces } from "./places.js";

function element(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}

export function placeSearch({ t, load, choose, placeholder = t("radar.place.placeholder") }) {
  const box = element("div", null, "place-search");
  const label = element("label", t("radar.place.label"));
  const input = document.createElement("input");
  input.type = "search";
  input.id = "place";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = placeholder;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", "place-list");
  label.htmlFor = input.id;
  const list = element("ul", null, "place-list");
  list.id = "place-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  let results = [];
  let active = -1;
  let token = 0;
  let enterPending = false; // Enter before the list came: take its first place

  function show(items, message = null) {
    results = items;
    active = items.length ? 0 : -1;
    list.replaceChildren(
      ...items.map((place, k) => {
        const option = element("li", null, "option");
        option.id = `place-${k}`;
        option.setAttribute("role", "option");
        option.append(element("span", place.name, "name"), element("span", ` (${place.okres})`, "okres"));
        // mousedown: before the input loses focus and closes the list
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          pick(k);
        });
        return option;
      }),
    );
    if (message) list.append(element("li", message, "empty"));
    list.hidden = !items.length && !message;
    input.setAttribute("aria-expanded", String(!list.hidden));
    highlight();
  }
  function highlight() {
    [...list.querySelectorAll(".option")].forEach((option, k) => option.setAttribute("aria-selected", String(k === active)));
    if (active >= 0) input.setAttribute("aria-activedescendant", `place-${active}`);
    else input.removeAttribute("aria-activedescendant");
    list.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }
  function pick(k) {
    const place = results[k];
    if (!place) return;
    input.value = placeLabel(place);
    show([]);
    choose(place);
  }
  async function search() {
    const query = input.value;
    const mine = ++token;
    if (!query.trim()) return show([]);
    const places = await load();
    if (mine !== token) return;
    if (!places.length) return show([], t("radar.place.unavailable"));
    const found = searchPlaces(places, query, 8);
    show(found, found.length ? null : t("radar.place.none"));
    if (enterPending && found.length) pick(0);
    enterPending = false;
  }
  input.addEventListener("focus", () => load()); // fetch while the user types
  input.addEventListener("input", () => {
    enterPending = false;
    search();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!results.length) return;
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      highlight();
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0) pick(active);
      else if (input.value.trim()) enterPending = true;
    } else if (event.key === "Escape") {
      show([]);
    }
  });
  input.addEventListener("blur", () => show([]));
  box.append(label, input, list);
  return box;
}
