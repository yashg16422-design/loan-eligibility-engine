// Indian number formatting: rupees grouped the Indian way, large amounts in lakh and crore.

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function rupees(n: number | null | undefined): string {
  return n == null ? "-" : `₹${inr.format(Math.round(n))}`;
}

/** ₹5 lakh, ₹40 lakh, ₹1.5 crore: how loan sizes are spoken about in India. */
export function rupeesShort(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n >= 1e7) return `₹${trim(n / 1e7)} crore`;
  if (n >= 1e5) return `₹${trim(n / 1e5)} lakh`;
  return rupees(n);
}

function trim(x: number): string {
  return x.toFixed(x < 10 ? 1 : 0).replace(/\.0$/, "");
}

export function rate(min: number | null, max: number | null): string {
  if (min == null) return "Rate on request";
  if (max == null || max === min) return `from ${min}%`;
  return `${min}% to ${max}%`;
}

export const EMPLOYMENT_LABEL = {
  salaried: "Salaried",
  self_employed: "Self-employed",
  business: "Business owner",
} as const;

export function count(n: number, one: string, many = `${one}s`): string {
  return `${inr.format(n)} ${n === 1 ? one : many}`;
}
