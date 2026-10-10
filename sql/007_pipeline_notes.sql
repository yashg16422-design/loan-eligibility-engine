-- 007_pipeline_notes.sql: data fix for a compile bug (PLAN.md decision log, 2026-10-10).
--
-- Our normalizer appends its own note when a lender publishes no criteria ("Eligibility criteria
-- not published: confirm with the lender") or a page could not be verified. compile.js dropped
-- that note, so such a text compiled to NO rules and NO requirements, which Stage 1 reads as
-- "eligible" (7 live products, e.g. Federal Bank on Paisabazaar: 10,000 of 10,000 "eligible").
-- compile.js now keeps the note as a requirement; this applies the same rule to the cached
-- compile results, deterministically (no LLM). Idempotent: a note already present is skipped.
WITH notes AS (
    SELECT DISTINCT encode(sha256(convert_to(other_criteria_text, 'UTF8')), 'hex') AS text_hash,
           (SELECT jsonb_agg(btrim(part) ORDER BY ord)
              FROM regexp_split_to_table(other_criteria_text, ';') WITH ORDINALITY AS t(part, ord)
             WHERE part ~* 'could not be verified automatically|criteria not published') AS notes
    FROM loan_products
    WHERE other_criteria_text ~* 'could not be verified automatically|criteria not published'
)
UPDATE criteria_rules r
SET requirements = coalesce(r.requirements, '[]'::jsonb) || n.notes
FROM notes n
WHERE r.criteria_text_hash = n.text_hash
  AND NOT coalesce(r.requirements, '[]'::jsonb) @> n.notes;
