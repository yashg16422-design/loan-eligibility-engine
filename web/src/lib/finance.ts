// Loan maths for the compare slide. Rates are % per annum, tenure in months, rupees in whole units.
// Same formula as dashboard/src/lib/finance.ts, so the landing and the app quote identical EMIs.

/** Monthly instalment on a reducing-balance loan (the standard Indian bank EMI formula). */
export function emi(principal: number, annualRatePct: number, months: number): number {
  if (principal <= 0 || months <= 0) return 0;
  const r = annualRatePct / 12 / 100;
  if (r === 0) return principal / months;
  const growth = (1 + r) ** months;
  return (principal * r * growth) / (growth - 1);
}

export interface Cost {
  emi: number;
  totalInterest: number;
}

/** EMI and the total interest paid over the whole tenure. */
export function loanCost(principal: number, annualRatePct: number, months: number): Cost {
  const monthly = emi(principal, annualRatePct, months);
  return { emi: monthly, totalInterest: Math.max(monthly * months - principal, 0) };
}
