// Loan maths for the compare view. Rates are % per annum, tenure in months, rupees in whole units.

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
  totalPaid: number;
}

export function loanCost(principal: number, annualRatePct: number, months: number): Cost {
  const monthly = emi(principal, annualRatePct, months);
  const totalPaid = monthly * months;
  return { emi: monthly, totalPaid, totalInterest: Math.max(totalPaid - principal, 0) };
}
