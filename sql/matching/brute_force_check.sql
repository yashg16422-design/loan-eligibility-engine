-- Correctness proof for the Treasure Hunt (PLAN.md §11.9).
-- Params: $1 run_id, $2 prompt_version.
--
-- Re-decides EVERY user x product pair the naive way: real values, no classes, no floors,
-- one row per pair. Then compares with what the optimized pipeline produced (class
-- decisions expanded to users). The optimization is correct iff the two sets are identical.
WITH run AS (
    SELECT * FROM pipeline_runs WHERE run_id = $1::uuid
), prods AS (
    SELECT p.*, r.rules AS residual_rules, r.requirements AS residual_requirements
    FROM loan_products p
    LEFT JOIN criteria_rules r
           ON r.prompt_version = $2
          AND r.criteria_text_hash = encode(sha256(convert_to(p.other_criteria_text, 'UTF8')), 'hex')
    WHERE p.is_active
      AND ((SELECT mode FROM run) = 'upload' OR p.product_id = ANY (coalesce((SELECT scope_product_ids FROM run), ARRAY[]::uuid[])))
), usr AS (
    SELECT u.* FROM users u
    WHERE (SELECT mode FROM run) = 'products' OR u.upload_job_id = (SELECT job_id FROM run)
), naive AS (  -- every user x every product, decided on the user's REAL values
    SELECT u.user_id, p.product_id,
        CASE
            WHEN NOT ((p.min_monthly_income IS NULL OR u.monthly_income >= p.min_monthly_income)
                  AND (p.min_credit_score   IS NULL OR u.credit_score  >= p.min_credit_score)
                  AND (p.max_credit_score   IS NULL OR u.credit_score  <= p.max_credit_score)
                  AND (p.min_age            IS NULL OR u.age           >= p.min_age)
                  AND (p.max_age            IS NULL OR u.age           <= p.max_age)
                  AND (p.employment_types   IS NULL OR u.employment_status = ANY (p.employment_types)))
                THEN 'fails_hard_criteria'
            WHEN p.other_criteria_text IS NULL THEN 'eligible'
            WHEN p.residual_rules IS NULL THEN 'conditional'
            WHEN NOT (SELECT coalesce(bool_and(CASE
                        WHEN x->>'field' = 'monthly_income' AND x->>'op' = '>=' THEN u.monthly_income >= (x->>'value')::numeric
                        WHEN x->>'field' = 'monthly_income' AND x->>'op' = '<=' THEN u.monthly_income <= (x->>'value')::numeric
                        WHEN x->>'field' = 'credit_score'   AND x->>'op' = '>=' THEN u.credit_score  >= (x->>'value')::numeric
                        WHEN x->>'field' = 'credit_score'   AND x->>'op' = '<=' THEN u.credit_score  <= (x->>'value')::numeric
                        WHEN x->>'field' = 'age'            AND x->>'op' = '>=' THEN u.age           >= (x->>'value')::numeric
                        WHEN x->>'field' = 'age'            AND x->>'op' = '<=' THEN u.age           <= (x->>'value')::numeric
                        ELSE true END), true)
                      FROM jsonb_array_elements(coalesce(p.residual_rules, '[]'::jsonb)) AS x
                      WHERE x->>'applies_to' IN ('any', u.employment_status))
                THEN 'not_eligible'
            WHEN jsonb_array_length(p.residual_requirements) > 0 THEN 'conditional'
            ELSE 'eligible' END AS tier
    FROM usr u CROSS JOIN prods p
), naive_kept AS (
    SELECT user_id, product_id, tier FROM naive WHERE tier IN ('eligible', 'conditional')
), optimized AS (  -- what the pipeline stored for this run
    SELECT m.user_id, m.product_id, m.tier
    FROM matches m
    WHERE m.status = 'active' AND m.user_id IN (SELECT user_id FROM usr)
      AND m.product_id IN (SELECT product_id FROM prods)
), diff AS (
    (SELECT * FROM naive_kept EXCEPT SELECT * FROM optimized)
    UNION ALL
    (SELECT * FROM optimized EXCEPT SELECT * FROM naive_kept)
)
UPDATE pipeline_runs SET correctness_ok = ((SELECT count(*) FROM diff) = 0)
WHERE run_id = $1::uuid
RETURNING run_id,
    (SELECT count(*) FROM naive) AS naive_pairs_evaluated,
    (SELECT count(*) FROM naive_kept) AS naive_matches,
    (SELECT count(*) FROM optimized) AS optimized_matches,
    (SELECT count(*) FROM diff) AS mismatches,
    correctness_ok;
