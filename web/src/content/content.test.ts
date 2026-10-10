// The landing quotes real numbers. These tests recompute every one of them from the mock export
// of the live database (public/mock/, copied from docs/extras/mock/) and from README.md, so the
// pitch can't drift from what was measured.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { loanCost } from "../lib/finance";
import { displayParts, fitParts } from "../lib/fit";
import { inr } from "../lib/format";
import { bestPerLender, type MatchRow, offersFor, type ProductRow } from "../lib/offers";
import { NODES } from "../lib/pipeline";
import { AARAV, COMPARE, displayName, EMAIL_ROWS, LENDERS, RANKED, TOP_FIT } from "./demo";

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");
const mock = <T>(name: string): T => JSON.parse(read(`../../public/mock/${name}.json`)) as T;

interface User {
  user_id: string;
  name: string;
  monthly_income: number;
  credit_score: number;
  age: number;
  employment_status: string;
}
type Product = ProductRow & { min_monthly_income: number | null; min_credit_score: number | null };

const users = mock<User[]>("users");
const products = mock<Product[]>("products");
const matches = mock<MatchRow[]>("matches");
const aarav = users.find((u) => u.name.startsWith("Aarav"));
if (!aarav) throw new Error("Aarav is missing from users.json");
const offers = offersFor(aarav.user_id, matches, products);
const via = (channel: string): string =>
  channel === "direct" ? "direct" : "via " + ({ bankbazaar: "BankBazaar", paisabazaar: "Paisabazaar" }[channel] ?? channel);

describe("demo borrower (Aarav) matches the mocks", () => {
  it("profile, match counts, lenders and best rate", () => {
    expect(AARAV.name).toBe(aarav.name.split(" ")[0] + " " + aarav.name.split(" ")[1][0] + ".");
    expect([AARAV.income, AARAV.score, AARAV.age]).toEqual([aarav.monthly_income, aarav.credit_score, aarav.age]);
    expect(AARAV.matches).toBe(offers.length);
    expect(AARAV.eligible).toBe(offers.filter((o) => o.tier === "eligible").length);
    expect(AARAV.lenders).toBe(new Set(offers.map((o) => o.lender)).size);
    expect(AARAV.bestRate).toBe(offers[0].rateFrom);
  });

  it("the ranked slide is each lender's best platform, in order", () => {
    const top = bestPerLender(offers).slice(0, RANKED.length);
    expect(RANKED).toEqual(
      top.map((o) => ({ lender: displayName(o.lender), via: via(o.channel), rate: o.rateFrom, fit: o.fit, verified: o.verified })),
    );
  });

  it("the fit breakdown adds up to the top match's score", () => {
    const best = offers[0];
    const product = products.find((p) => p.lender === best.lender && p.channel === best.channel);
    if (!product) throw new Error("top product missing");
    const p = fitParts({
      tier: best.tier, userIncome: aarav.monthly_income, userScore: aarav.credit_score,
      minIncome: product.min_monthly_income, minScore: product.min_credit_score, rateFrom: product.interest_rate_min,
    });
    expect(TOP_FIT.total).toBe(best.fit);
    expect(TOP_FIT.minIncome).toBe(product.min_monthly_income);
    expect(TOP_FIT.rate).toBe(product.interest_rate_min);
    expect(TOP_FIT.incomeMultiple).toBe(Math.round((aarav.monthly_income / 15000) * 10) / 10);
    expect(displayParts([p.tier, p.income, p.credit, p.rate], best.fit)).toEqual([...TOP_FIT.parts]);
  });

  it("compare and email rows use real starting rates and fit scores", () => {
    for (const { lender, rate } of COMPARE.lenders) {
      expect(offers.some((o) => displayName(o.lender) === lender && o.rateFrom === rate), lender).toBe(true);
    }
    for (const r of EMAIL_ROWS) {
      expect(offers.some((o) => displayName(o.lender) === r.lender && via(o.channel) === r.via && o.rateFrom === r.rate && o.fit === r.fit), r.lender).toBe(true);
    }
  });

  it("the ticker lists exactly the catalog's 26 lenders", () => {
    expect([...LENDERS].sort()).toEqual([...new Set(products.map((p) => displayName(p.lender)))].sort());
  });
});

describe("index.html copy matches the data", () => {
  const html = read("../../index.html");
  it("quotes Aarav's numbers and the fit breakdown", () => {
    expect(html).toContain(`${AARAV.matches} matches across ${AARAV.lenders} lenders`);
    expect(html).toContain(`${AARAV.eligible} meet every published rule`);
    expect(html).toContain(`<b>${AARAV.bestRate}%</b><span>best rate</span>`);
    expect(html).toContain(`₹${AARAV.income.toLocaleString("en-IN")}`);
    expect(html).toContain(`<div class="in">${AARAV.score}</div>`);
    expect(html).toContain(`Income is ${TOP_FIT.incomeMultiple}× the ${inr(TOP_FIT.minIncome)} minimum`);
    for (const part of TOP_FIT.parts) expect(html).toContain(`<b>+${part}</b>`);
    expect(html).toContain(`<b>${TOP_FIT.total}</b>`);
    expect(html).toContain(`${inr(COMPARE.principal)} over 3 years`);
    expect(COMPARE.months).toBe(36);
    expect(loanCost(COMPARE.principal, 9.5, COMPARE.months).emi).toBeGreaterThan(0);
  });
  it("says what the product is, and isn't", () => {
    expect(html).toContain("Not a loan offer or approval");
  });
  it("sends every primary call to action into the app", () => {
    const ctas = [...html.matchAll(/<a class="btn btn-primary" href="([^"]+)">Check my eligibility/g)].map((m) => m[1]);
    expect(ctas.length).toBeGreaterThanOrEqual(3);
    // The app's check page; "See the engine" opens the app's Overview (bulk upload + workflows).
    expect(new Set(ctas)).toEqual(new Set(["%APP_URL%check"]));
    expect(html).toContain('href="%APP_URL%"');
    expect(html).not.toMatch(/href="#[^"]*">See the engine/);
  });
});

describe("Treasure Hunt figures come from README.md", () => {
  const readme = read("../../../README.md");
  it.each(["590,000", "164", "276,594", "59"])("README states %s", (figure) => {
    expect(readme).toContain(figure);
  });
  it("every pipeline node figure appears in the README", () => {
    for (const n of NODES.filter((x) => x.countTo !== undefined)) {
      expect(readme, n.id).toContain(n.value);
    }
  });
});
