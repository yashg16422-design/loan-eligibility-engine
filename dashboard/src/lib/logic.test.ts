import { describe, expect, it } from "vitest";
import type { CatalogProduct, Match, Profile } from "../api/types";
import live from "./__fixtures__/live_decisions.json";
import { decide, nextUnlock, passesCompiledRules } from "./eligibility";
import { emi, loanCost } from "./finance";
import { rate, rupeesShort } from "./format";
import { checklist, groupByLender, sortOffers } from "./offers";

const catalog = live.products as unknown as CatalogProduct[];
const profile = live.profile as Profile;
const base: CatalogProduct = {
  product_id: "p",
  lender: "Test Bank",
  lender_key: "test",
  channel: "direct",
  product_name: "Test",
  product_url: null,
  interest_rate_min: 10,
  interest_rate_max: 20,
  rate_type: null,
  loan_amount_min: null,
  loan_amount_max: null,
  tenure_months_max: null,
  min_monthly_income: 25000,
  min_credit_score: 700,
  max_credit_score: null,
  min_age: 21,
  max_age: 60,
  employment_types: ["salaried"],
  other_criteria_text: null,
  verification: "ok",
  last_seen_at: null,
  compiled_rules: null,
  compiled_requirements: null,
};

describe("simulator mirrors Workflow B", () => {
  it("reproduces the server's decision on every live product", () => {
    const serverTiers = live.server_tiers as Record<string, string>;
    const mismatches = catalog.filter(
      (p) => decide(p, profile) !== (serverTiers[p.product_id] ?? "not_eligible"),
    );
    expect(catalog.length).toBe(59);
    expect(mismatches.map((p) => p.product_name)).toEqual([]);
  });

  it("follows the decided CTE case by case", () => {
    expect(decide(base, profile)).toBe("eligible"); // no free text left
    expect(decide({ ...base, min_credit_score: 800 }, profile)).toBe("not_eligible");
    expect(decide({ ...base, employment_types: ["business"] }, profile)).toBe("not_eligible");
    const text = { ...base, other_criteria_text: "2 years experience" };
    expect(decide(text, profile)).toBe("conditional"); // never compiled: never a rejection
    expect(decide({ ...text, compiled_rules: [], compiled_requirements: ["2 years experience"] }, profile)).toBe(
      "conditional",
    );
    expect(decide({ ...text, compiled_rules: [], compiled_requirements: [] }, profile)).toBe("eligible");
    const strict = { ...text, compiled_rules: [{ field: "age", op: "<=", value: 30, applies_to: "any" }] as const };
    expect(decide({ ...strict, compiled_rules: [...strict.compiled_rules], compiled_requirements: [] }, profile)).toBe(
      "not_eligible",
    );
  });

  it("rounds compiled thresholds like the SQL (integer fields) and respects applies_to", () => {
    const u = { ...profile, monthly_income: 25001 };
    expect(passesCompiledRules([{ field: "monthly_income", op: ">=", value: 25000.5, applies_to: "any" }], u)).toBe(true);
    expect(passesCompiledRules([{ field: "age", op: "<=", value: 30.9, applies_to: "any" }], { ...u, age: 31 })).toBe(false);
    expect(passesCompiledRules([{ field: "credit_score", op: ">=", value: 900, applies_to: "business" }], u)).toBe(true);
  });

  it("names the smallest real threshold that opens a new lender", () => {
    const low = { ...profile, credit_score: 690 };
    const unlock = nextUnlock([base, { ...base, lender: "Other", lender_key: "o", min_credit_score: 740 }], low);
    expect(unlock).toEqual({ field: "credit_score", to: 700, lenders: ["Test Bank"] });
    expect(nextUnlock([base], profile)).toBeNull(); // already reachable, nothing higher
  });
});

describe("loan maths", () => {
  it("matches the standard EMI formula", () => {
    expect(Math.round(emi(500000, 12, 60))).toBe(11122); // ₹5 lakh, 12%, 5 years
    expect(emi(120000, 0, 12)).toBe(10000);
    expect(emi(0, 12, 12)).toBe(0);
    const c = loanCost(500000, 12, 60);
    expect(Math.round(c.totalInterest)).toBe(Math.round(c.emi * 60 - 500000));
  });
});

