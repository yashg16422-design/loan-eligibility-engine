// The curtain: "ClickPar Match" rises, a bar draws, the curtain lifts. Once per session;
// index.html decides whether it plays before first paint.
import { gsap } from "gsap";
import { $, writeStore } from "./dom";
import { holdScroll } from "./scroll";

export function playIntro(): void {
  const root = document.documentElement;
  if (root.dataset.intro !== "play") return;
  writeStore("session", "cpm-intro", "1");
  holdScroll(true);
  const skip = $<HTMLButtonElement>("#skip");
  const tl = gsap.timeline({
    onComplete: () => {
      root.dataset.intro = "done";
      holdScroll(false);
    },
  });
  tl.to("#curtain .word span", { y: 0, duration: 0.7, stagger: 0.08, ease: "power3.out" })
    .to("#curtain .bar", { scaleX: 1, duration: 0.8, ease: "power2.inOut" }, "-=0.3")
    .to("#curtain", { clipPath: "inset(0 0 100% 0)", duration: 0.8, ease: "power3.inOut" }, "+=0.15");
  skip.addEventListener("click", () => tl.progress(1));
  skip.focus({ preventScroll: true });
}
