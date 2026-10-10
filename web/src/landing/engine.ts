// "How it decides, in one pass": the pipeline draws itself as you scroll. Each node fades in
// and counts up, its outgoing edges draw, then packets travel along them; fewer packets per
// edge through the funnel show the work collapsing (590,000 -> 164 -> 5). Phones get a single
// column that the camera follows.
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { count, step } from "../lib/format";
import { anchor, CAPTIONS, captionAt, EDGES, type Hue, layout, NODES, pathD } from "../lib/pipeline";
import { $, accent, isSmall, isStatic, THEME_EVENT } from "./dom";

const SVG_NS = "http://www.w3.org/2000/svg";
const SLOT = 1.4; // timeline seconds per node
const hueColour = (h: Hue): string =>
  ({ amber: "#FFC94D", peri: "#B79CFF", coral: "#FF7A59", mint: accent() })[h];

function svgEl<K extends keyof SVGElementTagNameMap>(
  tag: K, attrs: Record<string, string | number>, parent?: Element,
): SVGElementTagNameMap[K] {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  parent?.append(e);
  return e;
}

export function initEngine(): void {
  const dia = $("#dia");
  const capEl = $("#eng-text");
  const stepEl = $("#eng-step");
  const cam = { y: 0 };
  let svg: SVGSVGElement | null = null;
  let vertical = false;
  let viewH = 0;
  let tl: gsap.core.Timeline | undefined;
  let st: ScrollTrigger | undefined;

  const setCaption = (i: number): void => {
    capEl.textContent = CAPTIONS[i];
    stepEl.textContent = step(i, CAPTIONS.length);
  };

  // phones: the svg is taller than the screen, so translate it to follow the newest node
  function applyCam(): void {
    if (!svg || !vertical) return;
    const s = dia.clientWidth / 360;
    svg.style.transform = `translateY(${-cam.y * s}px)`;
    svg.style.height = viewH * s + "px";
  }

  function build(): void {
    tl?.kill();
    st?.kill();
    dia.replaceChildren();
    vertical = isSmall();
    const { boxes, viewBox } = layout(vertical);
    viewH = viewBox[3];
    svg = svgEl("svg", {
      viewBox: viewBox.join(" "),
      preserveAspectRatio: vertical ? "xMidYMin meet" : "xMidYMid meet",
      role: "img",
      "aria-label": "Pipeline from lender sites through the AI and the Treasure Hunt funnel to email",
    }, dia);
    const gEdges = svgEl("g", {}, svg), gNodes = svgEl("g", {}, svg), gPackets = svgEl("g", {}, svg);
    const hueOf = (id: string): string => hueColour(NODES.find((n) => n.id === id)?.hue ?? "amber");

    const edges = EDGES.map((e) => {
      const d = pathD(anchor(boxes[e.from], boxes[e.to]));
      const cls = "edge" + (e.control ? " ctl" : "");
      svgEl("path", { d, class: cls, stroke: "#151515" }, gEdges); // the unlit track
      const live = svgEl("path", { d, class: cls, stroke: hueOf(e.to) }, gEdges);
      const len = live.getTotalLength();
      if (e.control) live.style.opacity = "0";
      else {
        live.style.strokeDasharray = String(len);
        live.style.strokeDashoffset = String(len);
      }
      const packets = Array.from({ length: e.packets }, () =>
        svgEl("circle", { r: e.packets > 4 ? 3 : 4.5, fill: hueOf(e.to), opacity: 0 }, gPackets));
      return { ...e, live, len, packets };
    });

    const nodes = NODES.map((n) => {
      const b = boxes[n.id];
      const g = svgEl("g", { class: n.control ? "ctl" : "", opacity: 0, transform: `translate(${b.x},${b.y})` }, gNodes);
      svgEl("rect", { class: "nf", width: b.w, height: b.h }, g);
      svgEl("rect", { width: 28, height: 3, fill: hueColour(n.hue) }, g);
      const glow = svgEl("rect", { class: "glow", width: b.w, height: b.h, fill: "none", stroke: hueColour(n.hue), "stroke-width": 1.5 }, g);
      svgEl("text", { class: "nl", x: 14, y: 26 }, g).textContent = n.label;
      const value = svgEl("text", { class: "nv", x: 14, y: vertical ? 62 : 66, fill: hueColour(n.hue) }, g);
      value.textContent = n.value;
      svgEl("text", { class: "ns", x: 14, y: vertical ? 82 : 90 }, g).textContent = n.sub;
      return { n, b, g, glow, value };
    });

    if (isStatic()) {
      // reduced motion: the finished diagram, with every caption as one paragraph
      nodes.forEach((o) => o.g.setAttribute("opacity", "1"));
      edges.forEach((e) => {
        e.live.style.strokeDashoffset = "0";
        e.live.style.opacity = "1";
      });
      stepEl.textContent = step(CAPTIONS.length - 1, CAPTIONS.length);
      capEl.textContent = CAPTIONS.join(" ");
      return;
    }
    setCaption(0);

    const timeline = gsap.timeline({ defaults: { ease: "power2.out" } });
    nodes.forEach((o, i) => {
      const t = i * SLOT;
      if (vertical) timeline.to(cam, { y: Math.max(0, o.b.y - 120), duration: 0.8, ease: "power1.inOut", onUpdate: applyCam }, t);
      timeline
        .fromTo(o.g, { attr: { opacity: 0 } }, { attr: { opacity: 1 }, duration: 0.4 }, t + 0.1)
        .fromTo(o.glow, { opacity: 0.9 }, { opacity: 0, duration: 0.8 }, t + 0.3);
      if (o.n.countTo) {
        const c = { v: 0 };
        const to = o.n.countTo;
        timeline.to(c, { v: to, duration: 0.9, ease: "power1.out", onUpdate: () => void (o.value.textContent = count(c.v)) }, t + 0.1);
      }
      edges.filter((e) => e.from === o.n.id).forEach((e) => {
        const s = t + 0.7;
        if (e.control) timeline.to(e.live, { opacity: 1, duration: 0.4 }, s);
        else timeline.to(e.live, { strokeDashoffset: 0, duration: 0.6, ease: "none" }, s);
        e.packets.forEach((c, k) => {
          const p = { u: 0 };
          timeline.to(p, {
            u: 1, duration: 0.7, ease: "power1.inOut",
            onUpdate: () => {
              const pt = e.live.getPointAtLength(p.u * e.len);
              c.setAttribute("cx", String(pt.x));
              c.setAttribute("cy", String(pt.y));
              c.setAttribute("opacity", p.u > 0.02 && p.u < 0.98 ? "1" : "0");
            },
          }, s + 0.3 + k * 0.05);
        });
      });
    });
    timeline.to({}, { duration: 0.8 }); // a beat on the finished diagram before it scrolls away
    // the caption follows the playhead, so scrubbing backwards stays correct
    let last = 0;
    timeline.eventCallback("onUpdate", () => {
      const i = captionAt(timeline.time(), SLOT);
      if (i !== last) setCaption((last = i));
    });
    tl = timeline;
    st = ScrollTrigger.create({ trigger: "#engine", start: "top top", end: "bottom bottom", scrub: 0.5, animation: timeline });
  }

  build();
  applyCam();
  addEventListener(THEME_EVENT, () => {
    build();
    applyCam();
    ScrollTrigger.refresh();
  });
  let wasVertical = vertical;
  addEventListener("resize", () => {
    if (isSmall() === wasVertical) return;
    wasVertical = isSmall();
    cam.y = 0;
    build();
    ScrollTrigger.refresh();
  });
}
