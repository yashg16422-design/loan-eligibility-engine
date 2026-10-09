// ClickPar Match landing: boots each scroll scene in document order. ScrollTrigger measures
// in creation order, so sections above a pinned one must be created before it.
import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import "lenis/dist/lenis.css";
import "./styles/landing.css";

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { initAsk } from "./landing/ask";
import { initComic } from "./landing/comic";
import { initEngine } from "./landing/engine";
import { playIntro } from "./landing/intro";
import { initJourney } from "./landing/journey";
import { initNav } from "./landing/nav";
import { initProof } from "./landing/proof";
import { initSmoothScroll } from "./landing/scroll";
import { initStatement } from "./landing/statement";

gsap.registerPlugin(ScrollTrigger);

async function boot(): Promise<void> {
  const root = document.documentElement;
  root.dataset.ready = "1"; // tells the curtain's safety timer that the script is alive
  initSmoothScroll();
  initNav();
  initStatement();
  initAsk();
  const comicReady = initComic(); // fetches the cast lazily
  initJourney();
  initEngine();
  initProof();

  // the globe (three.js + 220 KB of map dots) loads after everything else is interactive
  const globe = import("./landing/globe").then((m) => m.initGlobe());

  const [comic] = await Promise.all([comicReady, document.fonts.ready]);
  comic.build(); // needs final font metrics: the camera frames measured boxes
  ScrollTrigger.refresh();
  playIntro();
  await globe;
  ScrollTrigger.refresh();
}

boot().catch((err: unknown) => {
  // a broken scene must never leave the page covered or frozen: show the static page instead
  document.documentElement.classList.add("static");
  document.documentElement.dataset.intro = "done";
  ScrollTrigger.getAll().forEach((st) => st.kill(true));
  reportError(err);
});
