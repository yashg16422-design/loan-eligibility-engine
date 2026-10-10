-- Workflow B · Products whose criteria were compiled for the FIRST time in this run.
-- Params: $1 run_id, $2 prompt_version.
--
-- When the LLM fails to compile a product's criteria, that product counts as "may qualify" for
-- every user (never wrongly eligible) and the text is retried on the next run. Once a later run
-- compiles it, the users matched BEFORE still hold the provisional decision: B re-matches all
-- users against exactly these products (product mode). The follow-up run finds every text
-- cached (rules_compiled = 0), so this never loops.
WITH run AS (
    SELECT * FROM pipeline_runs WHERE run_id = $1::uuid
)
SELECT $1::text AS run_id,
       coalesce(json_agg(DISTINCT p.product_id), '[]'::json) AS product_ids
FROM loan_products p
JOIN criteria_rules r
  ON r.prompt_version = $2
 AND r.criteria_text_hash = encode(sha256(convert_to(p.other_criteria_text, 'UTF8')), 'hex')
WHERE p.is_active
  AND coalesce((SELECT rules_compiled FROM run), 0) > 0
  AND r.created_at >= (SELECT started_at FROM run)
  -- a product-mode run already re-decided every user for its own products
  AND NOT ((SELECT mode FROM run) = 'products'
           AND p.product_id = ANY (coalesce((SELECT scope_product_ids FROM run), ARRAY[]::uuid[])));
