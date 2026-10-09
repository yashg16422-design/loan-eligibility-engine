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

/** Indices of slots not yet taken, so two floating questions never share a spot. */
export function freeSlots(total: number, used: Iterable<number>): number[] {
  const taken = new Set(used);
  return Array.from({ length: total }, (_, i) => i).filter((i) => !taken.has(i));
}

/** Where floating questions may sit, in % of the section: around the centre column on desktop,
 *  in bands above and below it on phones. */
export const SLOTS_DESKTOP: ReadonlyArray<readonly [number, number]> = [
  [6, 16], [7, 36], [6, 58], [8, 78], [77, 18], [79, 36], [76, 60], [78, 80], [32, 91],
];
export const SLOTS_PHONE: ReadonlyArray<readonly [number, number]> = [
  [4, 11], [34, 16], [6, 21], [4, 82], [34, 87], [8, 92],
];
