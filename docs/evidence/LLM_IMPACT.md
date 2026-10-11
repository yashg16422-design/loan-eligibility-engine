# Evidence: what the LLM step actually changes

Captured 2026-10-11 (read-only queries on the live RDS through `scripts/psql.sh`), for the
reference run `ccfff5cb-5ddc-4c13-940a-bd7354c9c4c2` (the 10,000-user `users.csv`, 58 active
products, 164 classes).

The LLM (Nova Pro) runs once per distinct criteria text and turns it into checkable rules plus
requirements that our CSV cannot check (README §8, Stage 0). Its output decides most of the
class × product decisions:

```
SELECT stage, tier, count(*) AS class_product_pairs, sum(mc.users) AS user_pairs
FROM match_pairs mp JOIN match_classes mc USING (run_id, class_id)
WHERE mp.run_id = 'ccfff5cb-...' GROUP BY 1, 2;

   stage   |     tier     | class_product_pairs | user_pairs
-----------+--------------+---------------------+------------
 llm_rules | conditional  |                3240 |     214910
 llm_rules | not_eligible |                  13 |        377
 sql       | eligible     |                 569 |      34713
```

- **3,253 of the 3,822 class × product pairs that pass the hard criteria (85%) are decided by
  the compiled rules.** The other 569 are products with no free-text criteria, which plain SQL
  decides. (The run's `class_product_pairs` counter, 9,512, also counts pairs that fail the hard
  criteria; `match_pairs` stores only the ones that pass.)
- **3,240 decisions became "may qualify" (214,910 user pairs).** Each one carries the requirement
  the lender states and the CSV cannot check, shown to the user. For example:
  - "Salaried employees should have … worked with the current employer for at least 1 year"
    (Bank of Baroda);
  - "Minimum 2-years ITR returns need to be submitted" (Bank of Maharashtra).
- **13 decisions became not eligible (377 users).**

  Without the LLM step, every one of these products would show "may qualify" with the lender's
  whole raw paragraph as the requirement. The 377 users above would see an offer they cannot get,
  and nobody would see which single condition matters.

## One rejection, traced to its source

The 13 rejected classes are all for ICICI Bank on BankBazaar: self-employed users aged 25–27.
The product's structured minimum age did not stop them, but the page's free text did:

> Age: 25 years (for doctors) and 28 years (for self-employed individuals) to 65 years

Compiled rules (stored in `criteria_rules`, each with the quote it came from):

```json
[{"field": "age", "op": ">=", "value": 25, "applies_to": "self_employed", "quote": "Age: 25 years (for doctors) and 28 years (for self-employed individuals) to 65 years"},
 {"field": "age", "op": ">=", "value": 28, "applies_to": "self_employed", "quote": "Age: 25 years (for doctors) and 28 years (for self-employed individuals) to 65 years"}]
```

The rule `age >= 28` for self-employed users rejected 377 users who would otherwise have seen
an offer they cannot get. The business-turnover and profit conditions on the same page became
requirements: our five CSV fields cannot check them.

## Coverage of the compiled texts

```
 texts | with_checkable_rules | with_requirements | rules_total
-------+----------------------+-------------------+-------------
    71 |                    6 |                70 |          11
```

Most lender criteria are conditions the CSV cannot check (employer type, work experience, ITR,
residency). The pipeline keeps them as stated requirements instead of guessing.

## Not measured: extraction accuracy

Precision and recall of the compiled rules against a hand-labelled gold set have not been
measured. That needs labels verified by a person; an LLM grading an LLM would prove nothing.
It is listed as a next step in README §11.

Two guards are in place instead:
- **Quote check.** Every rule must quote text that exists on the page and contains its number;
  otherwise it becomes a requirement.
- **Every-pair proofs.** The proofs check that the pipeline applies the compiled rules exactly
  (README §8).
