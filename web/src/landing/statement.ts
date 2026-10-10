// "Most people learn a lender's rules by getting rejected...": each letter fills in as you
// scroll. Screen readers get the sentence once, via aria-label.
import { gsap } from "gsap";
import { plain, tokenize } from "../lib/statement";
import { $, $$, isStatic } from "./dom";

export function initStatement(): void {
  const el = $("#statement-text");
  const source = el.dataset.text ?? "";
  el.setAttribute("aria-label", plain(source));
  el.replaceChildren(
    ...tokenize(source).map((t) => {
      if (t.kind === "space") return document.createTextNode(t.text);
      const word = document.createElement("span");
      word.className = t.tone ? `w ${t.tone}` : "w";
      word.setAttribute("aria-hidden", "true");
      for (const ch of t.text) {
        const c = document.createElement("span");
        c.className = "ch";
        c.textContent = ch;
        word.append(c);
      }
      return word;
    }),
  );
  if (isStatic()) return;
  gsap.to($$(".ch", el), {
    opacity: 1,
    ease: "none",
    stagger: 0.05,
    scrollTrigger: { trigger: "#statement", start: "top top", end: "bottom bottom", scrub: 0.4 },
  });
}
