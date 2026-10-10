-- Workflow B · Stage 3: expand class decisions to users, score fit, diff against active
-- matches. ONE statement = one transaction, serialized by an advisory lock so an
-- upload-mode run and a product-mode run can never create duplicate active pairs.
-- Params: $1 run_id.
--
-- Fit score (0-100, transparent, every term traceable to a published lender rule):
--   tier            eligible 60 | conditional 35
--   income headroom up to 15  (user income / lender minimum: 1x -> 0, 3x or more -> 15)
--   credit margin   up to 10  (points above the lender minimum, capped at +100)
--   interest rate   up to 15  (lower starting rate is better; 0% -> 15, 30%+ -> 0)
--   unknown criterion -> half credit (neither rewarded nor punished)
WITH lck AS (
    SELECT pg_advisory_xact_lock(424242) AS locked
), run AS (
    SELECT r.* FROM pipeline_runs r, lck WHERE r.run_id = $1::uuid
), usr AS (
    SELECT u.* FROM users u
    WHERE (SELECT mode FROM run) = 'products' OR u.upload_job_id = (SELECT job_id FROM run)
), user_class AS (  -- the same floors Stage 1 used (cuts stored on the run)
    SELECT u.user_id, u.monthly_income, u.credit_score, mc.class_id
    FROM usr u
    CROSS JOIN LATERAL (
        SELECT coalesce((SELECT max(c::int) FROM jsonb_array_elements_text((SELECT cuts->'income' FROM run)) c WHERE c::int <= u.monthly_income), -1) AS fi,
               coalesce((SELECT max(c::int) FROM jsonb_array_elements_text((SELECT cuts->'score' FROM run)) c WHERE c::int <= u.credit_score), -1) AS fs,
               coalesce((SELECT max(c::int) FROM jsonb_array_elements_text((SELECT cuts->'age' FROM run)) c WHERE c::int <= u.age), -1) AS fa
    ) f
    JOIN match_classes mc ON mc.run_id = $1::uuid AND mc.income_floor = f.fi AND mc.score_floor = f.fs
                         AND mc.age_floor = f.fa AND mc.employment_status = u.employment_status
), scored AS (
    SELECT uc.user_id, mp.product_id, mp.tier, mp.requirements,
        CASE mp.stage WHEN 'llm_rules' THEN 'llm' ELSE mp.stage END AS stage_decided,
        round(
              CASE mp.tier WHEN 'eligible' THEN 60 ELSE 35 END
            + 15 * CASE WHEN p.min_monthly_income IS NULL THEN 0.5
                        ELSE least(greatest(uc.monthly_income::numeric / p.min_monthly_income - 1, 0), 2) / 2 END
            + 10 * CASE WHEN p.min_credit_score IS NULL THEN 0.5
                        ELSE least(greatest(uc.credit_score - p.min_credit_score, 0), 100) / 100.0 END
            + 15 * CASE WHEN p.interest_rate_min IS NULL THEN 0.5
                        ELSE greatest(30 - least(p.interest_rate_min, 30), 0) / 30.0 END
        , 1) AS fit_score,
        jsonb_strip_nulls(jsonb_build_object(
            'income_multiple', round(uc.monthly_income::numeric / nullif(p.min_monthly_income, 0), 1),
            'credit_margin',   uc.credit_score - p.min_credit_score,
            'rate_from',       p.interest_rate_min,
            'has_conditions',  mp.requirements IS NOT NULL)) AS fit_reasons
    FROM user_class uc
    JOIN match_pairs mp ON mp.run_id = $1::uuid AND mp.class_id = uc.class_id
                       AND mp.tier IN ('eligible', 'conditional')
    JOIN loan_products p ON p.product_id = mp.product_id
), current_active AS (  -- active matches inside this run's scope
    -- A user created or changed after this run started (i.e. after Stage 1 classified everyone)
    -- is left alone: their matches are never wrongly superseded; the next run decides them.
    -- Written as a PK lookup on users, not "IN (user_class)": the planner estimates that CTE
    -- at 1 row and a nested loop over 240k matches took 8+ minutes on RDS (found live).
    SELECT m.match_id, m.user_id, m.product_id
    FROM matches m
    WHERE m.status = 'active'
      AND NOT EXISTS (SELECT 1 FROM users late
                      WHERE late.user_id = m.user_id AND late.updated_at > (SELECT started_at FROM run))
      AND (((SELECT mode FROM run) = 'upload' AND m.user_id IN (SELECT user_id FROM usr))
        OR ((SELECT mode FROM run) = 'products' AND m.product_id = ANY (coalesce((SELECT scope_product_ids FROM run), ARRAY[]::uuid[]))))
), ins AS (
    INSERT INTO matches (user_id, product_id, job_id, match_run_id, tier, requirements,
                         stage_decided, fit_score, fit_reasons)
    SELECT s.user_id, s.product_id, (SELECT job_id FROM run), $1::uuid, s.tier, s.requirements,
           s.stage_decided, s.fit_score, s.fit_reasons
    FROM scored s
    WHERE NOT EXISTS (SELECT 1 FROM current_active c WHERE c.user_id = s.user_id AND c.product_id = s.product_id)
    ON CONFLICT (user_id, product_id) WHERE status = 'active' DO NOTHING
    RETURNING 1
), upd AS (  -- tier/requirements changed on a pair the user already had: update in place, no new email
    UPDATE matches m SET tier = s.tier, requirements = s.requirements, fit_score = s.fit_score,
                         fit_reasons = s.fit_reasons, stage_decided = s.stage_decided
    FROM scored s
    WHERE m.status = 'active' AND m.user_id = s.user_id AND m.product_id = s.product_id
      AND (m.tier, m.requirements) IS DISTINCT FROM (s.tier, s.requirements)
    RETURNING 1
), sup AS (  -- no longer eligible: keep the history, mark superseded (no email)
    UPDATE matches m SET status = 'superseded', superseded_at = now()
    FROM current_active c
    WHERE m.match_id = c.match_id
      AND NOT EXISTS (SELECT 1 FROM scored s WHERE s.user_id = c.user_id AND s.product_id = c.product_id)
    RETURNING 1
), job AS (
    UPDATE upload_jobs SET match_status = 'DONE', matched_at = now()
    WHERE job_id = (SELECT job_id FROM run)
    RETURNING 1
)
UPDATE pipeline_runs SET
    matches_new        = (SELECT count(*) FROM ins),
    matches_superseded = (SELECT count(*) FROM sup),
    matches_unchanged  = (SELECT count(*) FROM scored) - (SELECT count(*) FROM ins) - (SELECT count(*) FROM upd),
    finished_at        = now(),
    error = CASE WHEN (SELECT count(*) FROM job) >= 0 THEN error END
WHERE run_id = $1::uuid
RETURNING run_id, mode, job_id, matches_new, matches_superseded, matches_unchanged,
          (SELECT count(*) FROM upd) AS matches_updated, (SELECT count(*) FROM scored) AS matched_pairs;
