-- Workflow B · Stage 1 + 2: exact equivalence classes, then a decision per class x product.
-- Params: $1 run_id (uuid text), $2 prompt_version of the compiled residual rules.
--
-- Idea: every threshold any in-scope product uses (its hard criteria AND the numbers in
-- its LLM-compiled residual rules) is a CUT POINT. Two users whose income, credit score
-- and age fall between the same consecutive cut points, with the same employment type,
-- get identical answers to every rule, so they form one class. We decide once per
-- class x product and expand to users later. Exact, not banded: no false positives.
--
-- Why floors are exact: for any cut c, value >= c  <=>  floor(value) >= c, where
-- floor(value) = the largest cut <= value (or -1 below all cuts). So every comparison
-- against a cut gives the same answer on the floor as on the real value.
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
), rule_values AS (  -- numbers inside the compiled residual rules are cut points too
    SELECT x->>'field' AS field, x->>'op' AS op, (x->>'value')::numeric AS v
    FROM prods, jsonb_array_elements(coalesce(residual_rules, '[]'::jsonb)) AS x
), cuts AS (
    -- ">= v" splits at ceil(v); "<= v" splits at floor(v) + 1 (integer fields)
    SELECT 'income' AS dim, min_monthly_income AS c FROM prods WHERE min_monthly_income IS NOT NULL
    UNION SELECT 'income', ceil(v)::int FROM rule_values WHERE field = 'monthly_income' AND op = '>='
    UNION SELECT 'income', floor(v)::int + 1 FROM rule_values WHERE field = 'monthly_income' AND op = '<='
    UNION SELECT 'score', min_credit_score FROM prods WHERE min_credit_score IS NOT NULL
    UNION SELECT 'score', max_credit_score + 1 FROM prods WHERE max_credit_score IS NOT NULL
    UNION SELECT 'score', ceil(v)::int FROM rule_values WHERE field = 'credit_score' AND op = '>='
    UNION SELECT 'score', floor(v)::int + 1 FROM rule_values WHERE field = 'credit_score' AND op = '<='
    UNION SELECT 'age', min_age FROM prods WHERE min_age IS NOT NULL
    UNION SELECT 'age', max_age + 1 FROM prods WHERE max_age IS NOT NULL
    UNION SELECT 'age', ceil(v)::int FROM rule_values WHERE field = 'age' AND op = '>='
    UNION SELECT 'age', floor(v)::int + 1 FROM rule_values WHERE field = 'age' AND op = '<='
), user_floors AS (
    SELECT u.user_id, u.employment_status,
        coalesce((SELECT max(c) FROM cuts WHERE dim = 'income' AND c <= u.monthly_income), -1) AS income_floor,
        coalesce((SELECT max(c) FROM cuts WHERE dim = 'score' AND c <= u.credit_score), -1) AS score_floor,
        coalesce((SELECT max(c) FROM cuts WHERE dim = 'age' AND c <= u.age), -1) AS age_floor
    FROM usr u
), classes AS (
    SELECT row_number() OVER (ORDER BY employment_status, income_floor, score_floor, age_floor)::int AS class_id,
           income_floor, score_floor, age_floor, employment_status, count(*)::int AS users
    FROM user_floors
    GROUP BY employment_status, income_floor, score_floor, age_floor
), pairs AS (  -- Stage 1: hard criteria (NULL = "lender states no limit" = passes)
    SELECT c.class_id, c.users, c.income_floor, c.score_floor, c.age_floor, c.employment_status,
           p.product_id, p.other_criteria_text, p.verification, p.residual_rules, p.residual_requirements
    FROM classes c
    JOIN prods p ON
         (p.min_monthly_income IS NULL OR c.income_floor >= p.min_monthly_income)
     AND (p.min_credit_score   IS NULL OR c.score_floor  >= p.min_credit_score)
     AND (p.max_credit_score   IS NULL OR c.score_floor  <  p.max_credit_score + 1)
     AND (p.min_age            IS NULL OR c.age_floor    >= p.min_age)
     AND (p.max_age            IS NULL OR c.age_floor    <  p.max_age + 1)
     AND (p.employment_types   IS NULL OR c.employment_status = ANY (p.employment_types))
), judged AS (  -- Stage 2: the compiled residual rules, evaluated on the class floors
    SELECT pr.*,
        (SELECT coalesce(bool_and(CASE
                    WHEN x->>'field' = 'monthly_income' AND x->>'op' = '>=' THEN pr.income_floor >= ceil((x->>'value')::numeric)
                    WHEN x->>'field' = 'monthly_income' AND x->>'op' = '<=' THEN pr.income_floor <  floor((x->>'value')::numeric) + 1
                    WHEN x->>'field' = 'credit_score'   AND x->>'op' = '>=' THEN pr.score_floor  >= ceil((x->>'value')::numeric)
                    WHEN x->>'field' = 'credit_score'   AND x->>'op' = '<=' THEN pr.score_floor  <  floor((x->>'value')::numeric) + 1
                    WHEN x->>'field' = 'age'            AND x->>'op' = '>=' THEN pr.age_floor    >= ceil((x->>'value')::numeric)
                    WHEN x->>'field' = 'age'            AND x->>'op' = '<=' THEN pr.age_floor    <  floor((x->>'value')::numeric) + 1
                    ELSE true END), true)
         FROM jsonb_array_elements(coalesce(pr.residual_rules, '[]'::jsonb)) AS x
         WHERE x->>'applies_to' IN ('any', pr.employment_status)) AS rules_pass
    FROM pairs pr
), decided AS (
    SELECT class_id, users, product_id,
        CASE
            WHEN other_criteria_text IS NULL                  THEN 'eligible'     -- nothing left to check
            WHEN residual_rules IS NULL                       THEN 'conditional'  -- not compiled / unverified: never a rejection
            WHEN NOT rules_pass                               THEN 'not_eligible'
            WHEN jsonb_array_length(residual_requirements) > 0 THEN 'conditional'
            ELSE 'eligible' END AS tier,
        CASE
            WHEN other_criteria_text IS NULL THEN 'sql'
            WHEN residual_rules IS NULL      THEN 'rules'
            ELSE 'llm_rules' END AS stage,
        CASE
            WHEN other_criteria_text IS NULL THEN NULL
            WHEN residual_rules IS NULL      THEN other_criteria_text
            ELSE nullif(array_to_string(ARRAY(SELECT jsonb_array_elements_text(residual_requirements)), '; '), '')
        END AS requirements
    FROM judged
), ins_classes AS (
    INSERT INTO match_classes (run_id, class_id, income_floor, score_floor, age_floor, employment_status, users)
    SELECT $1::uuid, class_id, income_floor, score_floor, age_floor, employment_status, users FROM classes
    RETURNING 1
), ins_pairs AS (
    INSERT INTO match_pairs (run_id, class_id, product_id, tier, stage, requirements)
    SELECT $1::uuid, class_id, product_id, tier, stage, requirements FROM decided
    RETURNING 1
)
UPDATE pipeline_runs SET
    users_in            = (SELECT count(*) FROM usr),
    products_in         = (SELECT count(*) FROM prods),
    naive_pairs         = (SELECT count(*) FROM usr) * (SELECT count(*) FROM prods),
    classes             = (SELECT count(*) FROM classes),
    class_product_pairs = (SELECT count(*) FROM classes) * (SELECT count(*) FROM prods),
    pairs_after_sql     = (SELECT coalesce(sum(users), 0) FROM pairs),
    rule_decided        = (SELECT count(*) FROM decided WHERE stage IN ('sql', 'rules')),
    llm_candidates      = (SELECT count(*) FROM decided WHERE stage = 'llm_rules'),
    not_eligible_pairs  = (SELECT count(*) FROM decided WHERE tier = 'not_eligible'),
    residual_texts      = (SELECT count(DISTINCT other_criteria_text) FROM prods),
    -- coalesce: a dimension with no thresholds (e.g. a product-mode run whose product has no
    -- age rule) must be stored as [] - jsonb_agg of zero rows is NULL -> JSON null, and Stage 3
    -- cannot iterate a scalar (found by the product-mode integration test).
    cuts = jsonb_build_object(
        'income', coalesce((SELECT jsonb_agg(c ORDER BY c) FROM cuts WHERE dim = 'income'), '[]'::jsonb),
        'score',  coalesce((SELECT jsonb_agg(c ORDER BY c) FROM cuts WHERE dim = 'score'), '[]'::jsonb),
        'age',    coalesce((SELECT jsonb_agg(c ORDER BY c) FROM cuts WHERE dim = 'age'), '[]'::jsonb)),
    -- Reference the data-modifying CTEs so they are part of this statement.
    error = CASE WHEN (SELECT count(*) FROM ins_classes) >= 0 AND (SELECT count(*) FROM ins_pairs) >= 0
                 THEN NULL END
WHERE run_id = $1::uuid
RETURNING run_id, mode, users_in, products_in, naive_pairs, classes, class_product_pairs,
          pairs_after_sql, rule_decided, llm_candidates, not_eligible_pairs, residual_texts, cuts;
