// The engine diagram as data: nodes in build (= scroll) order, edges with a packet count that
// shows how much work flows along them, and one caption per node. Figures come from README.md
// (the measured Treasure Hunt run). Layout and edge routing are pure geometry, tested.

export type Hue = "amber" | "peri" | "coral" | "mint";

export interface PipeNode {
  id: string;
  label: string;
  value: string;
  sub: string;
  hue: Hue;
  control?: boolean; // control plane (trigger, proof): drawn dashed
  countTo?: number; // the value counts up from 0 when the node appears
}

export const NODES: readonly PipeNode[] = [
  { id: "sched", label: "trigger", value: "06:00 IST", sub: "daily crawl, plus manual", hue: "amber", control: true },
  { id: "sites", label: "sources", value: "40", sub: "lender pages", hue: "amber", countTo: 40 },
  { id: "robots", label: "robots.txt", value: "obeyed", sub: "blocked = skipped", hue: "amber" },
  { id: "nova", label: "Amazon Nova Pro", value: "reads once", sub: "every rule quotes the page", hue: "peri" },
  { id: "prods", label: "products", value: "59", sub: "26 lenders × 3 platforms", hue: "amber", countTo: 59 },
  { id: "pairs", label: "naive pairs", value: "590,000", sub: "10,000 users × 59", hue: "coral", countTo: 590000 },
  { id: "classes", label: "equivalence classes", value: "164", sub: "exact, not banded", hue: "peri", countTo: 164 },
  { id: "ai", label: "AI calls", value: "5", sub: "about $0.02, then 0", hue: "peri", countTo: 5 },
  { id: "matches", label: "matches", value: "276,594", sub: "tier + fit score", hue: "mint", countTo: 276594 },
  { id: "proof", label: "brute-force proof", value: "0", sub: "mismatches, 40 s", hue: "mint", control: true },
  { id: "email", label: "email", value: "best pick", sub: "with the reasons", hue: "mint" },
];

export interface PipeEdge {
  from: string;
  to: string;
  packets: number;
  control?: boolean;
}

// packets narrow 14 -> 9 -> 5 -> 3 through the funnel: the work collapsing is the climax
export const EDGES: readonly PipeEdge[] = [
  { from: "sched", to: "sites", packets: 1, control: true },
  { from: "sites", to: "robots", packets: 1 },
  { from: "robots", to: "nova", packets: 1 },
  { from: "nova", to: "prods", packets: 1 },
  { from: "prods", to: "pairs", packets: 14 },
  { from: "pairs", to: "classes", packets: 9 },
  { from: "classes", to: "ai", packets: 5 },
  { from: "ai", to: "matches", packets: 3 },
  { from: "matches", to: "proof", packets: 1, control: true },
  { from: "matches", to: "email", packets: 1 },
];

export const CAPTIONS: readonly string[] = [
  "Every morning at 06:00 IST the crawler wakes up. A manual run is one click away for demos.",
  "It visits 40 lender pages: bank sites, BankBazaar and Paisabazaar, one request a second.",
  "robots.txt is checked for every URL. A block, a 403 or a CAPTCHA means skip. Never bypass.",
  "Amazon Nova Pro reads each changed page once. Every rule must quote the text it came from, and code checks the quote.",
  "The result: 59 products from 26 lenders, one per lender, platform and employment type.",
  "10,000 users times 59 products. Asking an AI about each pair would be 590,000 questions.",
  "Users between the same cut-offs get the same answer from every lender. 164 classes cover all 10,000, exactly.",
  "Only 46 written conditions need reading. 5 AI calls, about $0.02. Every later run needs none.",
  "276,594 matches, each with a tier and a fit score you can add up.",
  "Then the slow way, as proof: all 590,000 pairs re-decided one by one. 0 mismatches, in 40 seconds.",
  "Each user gets an email with their best pick, their top picks and why. Only to the address they gave.",
];

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
export type Point = readonly [number, number];

export interface Layout {
  boxes: Record<string, Box>;
  viewBox: readonly [number, number, number, number];
}

/** Desktop: a snake (top row left to right, bottom row back, proof below). Phone: one column. */
export function layout(vertical: boolean): Layout {
  const boxes: Record<string, Box> = {};
  if (!vertical) {
    const w = 196, h = 108, xs = [24, 272, 520, 768, 1016];
    ["sched", "sites", "robots", "nova", "prods"].forEach((id, i) => (boxes[id] = { x: xs[i], y: 40, w, h }));
    ["email", "matches", "ai", "classes", "pairs"].forEach((id, i) => (boxes[id] = { x: xs[i], y: 250, w, h }));
    boxes.proof = { x: xs[1], y: 432, w, h };
    return { boxes, viewBox: [0, 0, 1236, 560] };
  }
  NODES.forEach((n, i) => (boxes[n.id] = { x: 30, y: 30 + i * 150, w: 300, h: 96 }));
  return { boxes, viewBox: [0, 0, 360, 30 + NODES.length * 150] };
}

/** Facing edges of two boxes: left/right when on the same row, otherwise bottom/top. */
export function anchor(a: Box, b: Box): [Point, Point] {
  if (Math.abs(a.y - b.y) < 4) {
    return a.x < b.x
      ? [[a.x + a.w, a.y + a.h / 2], [b.x, b.y + b.h / 2]]
      : [[a.x, a.y + a.h / 2], [b.x + b.w, b.y + b.h / 2]];
  }
  return a.y < b.y
    ? [[a.x + a.w / 2, a.y + a.h], [b.x + b.w / 2, b.y]]
    : [[a.x + a.w / 2, a.y], [b.x + b.w / 2, b.y + b.h]];
}

/** A straight line when aligned, otherwise an orthogonal elbow through the midpoint. */
export function pathD([p, q]: readonly [Point, Point]): string {
  if (p[0] === q[0] || p[1] === q[1]) return `M${p[0]},${p[1]} L${q[0]},${q[1]}`;
  const my = (p[1] + q[1]) / 2;
  return `M${p[0]},${p[1]} L${p[0]},${my} L${q[0]},${my} L${q[0]},${q[1]}`;
}

/** Which caption belongs to a playhead time, when each node owns `slot` seconds of timeline. */
export const captionAt = (time: number, slot: number): number =>
  Math.min(NODES.length - 1, Math.max(0, Math.floor(time / slot)));
