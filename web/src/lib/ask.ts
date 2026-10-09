// "What's stopping your loan?": the sample questions that type themselves in, and the part of
// ClickPar Match that answers each one. classify() routes a typed question to an answer by keyword.

export type AnswerKey = "all" | "reject" | "platform" | "score" | "docs" | "daily" | "emi";

export interface Answer {
  tag: string; // the feature that answers it, shown under the floating question
  title: string;
  body: string;
  href: string; // in-page section that shows the feature
  cta: string;
}

export const QUESTIONS: ReadonlyArray<readonly [string, AnswerKey]> = [
  ["does checking my eligibility hurt my CIBIL?", "score"],
  ["why do I keep getting rejected?", "reject"],
  ["which bank gives salaried people the lowest rate?", "platform"],
  ["I'm self-employed. who will even lend to me?", "all"],
  ["why does BankBazaar say yes and Paisabazaar say no?", "platform"],
  ["is ₹25,000 a month enough for a personal loan?", "all"],
  ["what documents will they actually ask for?", "docs"],
  ["can I get ₹5 lakh at 29 with a 742 score?", "all"],
  ["how many applications before my score drops?", "score"],
  ["did the bank change its rules again?", "daily"],
  ["which lenders accept a 700 credit score?", "all"],
  ["what EMI would I pay on ₹3 lakh?", "emi"],
];

export const ANSWERS: Readonly<Record<AnswerKey, Answer>> = {
  all: {
    tag: "every lender at once",
    title: "We check every lender at once.",
    body: "All 59 products from 26 lenders are scored against your four numbers together, so you see who is likely to say yes before you apply anywhere.",
    href: "#journey",
    cta: "See your ranked matches",
  },
  reject: {
    tag: "the reason behind every match",
    title: "Every match comes with its reason.",
    body: "“Your income is 3.2× the minimum.” Every point of the fit score traces back to a rule the lender published.",
    href: "#journey",
    cta: "See how the score adds up",
  },
  platform: {
    tag: "best platform per lender",
    title: "We read every platform, then compare.",
    body: "The same lender can ask for different things on its own site, BankBazaar and Paisabazaar. We show where you actually qualify, and the best rate.",
    href: "#engine",
    cta: "See how we read lender pages",
  },
  score: {
    tag: "no credit bureau pull",
    title: "Checking never touches your score.",
    body: "You type four numbers. Nothing is sent to a credit bureau, so you can check as often as you like and apply only where you fit.",
    href: "#journey",
    cta: "Start with four numbers",
  },
  docs: {
    tag: "document checklist",
    title: "Your shortlist comes with its checklist.",
    body: "We merge what your top lenders ask for, like work experience or salary account rules, into one list before you apply.",
    href: "#journey",
    cta: "See the shortlist",
  },
  daily: {
    tag: "re-read daily, 06:00 IST",
    title: "Rules change. We re-read them every morning.",
    body: "Lender pages are crawled every day. When a rule changes, every user is re-matched automatically and told if something new fits.",
    href: "#engine",
    cta: "See the daily crawl",
  },
  emi: {
    tag: "EMI and total cost",
    title: "Compare the real cost before you choose.",
    body: "Pick three lenders and see monthly EMI and total interest side by side, worked out from each one's starting rate.",
    href: "#journey",
    cta: "See the comparison",
  },
};

// Checked in order: the first rule that matches wins, so score worries beat generic "rate" words.
const RULES: ReadonlyArray<readonly [RegExp, AnswerKey]> = [
  [/cibil|credit score|score drop|hurt|enquir/, "score"],
  [/reject|declin|denied|why (do|did)/, "reject"],
  [/bankbazaar|paisabazaar|site|platform|different|lowest|rate/, "platform"],
  [/document|papers|proof|salary slip/, "docs"],
  [/change|update|new rule/, "daily"],
  [/emi|interest|cost|repay/, "emi"],
];

/** Route a free-text question to the answer that fits it best; anything else gets "all". */
export function classify(question: string): AnswerKey {
  const q = question.toLowerCase();
  return RULES.find(([re]) => re.test(q))?.[1] ?? "all";
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Do two boxes overlap, counting `pad` px of breathing room between them? */
export const overlaps = (a: Box, b: Box, pad = 0): boolean =>
  a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;

/**
 * A random spot for a w × h question inside `area` that keeps `pad` px clear of every box in
 * `avoid` (the heading, the ask box, other questions). Tries `tries` random candidates and
 * gives up with null rather than ever placing a question on top of something.
 */
export function pickSpot(
  area: Box, size: { w: number; h: number }, avoid: readonly Box[], rand: () => number, pad = 16, tries = 80,
): Box | null {
  const freeW = area.w - size.w, freeH = area.h - size.h;
  if (freeW < 0 || freeH < 0) return null;
  for (let i = 0; i < tries; i++) {
    const spot = { x: area.x + rand() * freeW, y: area.y + rand() * freeH, w: size.w, h: size.h };
    if (!avoid.some((r) => overlaps(spot, r, pad))) return spot;
  }
  return null;
}

/** Fisher-Yates shuffle into a new array. */
export function shuffle<T>(items: readonly T[], rand: () => number): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Small seeded PRNG (mulberry32), so the reduced-motion layout is the same on every visit. */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
