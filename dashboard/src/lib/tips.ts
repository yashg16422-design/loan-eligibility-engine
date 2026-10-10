// Quick tips: short, specific, computed from this person's own results (never generic advice).
import type { CatalogProduct, Match, Profile } from "../api/types";
import { nextUnlock } from "./eligibility";
import { checklist, type LenderOffer } from "./offers";

const inr = (n: number) => `₹${new Intl.NumberFormat("en-IN").format(n)}`;

export function tips(offers: LenderOffer[], matches: Match[], catalog: CatalogProduct[], u: Profile): string[] {
  const out: string[] = [];
  const score = nextUnlock(catalog, u, ["credit_score"]);
  if (score) {
    out.push(`Raising your credit score to ${score.to} would bring ${score.lenders.slice(0, 3).join(", ")}${score.lenders.length > 3 ? ` and ${score.lenders.length - 3} more` : ""} into reach.`);
  }
  const income = nextUnlock(catalog, u, ["monthly_income"]);
  if (income) {
    out.push(`At ${inr(income.to)} a month, ${income.lenders.slice(0, 3).join(", ")}${income.lenders.length > 3 ? ` and ${income.lenders.length - 3} more` : ""} would open up. A co-applicant's income can count towards it.`);
  }
  const multi = offers.filter((o) => o.others.length > 0).length;
  if (multi > 0) {
    out.push(`${multi} of your lenders are on more than one platform. Each row shows the platform that fits you best; expand it to compare the others.`);
  }
  const needs = checklist(matches.filter((m) => m.tier === "conditional"));
  if (needs.length > 0) {
    out.push(`Offers marked "may qualify" mostly ask for things four numbers can't show, such as: ${needs.slice(0, 2).join("; ").toLowerCase()}. Have those ready before you apply.`);
  }
  out.push("Apply to your top pick first rather than to many lenders at once: each application can be a hard enquiry on your credit report.");
  return out;
}
