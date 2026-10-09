// The fit score's parts, recomputed with the formula in sql/matching/stage3_expand.sql so a
// borrower can see WHY an offer scored 90.2: every point traces to a published lender rule.
import type { Match, Profile } from "../api/types";

export interface FitPart {
  key: "tier" | "income" | "credit" | "rate";
  label: string;
  points: number;
  max: number;
  unknown: boolean; // the lender publishes no number here: half credit, neither reward nor penalty
}

export function fitParts(m: Match, u: Profile): FitPart[] {
  const tier = m.tier === "eligible" ? 60 : 35;
  const income =
    m.min_monthly_income == null
      ? 7.5
      : (15 * Math.min(Math.max(u.monthly_income / m.min_monthly_income - 1, 0), 2)) / 2;
  const credit =
    m.min_credit_score == null
      ? 5
      : (10 * Math.min(Math.max(u.credit_score - m.min_credit_score, 0), 100)) / 100;
  const rate =
    m.interest_rate_min == null ? 7.5 : (15 * Math.max(30 - Math.min(m.interest_rate_min, 30), 0)) / 30;
  return [
    { key: "tier", label: m.tier === "eligible" ? "Meets every published rule" : "Meets the checkable rules", points: tier, max: 60, unknown: false },
    { key: "income", label: "Income headroom", points: income, max: 15, unknown: m.min_monthly_income == null },
    { key: "credit", label: "Credit score margin", points: credit, max: 10, unknown: m.min_credit_score == null },
    { key: "rate", label: "Starting rate", points: rate, max: 15, unknown: m.interest_rate_min == null },
  ];
}

/**
 * Parts rounded to one decimal that add up EXACTLY to the server's total (largest-remainder
 * rounding), so the breakdown never shows 60 + 15 + 5 + 10.3 = 90.3 under a "90.2".
 */
export function displayParts(parts: FitPart[], total: number): number[] {
  const tenths = parts.map((p) => p.points * 10);
  const floors = tenths.map(Math.floor);
  let missing = Math.round(total * 10) - floors.reduce((a, b) => a + b, 0);
  const order = tenths.map((t, i) => [t - Math.floor(t), i] as const).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) {
    if (missing <= 0) break;
    floors[i] += 1;
    missing -= 1;
  }
  return floors.map((f) => f / 10);
}