describe("offers", () => {
  const m = (lender: string, channel: Match["channel"], tier: Match["tier"], fit: number, r: number): Match =>
    ({ ...base, product_id: `${lender}-${channel}`, lender, lender_key: lender, channel, tier, fit_score: fit,
      interest_rate_min: r, fit_reasons: {}, requirements: null, match_id: 1, matched_at: "" }) as Match;

  it("shows one row per lender with the best platform first", () => {
    const offers = groupByLender([
      m("icici", "bankbazaar", "conditional", 80, 10.5),
      m("icici", "direct", "eligible", 70, 10.9),
      m("hdfc", "paisabazaar", "eligible", 90, 11),
    ]);
    expect(offers.map((o) => [o.lender_key, o.best.channel, o.others.length])).toEqual([
      ["hdfc", "paisabazaar", 0],
      ["icici", "direct", 1],
    ]);
    expect(sortOffers(offers, "rate")[0].lender_key).toBe("icici");
  });

  it("merges requirements into one checklist without pipeline notes or duplicates", () => {
    const a = { ...m("a", "direct", "conditional", 1, 1), requirements: "2 years work experience; Salary account." };
    const b = { ...m("b", "direct", "conditional", 1, 1), requirements: "2 Years work experience; Criteria could not be verified automatically" };
    expect(checklist([a, b])).toEqual(["2 years work experience", "Salary account"]);
  });
});

describe("formatting", () => {
  it("speaks Indian amounts", () => {
    expect(rupeesShort(500000)).toBe("₹5 lakh");
    expect(rupeesShort(4000000)).toBe("₹40 lakh");
    expect(rupeesShort(15000000)).toBe("₹1.5 crore");
    expect(rate(9.5, 21.55)).toBe("9.5% to 21.55%");
    expect(rate(null, null)).toBe("Rate on request");
  });
});

import { fitParts } from "./fit";
import type { Match as M } from "../api/types";

describe("fit score breakdown", () => {
  it("adds up to the server's fit_score for every live match", async () => {
    const { default: fx } = await import("./__fixtures__/live_matches.json");
    const matches = fx.matches as unknown as M[];
    expect(matches.length).toBeGreaterThan(0);
    for (const m of matches) {
      const total = fitParts(m, fx.profile as Profile).reduce((s, p) => s + p.points, 0);
      // Within one display step: Postgres NUMERIC truncates 20.5/30.0 at 20 digits, so the
      // server can round 90.2499... down where float gets exactly 90.25. The UI always
      // shows the server's score as the total; the parts only explain it.
      expect(Math.abs(total - m.fit_score)).toBeLessThanOrEqual(0.1 + 1e-9);
    }
  });
});

import { displayParts } from "./fit";

describe("fit display", () => {
  it("shows parts that always add up to the server's total", async () => {
    const { default: fx } = await import("./__fixtures__/live_matches.json");
    for (const m of fx.matches as unknown as M[]) {
      const shown = displayParts(fitParts(m, fx.profile as Profile), m.fit_score);
      expect(Math.round(shown.reduce((a, b) => a + b, 0) * 10)).toBe(Math.round(m.fit_score * 10));
    }
  });
});

import { whyNot } from "./eligibility";

describe("why not eligible", () => {
  it("names every failing published rule in plain words", () => {
    const u = { monthly_income: 15000, credit_score: 690, age: 31, employment_status: "salaried" as const };
    expect(whyNot(base, u)).toEqual([
      "Needs ₹25,000 a month (you have ₹15,000)",
      "Needs a credit score of 700 (yours is 690)",
    ]);
    expect(whyNot({ ...base, employment_types: ["business"] }, profile)).toEqual(["Only for business owners"]);
    expect(whyNot(base, profile)).toEqual([]); // in reach: nothing to say
  });

  it("explains a failing compiled rule when the published criteria pass", () => {
    const p = { ...base, other_criteria_text: "max age 30", compiled_rules: [{ field: "age", op: "<=", value: 30, applies_to: "any" }] as CatalogProduct["compiled_rules"], compiled_requirements: [] };
    expect(whyNot(p, profile)).toEqual(["At most age 30"]);
  });

  it("agrees with decide() on every live product", () => {
    for (const p of catalog) expect(whyNot(p, profile).length > 0).toBe(decide(p, profile) === "not_eligible");
  });
});

import { tips } from "./tips";

describe("quick tips", () => {
  it("are specific to the person and always end with the enquiry advice", () => {
    const low = { ...profile, credit_score: 690 };
    const t = tips([], [], [base, { ...base, lender: "Other", lender_key: "o", min_credit_score: 740 }], low);
    expect(t[0]).toBe("Raising your credit score to 700 would bring Test Bank into reach.");
    expect(t.at(-1)).toMatch(/hard enquiry/);
  });
});
