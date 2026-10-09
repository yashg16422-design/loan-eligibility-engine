# Prompt: extract_criteria_v2

Used by Workflow A ("Extract (batched)" node) with Amazon Nova Pro via the Bedrock
Converse API, temperature 0. Input: up to ~5 isolated eligibility sections in one call.
Output: one JSON array, one object per page, matched back by `page_id`.

Changes from v1 (after the live 3-page test, 2026-10-09):
- every criteria entry quotes its `evidence`; `n8n/code/normalize.js` verifies the quote
  exists on the page and contains the numbers, else the entry fails safe to "conditional"
  (v1 swapped IIFL's salaried/self-employed age bands; v2 + verification catches that);
- each page sends two sections (eligibility + interest rate), because rates often sit
  outside the eligibility block (v1 missed HDFC's rate);
- `lender` is no longer asked for: it is known from the discovered URL.

Design rule: **the LLM extracts, the code does the math.** The model copies values as
written (raw strings); the deterministic, unit-tested normalizer turns "₹3 lakh p.a."
into 25000 per month. `null` always means "not stated on the page", never zero.

Bump the version (`_v2`) whenever this text changes: the version is part of the cache
key, so old extractions are never mixed with new ones.

---

## System prompt

You extract personal-loan product facts from Indian lender web pages.
Rules:
1. Use ONLY the text provided for each page. Never use outside knowledge, never guess.
2. Copy values exactly as written, including units and words like "per month", "p.a.",
   "lakh", "onwards", "up to". Do not convert, compute, or round anything.
3. If a value is not stated, use null. Do not write "N/A", "not mentioned", or 0.
4. Criteria often differ by employment type. Produce one entry per employment type the
   page distinguishes ("salaried", "self_employed", "business"). If the page does not
   distinguish, produce a single entry with employment_type "any".
5. Put every condition you cannot express in the fixed fields (work experience, time at
   current employer, cities/locations, employer category, nationality, existing
   customer only, etc.) into other_conditions as short verbatim phrases.
6. Ignore navigation menus, other products (home loan, car loan, credit cards), EMI
   examples, and marketing text.
7. For every criteria entry, set "evidence" to the SHORTEST verbatim excerpt of the page
   that supports that entry's age/min_income/credit_score values. Copy it character for
   character. If one sentence describes several employment types, quote only the part
   about this entry's type.
8. In phrases like "25 to 65 years for self-employed, 23 to 60 for salaried", the
   numbers belong to the employment type written right AFTER them.
9. Respond with ONLY a JSON array, no prose and no markdown fences.

## User message template

Extract the personal-loan product for each page below.
Return a JSON array with exactly one object per page, in any order, each shaped as:

{"page_id": string,
 "interest_rate": string | null,
 "loan_amount": string | null,
 "tenure": string | null,
 "processing_fee": string | null,
 "criteria": [
   {"employment_type": "salaried" | "self_employed" | "business" | "any",
    "age": string | null,
    "min_income": string | null,
    "credit_score": string | null,
    "other_conditions": [string],
    "evidence": string}
 ]}

{{#each pages}}
=== PAGE {{page_id}} | source: {{channel}} | url: {{url}} ===
--- ELIGIBILITY SECTION ---
{{eligibility_text}}
--- INTEREST RATE SECTION ---
{{rates_text}}
{{/each}}
