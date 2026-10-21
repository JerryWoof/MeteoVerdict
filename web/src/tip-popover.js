// A small popover for the detail text of table cells and "?" marks ([data-tip]).
// A `title` shows only on mouse hover, so on a phone or with the keyboard the detail
// was out of reach. One popover for the whole page: it opens on hover (mouse), on
// keyboard focus and on a tap; it closes on a tap elsewhere, Escape or blur.
// It floats over the page (absolute, in <body>), so rows never grow and nothing moves.

let popover = null;
let current = null;
// how the open popover was opened: "hover" closes when the mouse leaves,
// "focus" on blur, "tap" (a click) stays until a tap elsewhere, Escape or blur
let mode = null;

function ensurePopover() {
  if (popover) return popover;
  popover = document.createElement("div");
  popover.className = "tip-popover";
  popover.id = "tip-popover";
  popover.setAttribute("role", "tooltip");
  popover.hidden = true;
  document.body.append(popover);
  return popover;
}

function place(target) {
  const box = target.getBoundingClientRect();
  const margin = 8;
  popover.style.left = "0px";
  popover.style.top = "0px";
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  // under the cell, or above it when the window ends first; never past the sides
  const left = Math.max(margin, Math.min(box.left, window.innerWidth - width - margin));
  const below = box.bottom + 4;
  const top = below + height > window.innerHeight - margin && box.top - height - 4 > margin
    ? box.top - height - 4
    : below;
  popover.style.left = `${left + window.scrollX}px`;
  popover.style.top = `${top + window.scrollY}px`;
}

function show(target, how) {
  const text = target.dataset.tip;
  if (!text) return;
  ensurePopover();
  if (current && current !== target) current.removeAttribute("aria-describedby");
  current = target;
  mode = how;
  popover.textContent = text;
  popover.hidden = false;
  target.setAttribute("aria-describedby", popover.id);
  place(target);
}

function hide() {
  if (!current) return;
  current.removeAttribute("aria-describedby");
  current = null;
  mode = null;
  popover.hidden = true;
}

const tipOf = (node) => (node instanceof Element ? node.closest("[data-tip]") : null);

/** Wires the popover for every [data-tip] element on the page (now and later ones). */
export function setUpTips() {
  document.addEventListener("pointerover", (event) => {
    if (event.pointerType !== "mouse") return;
    const target = tipOf(event.target);
    // hover does not take over a popover opened by focus or a tap
    if (target && target !== current && (!current || mode === "hover")) show(target, "hover");
  });
  document.addEventListener("pointerout", (event) => {
    if (mode !== "hover" || event.pointerType !== "mouse") return;
    if (!current.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("focusin", (event) => {
    const target = tipOf(event.target);
    if (target) show(target, "focus");
  });
  document.addEventListener("focusout", (event) => {
    if (current && current.contains(event.target) && !current.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("click", (event) => {
    const target = tipOf(event.target);
    if (!target) return;
    // the "?" sits in a <label>: a tap on it must not jump to the label's select
    if (target.closest("label")) event.preventDefault();
    // a second tap on the same cell closes it again
    if (target === current && mode === "tap") hide();
    else show(target, "tap");
  });
  document.addEventListener("pointerdown", (event) => {
    if (current && !tipOf(event.target) && !popover.contains(event.target)) hide();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide();
  });
  // it follows its cell when the page or a table scrolls (also the sticky "?"),
  // or when a phone's address bar comes and goes
  const follow = () => {
    if (current) place(current);
  };
  document.addEventListener("scroll", follow, { capture: true, passive: true });
  window.addEventListener("resize", follow);
}
