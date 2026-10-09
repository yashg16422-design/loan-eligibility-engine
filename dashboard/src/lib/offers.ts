// Turning raw matches into what a borrower reads: one row per lender, best platform first.
import type { Channel, Match } from "../api/types";

export interface LenderOffer {
  lender_key: string;
  lender: string;
  best: Match; // the platform to apply on
  others: Match[]; // the same lender on other platforms, best first
}

/** Same ranking Workflow C uses for its email: eligible first, fit score, then lowest rate. */
export function compareMatches(a: Match, b: Match): number {
  return (
    Number(b.tier === "eligible") - Number(a.tier === "eligible") ||
    b.fit_score - a.fit_score ||
    (a.interest_rate_min ?? Infinity) - (b.interest_rate_min ?? Infinity) ||
    a.product_name.localeCompare(b.product_name)
  );
}

export function groupByLender(matches: Match[]): LenderOffer[] {
  const byLender = new Map<string, Match[]>();
  for (const m of matches) byLender.set(m.lender_key, [...(byLender.get(m.lender_key) ?? []), m]);
  return [...byLender.values()]
    .map((list) => {
      const [best, ...others] = [...list].sort(compareMatches);
      return { lender_key: best.lender_key, lender: best.lender, best, others };
    })
    .sort((a, b) => compareMatches(a.best, b.best));
}

export type SortKey = "fit" | "rate" | "amount";

export function sortOffers(offers: LenderOffer[], key: SortKey): LenderOffer[] {
  const by: Record<SortKey, (a: LenderOffer, b: LenderOffer) => number> = {
    fit: (a, b) => compareMatches(a.best, b.best),
    rate: (a, b) => (a.best.interest_rate_min ?? Infinity) - (b.best.interest_rate_min ?? Infinity),
    amount: (a, b) => (b.best.loan_amount_max ?? -1) - (a.best.loan_amount_max ?? -1),
  };
  return [...offers].sort(by[key]);
}

/** For use inside a sentence: "Best on the lender's site, also on BankBazaar". */
export const CHANNEL_PHRASE: Record<Channel, string> = {
  direct: "the lender's site",
  bankbazaar: "BankBazaar",
  paisabazaar: "Paisabazaar",
};

export const CHANNEL_LABEL: Record<Channel, string> = {
  direct: "Lender's site",
  bankbazaar: "BankBazaar",
  paisabazaar: "Paisabazaar",
};

/** Requirements of the shortlisted offers, merged and de-duplicated for one checklist. */
export function checklist(matches: Match[]): string[] {
  const items = matches
    .flatMap((m) => (m.requirements ?? "").split(/;\s*/))
    .map((s) => s.trim().replace(/\.$/, ""))
    .filter((s) => s.length > 3 && !/could not be verified|not published/i.test(s));
  const seen = new Map<string, string>();
  for (const item of items) {
    const key = item.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (!seen.has(key)) seen.set(key, item);
  }
  return [...seen.values()];
}
