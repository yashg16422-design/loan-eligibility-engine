import { describe, expect, it } from "vitest";
import { ANSWERS, classify, overlaps, pickSpot, QUESTIONS, seeded, shuffle } from "./ask";
import { burstPoints, fit } from "./camera";
import { emi, loanCost } from "./finance";
import { displayParts, fitParts } from "./fit";
import { count, inr, step } from "./format";
import { decodeInt16, latLonToXYZ, progress, smoothstep } from "./geo";
import { bestPerLender, type MatchRow, offersFor, type ProductRow } from "./offers";
import { anchor, CAPTIONS, captionAt, EDGES, layout, NODES, pathD } from "./pipeline";
import { plain, tokenize } from "./statement";

describe("finance", () => {
  it("matches the standard EMI for ₹5,00,000 at 9.5% over 36 months", () => {
    expect(emi(500000, 9.5, 36)).toBeCloseTo(16016.47, 2); // checked with Decimal arithmetic
  });
  it("splits a zero-rate loan evenly and refuses nonsense input", () => {
    expect(emi(36000, 0, 36)).toBe(1000);
    expect(emi(0, 10, 12)).toBe(0);
    expect(emi(1000, 10, 0)).toBe(0);
  });
  it("total interest is EMI × months minus the principal", () => {
    const c = loanCost(500000, 10.5, 36);
    expect(c.totalInterest).toBeCloseTo(c.emi * 36 - 500000, 6);
    expect(loanCost(500000, 10.5, 36).totalInterest).toBeGreaterThan(loanCost(500000, 9.5, 36).totalInterest);
  });
});

describe("format", () => {
  it("uses Indian grouping for rupees and international grouping for counts", () => {
    expect(inr(500000)).toBe("₹5,00,000");
    expect(inr(16016.47)).toBe("₹16,016");
    expect(count(590000)).toBe("590,000");
    expect(count(276593.6)).toBe("276,594");
  });
  it("pads step counters", () => {
    expect(step(0, 9)).toBe("01 / 09");
    expect(step(10, 11)).toBe("11 / 11");
  });
});

describe("fit score", () => {
  const axis = { tier: "eligible", userIncome: 48000, userScore: 742, minIncome: 15000, minScore: null, rateFrom: 9.5 } as const;
  it("rebuilds Axis Bank's 90.2 for Aarav from its parts", () => {
    const p = fitParts(axis);
    expect(p).toEqual({ tier: 60, income: 15, credit: 5, rate: 10.25 });
    expect(displayParts([p.tier, p.income, p.credit, p.rate], 90.2)).toEqual([60, 15, 5, 10.2]);
  });
  it("gives half credit where the lender publishes no number", () => {
    const p = fitParts({ ...axis, tier: "conditional", minIncome: null, rateFrom: null });
    expect(p).toEqual({ tier: 35, income: 7.5, credit: 5, rate: 7.5 });
  });
  it("caps income headroom at 3× the minimum and score margin at 100 points", () => {
    expect(fitParts({ ...axis, userIncome: 1e7 }).income).toBe(15);
    expect(fitParts({ ...axis, minScore: 600, userScore: 900 }).credit).toBe(10);
    expect(fitParts({ ...axis, minScore: 800 }).credit).toBe(0);
  });
  it("display parts always add up to the server total", () => {
    for (const total of [90.2, 81.3, 77.75, 60]) {
      const parts = displayParts([60, 7.333, 3.333, total - 70.666], total);
      expect(Math.round(parts.reduce((a, b) => a + b, 0) * 10)).toBe(Math.round(total * 10));
    }
  });
});

describe("offers", () => {
  const products: ProductRow[] = [
    { product_id: "a1", lender: "Axis", channel: "bankbazaar", interest_rate_min: 9.5, verification: "ok" },
    { product_id: "a2", lender: "Axis", channel: "paisabazaar", interest_rate_min: 9.99, verification: "ok" },
    { product_id: "b1", lender: "Bee", channel: "direct", interest_rate_min: 11, verification: "unverified" },
    { product_id: "c1", lender: "Cee", channel: "direct", interest_rate_min: 10, verification: "ok" },
  ];
  const m = (product_id: string, fit_score: number, user_id = "u"): MatchRow => ({ user_id, product_id, fit_score, tier: "eligible" });
  const matches = [m("a2", 90), m("a1", 90.2), m("b1", 80), m("c1", 80), m("c1", 99, "someone-else")];

  it("ranks one user's offers by fit, then the lower rate", () => {
    expect(offersFor("u", matches, products).map((o) => o.lender + "/" + o.channel)).toEqual([
      "Axis/bankbazaar", "Axis/paisabazaar", "Cee/direct", "Bee/direct",
    ]);
  });
  it("keeps each lender's best platform only", () => {
    const best = bestPerLender(offersFor("u", matches, products));
    expect(best.map((o) => o.lender)).toEqual(["Axis", "Cee", "Bee"]);
    expect(best[0]).toMatchObject({ channel: "bankbazaar", verified: true });
    expect(best[2].verified).toBe(false);
  });
  it("skips matches whose product is missing from the catalog", () => {
    expect(offersFor("u", [m("gone", 99)], products)).toEqual([]);
  });
});

