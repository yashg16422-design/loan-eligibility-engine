-- Workflow B · Pre-write proof: runs AFTER Stage 1+2 and BEFORE Stage 3. Params: $1 run_id,
-- $2 prompt_version.
--
-- Re-decides EVERY user x product pair the naive way (real values, no classes) and compares
-- it with the class decisions expanded to users through the same floors Stage 3 will use
-- (the run's cuts -> match_classes -> match_pairs). It reads `matches` never and writes only
-- pipeline_runs.prewrite_ok, so a failure stops the run before any match is written.
-- A user who maps to no class (impossible by construction) counts as a mismatch for every
-- product they should match.
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
), user_class AS (  -- the same floors Stage 3 uses
    SELECT u.user_id, mc.class_id
    FROM usr u
    CROSS JOIN LATERAL (
        SELECT coalesce((SELECT max(c::int) FROM jsonb_array_elements_text((SELECT cuts->'income' FROM run)) c WHERE c::int <= u.monthly_income), -1) AS fi,
               coalesce((SELECT max(c::int) FROM jsonb_array_elements_text((SELECT cuts->'score' FROM run)) c WHERE c::int <= u.credit_score), -1) AS fs,
               coalesce((SELECT max(c::int) FROM jsonb_array_elements_text((SELECT cuts->'age' FROM run)) c WHERE c::int <= u.age), -1) AS fa
    ) f
    LEFT JOIN match_classes mc ON mc.run_id = $1::uuid AND mc.income_floor = f.fi AND mc.score_floor = f.fs
                              AND mc.age_floor = f.fa AND mc.employment_status = u.employment_status
), expanded AS (  -- what Stage 3 would write
    SELECT uc.user_id, mp.product_id, mp.tier
    FROM user_class uc
    JOIN match_pairs mp ON mp.run_id = $1::uuid AND mp.class_id = uc.class_id
                       AND mp.tier IN ('eligible', 'conditional')
    WHERE mp.product_id IN (SELECT product_id FROM prods)
), diff AS (
    (SELECT * FROM naive_kept EXCEPT SELECT * FROM expanded)
    UNION ALL
    (SELECT * FROM expanded EXCEPT SELECT * FROM naive_kept)
)
UPDATE pipeline_runs SET prewrite_ok = ((SELECT count(*) FROM diff) = 0)
WHERE run_id = $1::uuid
RETURNING run_id,
    (SELECT count(*) FROM naive) AS pairs_checked,
    (SELECT count(*) FROM naive_kept) AS naive_matches,
    (SELECT count(*) FROM expanded) AS class_matches,
    (SELECT count(*) FROM user_class WHERE class_id IS NULL) AS users_without_class,
    (SELECT count(*) FROM diff) AS mismatches,
    prewrite_ok;
