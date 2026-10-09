// "How ClickPar Match started": a two-frame comic on one big page, filmed by a scroll-driven
// camera. Frame 1: two engineers pitch the founders, who say YES. Frame 2: the team gathers
// round a laptop; the camera dives into its screen, which becomes the launch lockup.
// Characters: Open Peeps (Pablo Stanley, CC0), loaded lazily from cast.json.
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { burstPoints, type Cam, fit, type Rect } from "../lib/camera";
import { $, $$, accent, debounce, isStatic, THEME_EVENT } from "./dom";

type FrameId = "f2" | "f3";
interface PageLayout {
  w: number;
  h: number;
  frames: Record<FrameId, Rect>;
}

// desktop: frames side by side; phone: stacked, each frame portrait
const LAYOUT: Record<"desktop" | "phone", PageLayout> = {
  desktop: { w: 3260, h: 900, frames: { f2: [0, 0, 1600, 900], f3: [1660, 0, 1600, 900] } },
  phone: { w: 700, h: 2040, frames: { f2: [0, 0, 700, 1000], f3: [0, 1040, 700, 1000] } },
};
const isPhone = (): boolean => innerWidth < 761;
const CONFETTI = 46;

type Style = Partial<CSSStyleDeclaration>;
/** Per-layout staging: phones stack the cast vertically inside the portrait frames. */
const STAGING: Record<string, [desktop: Style, phone: Style]> = {
  "#f2board": [{ width: "46%", left: "4%", top: "14%" }, { width: "88%", left: "6%", top: "12%" }],
  "#f2s1": [{ left: "54%", top: "8%", maxWidth: "26cqw" }, { left: "6%", top: "33%", maxWidth: "60cqw" }],
  "#f2a": [{ left: "-2%", height: "" }, { left: "-10%", height: "44cqh" }],
  "#f2b": [{ left: "21%", height: "54cqh" }, { left: "16%", height: "38cqh" }],
  "#f2f2": [{ right: "19%", height: "56cqh" }, { right: "14%", height: "40cqh" }],
  "#f2f1": [{ right: "-3%", height: "" }, { right: "-10%", height: "44cqh" }],
  "#f2burst": [{ right: "34%", top: "3%" }, { right: "1%", top: "37%" }],
  "#f2s2": [{ right: "3%", top: "12%" }, { right: "54%", top: "42%" }],
  "#f2dots": [{ right: "14%", top: "30%" }, { right: "12%", top: "46%" }],
};
// the team in frame 2 leaves the middle free for the laptop
const TEAM_LEFT = { desktop: [2, 15, 28, 46, 59, 72], phone: [-12, 4, 20, 50, 66, 82] };

export interface Comic {
  build(): void;
}

/** Fill each character slot with one layer per pose, so a pose swap is a cross-fade. */
function paintCast(cast: Record<string, string>): void {
  $$("[data-k]").forEach((el) => {
    const who = el.dataset.k ?? "";
    el.innerHTML = (el.dataset.s ?? "idle")
      .split(",")
      .map((pose) => `<div class="st" data-st="${pose}">${cast[`${who}_${pose}`] ?? cast[who] ?? cast[`${who}_idle`] ?? ""}</div>`)
      .join("");
  });
}

function paintConfetti(): void {
  const colours = [accent(), "#FFC94D", "#B79CFF", "#FF7A59", "#F2F2F2"];
  $("#confetti").innerHTML = Array.from(
    { length: CONFETTI },
    (_, i) => `<i style="background:${colours[i % 5]}; width:${8 + (i % 4) * 3}px; height:${6 + (i % 3) * 4}px"></i>`,
  ).join("");
}

