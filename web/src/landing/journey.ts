// "How Aarav checks his loans": five slides on a horizontal rail that pans as you scroll.
// The ranked list and the compare table are rendered from content/demo.ts (checked against
// the mocks), so the numbers on screen are the database's numbers.
import { gsap } from "gsap";
import { COMPARE, RANKED } from "../content/demo";
import { loanCost } from "../lib/finance";
import { inr } from "../lib/format";
import { $, isStatic } from "./dom";

function renderRanked(): void {
  $("#rank").innerHTML = RANKED.map(
    (o) => `<div class="mrow"><div><div class="n">${o.lender}</div><div class="v">${o.via}<span class="tag${o.verified ? " ok" : ""}">${o.verified ? "verified quote" : "confirm with lender"}</span></div></div><div class="r">${o.rate}%<small>from</small></div><div class="f">${o.fit.toFixed(1)}</div></div>`,
  ).join("");
}

function renderCompare(): void {
  const { principal, months, lenders } = COMPARE;
  $("#cmp tbody").innerHTML = lenders
    .map(({ lender, rate }, i) => {
      const c = loanCost(principal, rate, months);
      return `<tr${i === 0 ? ' class="best"' : ""}><td>${lender}</td><td>${rate}%</td><td>${inr(c.emi)}</td><td>${inr(c.totalInterest)}</td></tr>`;
    })
    .join("");
}

export function initJourney(): void {
  renderRanked();
  renderCompare();
  if (isStatic()) return; // reduced motion: the slides simply stack
  const track = $("#track");
  const distance = (): number => track.scrollWidth - innerWidth;
  gsap.to(track, {
    x: () => -distance(),
    ease: "none",
    scrollTrigger: {
      trigger: "#journey",
      start: "top top",
      end: () => "+=" + distance() * 1.1,
      pin: ".rail",
      scrub: 0.6,
      invalidateOnRefresh: true, // a plain tween, so re-measuring on resize is safe here
      anticipatePin: 1,
    },
  });
}
