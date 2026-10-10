-- Workflow B · Claim a job and start a run. Params: $1 mode ('upload'|'products'),
-- $2 job_id (uuid text or ''), $3 product ids (JSON array text or '').
-- Atomic: only ONE run per job, even with a duplicate webhook + the sweeper racing.
-- 0 rows returned = nothing to do (already matched / running / unknown / out of retries).
-- The retry rule matches sweeper.sql: a FAILED job is reclaimable fewer than 3 times.
WITH req AS (
  SELECT $1::text AS mode, nullif($2, '')::uuid AS job_id, nullif($3, '')::jsonb AS product_ids
), failures AS (
  SELECT count(*) AS n FROM pipeline_runs
  WHERE status = 'failed' AND job_id = (SELECT job_id FROM req)
), locked AS (
  UPDATE upload_jobs j SET match_status = 'RUNNING', match_started_at = now()
  FROM req
  WHERE req.mode = 'upload' AND j.job_id = req.job_id AND j.status = 'COMPLETED'
    AND (j.match_status IS NULL
         OR (j.match_status = 'RUNNING' AND j.match_started_at < now() - interval '15 minutes')
         OR (j.match_status = 'FAILED' AND (SELECT n FROM failures) < 3))
  RETURNING j.job_id
), abandoned AS (  -- a re-claimed job's previous run died: close it (data-modifying CTEs always run)
  UPDATE pipeline_runs SET status = 'failed', finished_at = now(),
         error = 'abandoned: job re-claimed after a stale lock'
  WHERE status = 'running' AND job_id = (SELECT job_id FROM locked)
  RETURNING 1
)
INSERT INTO pipeline_runs (mode, job_id, scope_product_ids)
SELECT req.mode, (SELECT job_id FROM locked),
       CASE WHEN req.mode = 'products'
            THEN ARRAY(SELECT jsonb_array_elements_text(req.product_ids))::uuid[] END
FROM req
WHERE req.mode = 'products' OR EXISTS (SELECT 1 FROM locked)
RETURNING run_id::text, mode, job_id::text;