export async function initComic(): Promise<Comic> {
  const page = $("#page");
  page.classList.add("peeps");
  const cast = (await import("./cast.json")).default as Record<string, string>;
  paintCast(cast);
  $$(".burstpoly").forEach((p) => p.setAttribute("points", burstPoints()));

  let L: PageLayout = LAYOUT.desktop;
  const cam: Cam = { x: 0, y: 0, s: 1 };
  let twin: HTMLElement | null = null;
  let tl: gsap.core.Timeline | undefined;
  let st: ScrollTrigger | undefined;

  function place(): void {
    const phone = isPhone();
    L = phone ? LAYOUT.phone : LAYOUT.desktop;
    page.classList.toggle("m", phone);
    Object.assign(page.style, { width: L.w + "px", height: L.h + "px" });
    for (const [id, [x, y, w, h]] of Object.entries(L.frames)) {
      Object.assign($("#" + id).style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
    }
    for (const [sel, [d, m]] of Object.entries(STAGING)) Object.assign($(sel).style, phone ? m : d);
    $$("#f3 .av.g").forEach((a, i) => {
      a.style.left = (phone ? TEAM_LEFT.phone : TEAM_LEFT.desktop)[i] + "%";
      a.style.height = phone ? "34cqh" : "46cqh";
    });
  }

  const applyCam = (): void => {
    const t = `translate(${cam.x}px, ${cam.y}px) scale(${cam.s})`;
    page.style.transform = t;
    if (twin) twin.style.transform = t;
  };
  const frameCam = (r: Rect, pad?: number): Cam => fit(r, innerWidth, innerHeight, pad);

  /** The laptop screen's rect in page coordinates, for the final dive. */
  function screenRect(): Rect {
    const f = L.frames.f3, fr = $("#f3").getBoundingClientRect(), sr = $("#screen").getBoundingClientRect();
    const k = f[2] / fr.width;
    return [f[0] + (sr.left - fr.left) * k, f[1] + (sr.top - fr.top) * k, sr.width * k, sr.height * k];
  }

  function build(): void {
    tl?.kill();
    st?.kill();
    // .to() tweens record their start from the live DOM, so reset what an earlier timeline left
    // behind (a rebuild mid-scroll would otherwise lose the idle poses and the "..." dots)
    gsap.set(["#page .st", "#page .dim", "#f2dots"], { clearProps: "opacity,visibility" });
    place();
    paintConfetti();
    // a blurred, static copy of the page behind the cards (ids stripped so nothing targets it)
    const cbg = $("#cbg");
    twin = page.cloneNode(true) as HTMLElement;
    twin.removeAttribute("id");
    twin.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id"));
    cbg.replaceChildren(twin);
    const dims = Object.fromEntries(
      (["f2", "f3"] as const).map((id) => {
        const frame = $("#" + id);
        let dim = frame.querySelector<HTMLElement>(".dim");
        if (!dim) {
          dim = document.createElement("div");
          dim.className = "dim";
          frame.append(dim);
        }
        return [id, dim];
      }),
    ) as Record<FrameId, HTMLElement>;
    Object.assign(cam, frameCam(L.frames.f2));
    applyCam();
    gsap.set("#launch", { autoAlpha: 0 });

    const t = gsap.timeline({ defaults: { ease: "power2.out", duration: 0.45 } });
    const go = (id: FrameId, at: number): void => {
      t.to(cam, { ...frameCam(L.frames[id]), duration: 0.9, ease: "power2.inOut", onUpdate: applyCam }, at);
      (Object.keys(dims) as FrameId[]).forEach((o) => t.to(dims[o], { opacity: o === id ? 0 : 0.7, duration: 0.5 }, at + 0.2));
    };
    const pop = (sel: string, at: number): void =>
      void t.fromTo(sel, { autoAlpha: 0, scale: 0.2 }, { autoAlpha: 1, scale: 1, duration: 0.4, ease: "back.out(2.2)" }, at);
    const out = (sel: string, at: number): void => void t.to(sel, { autoAlpha: 0, scale: 0.9, duration: 0.25 }, at);
    const swap = (who: string, pose: string, at: number): void =>
      void t
        .to(`${who} .st:not([data-st="${pose}"])`, { autoAlpha: 0, duration: 0.2 }, at)
        .to(`${who} .st[data-st="${pose}"]`, { autoAlpha: 1, duration: 0.2 }, at)
        .fromTo(who, { y: 0 }, { y: -18, duration: 0.15, yoyo: true, repeat: 1, ease: "power1.out" }, at);

    t.set(dims.f2, { opacity: 0 }, 0);
    // frame 1: the pitch, a pause, then YES
    t.fromTo("#f2board", { autoAlpha: 0, y: -30 }, { autoAlpha: 1, y: 0 }, 0.3);
    t.fromTo("#f2a, #f2b", { autoAlpha: 0, x: -70 }, { autoAlpha: 1, x: 0, stagger: 0.12 }, 0.4);
    t.fromTo("#f2f1, #f2f2", { autoAlpha: 0, x: 70 }, { autoAlpha: 1, x: 0, stagger: 0.12 }, 0.55);
    pop("#f2s1", 0.9);
    t.fromTo("#f2dots i", { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, stagger: 0.15, duration: 0.2 }, 1.4);
    t.to("#f2dots", { autoAlpha: 0, duration: 0.2 }, 2.0);
    out("#f2s1", 2.0);
    swap("#f2f1", "yes", 2.1);
    swap("#f2f2", "yes", 2.25);
    t.fromTo("#f2burst", { autoAlpha: 0, scale: 0, rotation: -40 }, { autoAlpha: 1, scale: 1, rotation: 0, ease: "back.out(3)" }, 2.15);
    pop("#f2s2", 2.5);
    // frame 2: everyone gathers; the laptop screen becomes the launch
    go("f3", 3.3);
    t.fromTo("#f3 .av.g", { autoAlpha: 0, y: 70 }, { autoAlpha: 1, y: 0, stagger: 0.1, duration: 0.4, ease: "back.out(1.6)" }, 4.0);
    t.fromTo("#f3 .note", { autoAlpha: 0, scale: 0.4 }, { autoAlpha: 1, scale: 1, stagger: 0.1, duration: 0.3, ease: "back.out(2)" }, 4.4);
    t.fromTo("#lap", { autoAlpha: 0, y: 30 }, { autoAlpha: 1, y: 0, duration: 0.35 }, 4.75);
    pop("#f3s1", 5.0);
    t.to(cam, { ...frameCam(screenRect(), 1.7), duration: 1, ease: "power3.in", onUpdate: applyCam }, 5.7);
    t.to("#launch", { autoAlpha: 1, duration: 0.35, ease: "none" }, 6.35);
    t.fromTo(".lock > *", { autoAlpha: 0, y: 24 }, { autoAlpha: 1, y: 0, stagger: 0.1 }, 6.5);
    $$("#confetti i").forEach((c, i) => {
      const a = (i / CONFETTI) * Math.PI * 2 + (i % 3) * 0.2, r = 0.35 + (i % 7) * 0.08;
      t.fromTo(c, { autoAlpha: 0, x: 0, y: 0, rotation: 0 }, {
        autoAlpha: 1, x: () => Math.cos(a) * innerWidth * r, y: () => Math.sin(a) * innerHeight * r * 0.9,
        rotation: 240 + i * 17, duration: 0.8, ease: "power3.out",
      }, 6.5 + (i % 5) * 0.03);
      t.to(c, { autoAlpha: 0, duration: 0.35 }, 7.4);
    });
    t.to({}, { duration: 0.8 }, 7.7); // hold the lockup before the section scrolls away
    tl = t;

    if (isStatic()) {
      t.progress(1);
      return;
    }
    // rebuilt on resize rather than invalidated, so the hidden start states hold
    st = ScrollTrigger.create({ trigger: "#comic", start: "top top", end: "bottom bottom", scrub: 0.6, animation: t });
  }

  const rebuild = debounce(() => {
    build();
    ScrollTrigger.refresh();
  }, 200);
  addEventListener("resize", rebuild);
  addEventListener(THEME_EVENT, rebuild);
  return { build };
}
