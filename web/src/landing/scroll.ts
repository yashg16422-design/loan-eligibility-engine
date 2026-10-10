// Smooth scroll (Lenis) driven by GSAP's ticker, so ScrollTrigger and Lenis agree on every
// frame. Reduced motion keeps native scrolling.
import Lenis from "lenis";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { $$, isStatic } from "./dom";

let lenis: Lenis | null = null;

export function initSmoothScroll(): void {
  if (!isStatic()) {
    lenis = new Lenis({ duration: 1.15, smoothWheel: true });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add((t) => lenis?.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
  }
  // in-page links glide instead of jumping; links to /app/ are left alone
  $$<HTMLAnchorElement>('a[href^="#"]').forEach((a) =>
    a.addEventListener("click", (e) => {
      const target = document.querySelector<HTMLElement>(a.getAttribute("href") ?? "");
      if (!target) return;
      e.preventDefault();
      scrollToEl(target);
      history.replaceState(null, "", a.hash);
    }),
  );
}

/** Scroll to an element (smoothly unless reduced motion), with an optional offset in px. */
export function scrollToEl(target: HTMLElement, offset = 0, duration = 1.4): void {
  if (lenis) lenis.scrollTo(target, { offset, duration });
  else target.scrollIntoView({ block: "start" });
}

/** Freeze or release scrolling (the intro curtain holds the page still). */
export function holdScroll(hold: boolean): void {
  if (hold) lenis?.stop();
  else lenis?.start();
}
