// What-if simulator: decides a product for a profile with EXACTLY the rules Workflow B uses
// (sql/matching/stage1_classes.sql, the `pairs`, `judged` and `decided` CTEs). The server
// stays the source of truth for real matches; this lets a borrower explore "what if my score
// were 790" instantly, without a round trip, and stays honest because the logic is the same.
import type { CatalogProduct, CompiledRule, Profile, SimTier } from "../api/types";

/** Stage 1: published hard criteria. NULL means "the lender states no limit", which passes. */
export function passesHardCriteria(p: CatalogProduct, u: Profile): boolean {
  return (
    (p.min_monthly_income == null || u.monthly_income >= p.min_monthly_income) &&
    (p.min_credit_score == null || u.credit_score >= p.min_credit_score) &&
    (p.max_credit_score == null || u.credit_score <= p.max_credit_score) &&
    (p.min_age == null || u.age >= p.min_age) &&
    (p.max_age == null || u.age <= p.max_age) &&
    (p.employment_types == null || p.employment_types.includes(u.employment_status))
  );
}

function fieldValue(rule: CompiledRule, u: Profile): number {
  if (rule.field === "monthly_income") return u.monthly_income;
  if (rule.field === "credit_score") return u.credit_score;
  return u.age;
}

/** Stage 2: the compiled free-text rules that apply to this employment type. */
export function passesCompiledRules(rules: CompiledRule[], u: Profile): boolean {
  return rules
    .filter((r) => r.applies_to === "any" || r.applies_to === u.employment_status)
    .every((r) => {
      const v = fieldValue(r, u);
      // Integer fields: ">= 25000.5" means >= 25001, "<= 60.9" means <= 60 (as in the SQL).
      return r.op === ">=" ? v >= Math.ceil(r.value) : v <= Math.floor(r.value);
    });
}

/** The tier Workflow B would assign: the `decided` CTE, case for case. */
export function decide(p: CatalogProduct, u: Profile): SimTier {
  if (!passesHardCriteria(p, u)) return "not_eligible";
  if (p.other_criteria_text == null) return "eligible"; // nothing left to check
  if (p.compiled_rules == null) return "conditional"; // never compiled: never a rejection
  if (!passesCompiledRules(p.compiled_rules, u)) return "not_eligible";
  if ((p.compiled_requirements ?? []).length > 0) return "conditional";
  return "eligible";
}

export interface Unlock {
  field: "credit_score" | "monthly_income";
  to: number;
  lenders: string[];
}

/**
 * The smallest single change (credit score or income) that brings at least one more lender
 * into reach. Searches the real thresholds (the cut points), not a fixed step, so the advice
 * names an exact number: "with a score of 750, HDFC and ICICI open up".
 */
export function nextUnlock(
  catalog: CatalogProduct[],
  u: Profile,
  fields: Unlock["field"][] = ["credit_score", "monthly_income"],
): Unlock | null {
  const reachable = new Set(catalog.filter((p) => decide(p, u) !== "not_eligible").map((p) => p.lender_key));
  const best: Unlock[] = [];
  for (const field of fields) {
    const current = u[field];
    const cuts = new Set<number>();
    for (const p of catalog) {
      const hard = field === "credit_score" ? p.min_credit_score : p.min_monthly_income;
      if (hard != null && hard > current) cuts.add(hard);
      for (const r of p.compiled_rules ?? []) {
        if (r.field === field && r.op === ">=" && Math.ceil(r.value) > current) cuts.add(Math.ceil(r.value));
      }
    }
    for (const to of [...cuts].sort((a, b) => a - b)) {
      const trial = { ...u, [field]: to };
      const opened = new Set(
        catalog
          .filter((p) => !reachable.has(p.lender_key) && decide(p, trial) !== "not_eligible")
          .map((p) => p.lender),
      );
      if (opened.size) {
        best.push({ field, to, lenders: [...opened].sort() });
        break;
      }
    }
  }
  // Prefer the change that is smallest relative to where the person is today.
  best.sort((a, b) => (a.to - u[a.field]) / u[a.field] - (b.to - u[b.field]) / u[b.field]);
  return best[0] ?? null;
}

const inr = (n: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(n))}`;
const EMPLOYMENT_NAME: Record<string, string> = {
  salaried: "salaried",
  self_employed: "self-employed",
  business: "business owners",
};

/**
 * Why a product is out of reach, in plain words, one line per failing rule (same checks as
 * `decide`). Empty when the product is in reach.
 */
export function whyNot(p: CatalogProduct, u: Profile): string[] {
  const out: string[] = [];
  if (p.employment_types != null && !p.employment_types.includes(u.employment_status)) {
    out.push(`Only for ${p.employment_types.map((e) => EMPLOYMENT_NAME[e] ?? e).join(" or ")}`);
  }
  if (p.min_monthly_income != null && u.monthly_income < p.min_monthly_income) {
    out.push(`Needs ${inr(p.min_monthly_income)} a month (you have ${inr(u.monthly_income)})`);
  }
  if (p.min_credit_score != null && u.credit_score < p.min_credit_score) {
    out.push(`Needs a credit score of ${p.min_credit_score} (yours is ${u.credit_score})`);
  }
  if (p.max_credit_score != null && u.credit_score > p.max_credit_score) {
    out.push(`For credit scores up to ${p.max_credit_score}`);
  }
  if (p.min_age != null && u.age < p.min_age) out.push(`Minimum age ${p.min_age}`);
  if (p.max_age != null && u.age > p.max_age) out.push(`Maximum age ${p.max_age}`);
  if (!out.length && p.other_criteria_text != null && p.compiled_rules != null) {
    for (const r of p.compiled_rules) {
      if (r.applies_to !== "any" && r.applies_to !== u.employment_status) continue;
      if (passesCompiledRules([r], u)) continue;
      const v = r.op === ">=" ? Math.ceil(r.value) : Math.floor(r.value);
      const what =
        r.field === "monthly_income" ? `${inr(v)} a month` : r.field === "credit_score" ? `a credit score of ${v}` : `age ${v}`;
      out.push(`${r.op === ">=" ? "Needs at least" : "At most"} ${what}`);
    }
  }
  return out;
}