describe("ask", () => {
  it("routes questions by keyword, first rule wins", () => {
    expect(classify("Does checking hurt my CIBIL?")).toBe("score");
    expect(classify("why do they reject me")).toBe("reject");
    expect(classify("lowest rate for salaried")).toBe("platform");
    expect(classify("which papers do I need")).toBe("docs");
    expect(classify("did HDFC change the rules")).toBe("daily");
    expect(classify("EMI on 3 lakh")).toBe("emi");
    expect(classify("hello")).toBe("all");
    expect(classify("")).toBe("all");
  });
  it("every sample question is answered by the feature it is tagged with", () => {
    for (const [q, key] of QUESTIONS) {
      expect(ANSWERS[key], q).toBeDefined();
      expect(ANSWERS[key].href).toMatch(/^#(journey|engine)$/);
    }
  });
  it("detects overlap, including the padding gap", () => {
    const a = { x: 0, y: 0, w: 10, h: 10 };
    expect(overlaps(a, { x: 5, y: 5, w: 10, h: 10 })).toBe(true);
    expect(overlaps(a, { x: 12, y: 0, w: 10, h: 10 })).toBe(false);
    expect(overlaps(a, { x: 12, y: 0, w: 10, h: 10 }, 4)).toBe(true);
  });
  it("never places a question on the ask box or another question", () => {
    const area = { x: 0, y: 90, w: 1440, h: 730 };
    const core = { x: 380, y: 260, w: 680, h: 380 }; // heading, live line, form
    const rand = seeded(7);
    const placed = [core];
    for (let i = 0; i < 400; i++) {
      const spot = pickSpot(area, { w: 260, h: 44 }, placed, rand, 16);
      if (!spot) continue;
      expect(placed.some((r) => overlaps(spot, r, 16))).toBe(false);
      expect(spot.x).toBeGreaterThanOrEqual(area.x);
      expect(spot.y + spot.h).toBeLessThanOrEqual(area.y + area.h);
      if (placed.length < 7) placed.push(spot); // keep a realistic crowd on screen
    }
    expect(placed.length).toBe(7);
  });
  it("gives up instead of overlapping when there is no room", () => {
    const area = { x: 0, y: 0, w: 300, h: 100 };
    expect(pickSpot(area, { w: 200, h: 50 }, [area], seeded(1))).toBeNull();
    expect(pickSpot(area, { w: 400, h: 50 }, [], seeded(1))).toBeNull();
  });
  it("shuffles without losing questions, reproducibly", () => {
    const s = shuffle(QUESTIONS, seeded(3));
    expect(s).toHaveLength(QUESTIONS.length);
    expect(new Set(s)).toEqual(new Set(QUESTIONS));
    expect(shuffle(QUESTIONS, seeded(3))).toEqual(s);
    expect([...Array(1000)].map(seeded(9)).every((x) => x >= 0 && x < 1)).toBe(true);
  });
});

describe("statement", () => {
  const src = "Learn by getting [rejected]. It costs [credit score] points.";
  it("colours the rejection coral and other bracketed words amber", () => {
    const words = tokenize(src).filter((t) => t.kind === "word");
    expect(words.find((w) => w.text === "rejected.")).toBeUndefined(); // the bracket ends before "."
    expect(words.find((w) => w.text === "rejected")).toMatchObject({ tone: "coral" });
    expect(words.filter((w) => w.kind === "word" && w.tone === "amber").map((w) => w.text)).toEqual(["credit", "score"]);
  });
  it("keeps every character, so the reveal reads as the original sentence", () => {
    expect(tokenize(src).map((t) => t.text).join("")).toBe(plain(src));
    expect(plain(src)).toBe("Learn by getting rejected. It costs credit score points.");
  });
});

describe("pipeline diagram", () => {
  it("has one caption per node and edges between known nodes", () => {
    expect(CAPTIONS).toHaveLength(NODES.length);
    const ids = new Set(NODES.map((n) => n.id));
    for (const e of EDGES) {
      expect(ids.has(e.from) && ids.has(e.to), `${e.from}->${e.to}`).toBe(true);
    }
  });
  it("narrows the packets through the funnel: the climax", () => {
    const p = (from: string): number => EDGES.find((e) => e.from === from)?.packets ?? 0;
    expect([p("prods"), p("pairs"), p("classes"), p("ai")]).toEqual([14, 9, 5, 3]);
  });
  for (const vertical of [false, true]) {
    it(`lays out every node inside the viewBox without overlap (${vertical ? "phone" : "desktop"})`, () => {
      const { boxes, viewBox } = layout(vertical);
      const all = NODES.map((n) => boxes[n.id]);
      for (const b of all) {
        expect(b.x).toBeGreaterThanOrEqual(0);
        expect(b.y).toBeGreaterThanOrEqual(0);
        expect(b.x + b.w).toBeLessThanOrEqual(viewBox[2]);
        expect(b.y + b.h).toBeLessThanOrEqual(viewBox[3]);
      }
      for (let i = 0; i < all.length; i++)
        for (let j = i + 1; j < all.length; j++) {
          const [a, b] = [all[i], all[j]];
          const apart = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
          expect(apart, `${NODES[i].id} / ${NODES[j].id}`).toBe(true);
        }
    });
  }
  it("routes edges between facing sides", () => {
    const a = { x: 0, y: 0, w: 10, h: 10 }, right = { x: 20, y: 0, w: 10, h: 10 }, below = { x: 40, y: 30, w: 10, h: 10 };
    expect(anchor(a, right)).toEqual([[10, 5], [20, 5]]);
    expect(anchor(right, a)).toEqual([[20, 5], [10, 5]]);
    expect(anchor(a, below)).toEqual([[5, 10], [45, 30]]);
    expect(pathD([[10, 5], [20, 5]])).toBe("M10,5 L20,5");
    expect(pathD([[5, 10], [45, 30]])).toBe("M5,10 L5,20 L45,20 L45,30");
  });
  it("maps the playhead to a caption, clamped to the ends", () => {
    expect(captionAt(0, 1.4)).toBe(0);
    expect(captionAt(1.5, 1.4)).toBe(1);
    expect(captionAt(-1, 1.4)).toBe(0);
    expect(captionAt(999, 1.4)).toBe(NODES.length - 1);
  });
});

describe("comic camera", () => {
  it("centres a frame in the viewport at the padded scale", () => {
    const c = fit([0, 0, 1600, 900], 1440, 900, 0.86);
    expect(c.s).toBeCloseTo(0.774, 6); // width-bound: 1440 × 0.86 / 1600 < 900 × 0.86 / 900
    expect(c.x + 800 * c.s).toBeCloseTo(720, 6);
    expect(c.y + 450 * c.s).toBeCloseTo(450, 6);
  });
  it("draws the YES burst as alternating spikes on a 100 × 100 box", () => {
    const pts = burstPoints().split(" ").map((p) => p.split(",").map(Number));
    expect(pts).toHaveLength(28);
    for (const [x, y] of pts) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(100);
    }
    expect(pts[0]).toEqual([98, 50]);
  });
});

describe("geo", () => {
  it("decodes little-endian Int16 base64", () => {
    const bytes = new Int16Array([2120, 7284, -1]).buffer;
    const b64 = btoa(String.fromCharCode(...new Uint8Array(bytes)));
    expect([...decodeInt16(b64)]).toEqual([2120, 7284, -1]);
  });
  it("puts the poles on the y axis and stays on the sphere", () => {
    const [x, y, z] = latLonToXYZ(90, 0, 2);
    expect(Math.abs(x) + Math.abs(z)).toBeCloseTo(0, 9);
    expect(y).toBeCloseTo(2, 9);
    const p = latLonToXYZ(21.2, 72.84);
    expect(Math.hypot(...p)).toBeCloseTo(1, 9);
  });
  it("smoothstep and progress clamp, and smoothstep can fall", () => {
    expect(smoothstep(0, 1, 0.5)).toBe(0.5);
    expect(smoothstep(2.1, 0.9, 0)).toBe(1);
    expect(smoothstep(2.1, 0.9, 5)).toBe(0);
    expect(progress(5, 0, 10)).toBe(0.5);
    expect(progress(-5, 0, 10)).toBe(0);
    expect(progress(50, 0, 10)).toBe(1);
  });
});
