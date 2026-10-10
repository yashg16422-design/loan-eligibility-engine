// The fit score's parts, recomputed with the formula in sql/matching/stage3_expand.sql (and
// dashboard/src/lib/fit.ts), so the "why you qualify" slide adds up to the server's number.

export interface FitInput {
  tier: "eligible" | "conditional";
  userIncome: number;
  userScore: number;
  minIncome: number | null;
  minScore: number | null;
  rateFrom: number | null;
}

export interface FitParts {
  tier: number;
  income: number;
  credit: number;
  rate: number;
}

const clamp = (x: number, lo: number, hi: number): number => Math.min(Math.max(x, lo), hi);

/** Points per part. A rule the lender doesn't publish earns half credit: no reward, no penalty. */
export function fitParts(f: FitInput): FitParts {
  return {
    tier: f.tier === "eligible" ? 60 : 35,
    income: f.minIncome == null ? 7.5 : (15 * clamp(f.userIncome / f.minIncome - 1, 0, 2)) / 2,
    credit: f.minScore == null ? 5 : (10 * clamp(f.userScore - f.minScore, 0, 100)) / 100,
    rate: f.rateFrom == null ? 7.5 : (15 * Math.max(30 - Math.min(f.rateFrom, 30), 0)) / 30,
  };
}

/**
 * Parts rounded to one decimal that add up exactly to the server's total (largest remainder),
 * so the slide never shows 60 + 15 + 5 + 10.3 under a "90.2".
 */
export function displayParts(parts: number[], total: number): number[] {
  const tenths = parts.map((p) => p * 10);
  const floors = tenths.map(Math.floor);
  let missing = Math.round(total * 10) - floors.reduce((a, b) => a + b, 0);
  const order = tenths.map((t, i) => [t - Math.floor(t), i] as const).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) {
    if (missing <= 0) break;
    floors[i] += 1;
    missing -= 1;
  }
  return floors.map((x) => x / 10);
}
