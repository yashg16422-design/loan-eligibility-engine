// The fixed top bar, the collapsible section rail on the left (where am I, jump anywhere)
// and the accent palette switch that lives inside the rail.
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { step } from "../lib/format";
import { $, $$, isSmall, THEME_EVENT, readStore, writeStore } from "./dom";

const PALETTE_KEY = "cpm-acc";
const DEFAULT_PALETTE = "mint";

export function initNav(): void {
  const rn = $("#rn");
  const toggle = $(".rn-toggle", rn);
  const links = $$<HTMLAnchorElement>("#rn-list a");
  const counter = $("#rn-count");

  const setOpen = (open: boolean): void => {
    rn.dataset.open = String(open);
    toggle.setAttribute("aria-expanded", String(open));
  };
  toggle.addEventListener("click", () => setOpen(rn.dataset.open !== "true"));
  $(".rn-acc", rn).addEventListener("click", () => setOpen(true));
  links.forEach((a) => a.addEventListener("click", () => isSmall() && setOpen(false)));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && rn.dataset.open === "true") {
      setOpen(false);
      toggle.focus();
    }
  });

  const setActive = (i: number): void => {
    links.forEach((a, k) => (k === i ? a.setAttribute("aria-current", "true") : a.removeAttribute("aria-current")));
    const label = links[i].textContent?.trim().toUpperCase() ?? "";
    counter.textContent = step(i, links.length) + (isSmall() ? "  " + label : "");
  };
  setActive(0);
  links.forEach((a, i) => {
    const section = document.querySelector(a.getAttribute("href") ?? "");
    // refreshPriority -1: measure after the pinned sections have added their spacing
    if (section) {
      ScrollTrigger.create({
        trigger: section,
        start: "top 55%",
        end: "bottom 55%",
        refreshPriority: -1,
        onToggle: (st) => st.isActive && setActive(i),
      });
    }
  });
  ScrollTrigger.create({ start: 60, end: "max", toggleClass: { targets: ".nav", className: "scrolled" } });

  initPalette();
}

function initPalette(): void {
  const root = document.documentElement;
  const swatches = $$<HTMLButtonElement>(".sw button");
  const apply = (name: string, announce: boolean): void => {
    if (name === DEFAULT_PALETTE) delete root.dataset.acc;
    else root.dataset.acc = name;
    swatches.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.acc === name)));
    if (announce) dispatchEvent(new Event(THEME_EVENT));
  };
  // index.html already applied the saved palette before paint; sync the buttons to it
  const saved = readStore("local", PALETTE_KEY);
  apply(saved && swatches.some((b) => b.dataset.acc === saved) ? saved : DEFAULT_PALETTE, false);
  swatches.forEach((b) =>
    b.addEventListener("click", () => {
      const name = b.dataset.acc ?? DEFAULT_PALETTE;
      apply(name, true);
      writeStore("local", PALETTE_KEY, name);
    }),
  );
}
