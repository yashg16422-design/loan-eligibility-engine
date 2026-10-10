// Ranking used by the "see every match" slide: one row per lender (its best platform), ordered
// by fit score, then by the lower starting rate. Mirrors how the dashboard groups offers.

export interface MatchRow {
  user_id: string;
  product_id: string;
  tier: "eligible" | "conditional";
  fit_score: number;
}

export interface ProductRow {
  product_id: string;
  lender: string;
  channel: string;
  interest_rate_min: number | null;
  verification: string;
}

export interface Offer {
  lender: string;
  channel: string;
  rateFrom: number | null;
  fit: number;
  tier: MatchRow["tier"];
  verified: boolean;
}

const byFitThenRate = (a: Offer, b: Offer): number =>
  b.fit - a.fit || (a.rateFrom ?? Infinity) - (b.rateFrom ?? Infinity);

/** All of one user's offers, best first. */
export function offersFor(userId: string, matches: MatchRow[], products: ProductRow[]): Offer[] {
  const byId = new Map(products.map((p) => [p.product_id, p]));
  return matches
    .filter((m) => m.user_id === userId)
    .flatMap((m) => {
      const p = byId.get(m.product_id);
      return p
        ? [{ lender: p.lender, channel: p.channel, rateFrom: p.interest_rate_min, fit: m.fit_score, tier: m.tier, verified: p.verification === "ok" }]
        : [];
    })
    .sort(byFitThenRate);
}

/** Keep each lender's best offer only (the platform where the borrower fits best). */
export function bestPerLender(offers: Offer[]): Offer[] {
  const seen = new Set<string>();
  return [...offers].sort(byFitThenRate).filter((o) => !seen.has(o.lender) && seen.add(o.lender));
}
