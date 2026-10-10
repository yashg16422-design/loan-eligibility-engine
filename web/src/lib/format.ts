// Number formatting. Rupees use Indian grouping (₹5,00,000); pipeline counts use the
// international grouping the README measured them in (590,000), so they match it verbatim.

/** Whole rupees with Indian digit grouping, e.g. 500000 -> "₹5,00,000". */
export const inr = (x: number): string => "₹" + Math.round(x).toLocaleString("en-IN");

/** A rounded count with international grouping, e.g. 276594 -> "276,594". */
export const count = (x: number): string => Math.round(x).toLocaleString("en-US");

/** A 1-based step counter, e.g. step(0, 9) -> "01 / 09". */
export const step = (i: number, total: number): string =>
  String(i + 1).padStart(2, "0") + " / " + String(total).padStart(2, "0");
