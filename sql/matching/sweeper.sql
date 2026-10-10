-- Workflow B · Sweeper (every 10 min): which upload jobs need a matching run now.
-- No params. Also closes ghost runs. Shared with tests/integration (same file, same SQL).
--
-- A job is picked when it completed ingest and:
--   * was never matched (webhook missed: n8n down, network blip), or
--   * its run died holding the lock (RUNNING for > 15 min), or
--   * its run FAILED (a transient DB/LLM error) and it has failed fewer than 3 times, the
--     last failure at least 10 minutes ago (bounded retry with backoff; after 3 it stays
--     FAILED for a human to look at, and Workflow E has already alerted).
WITH dead AS (  -- n8n's hard timeout is 10 min: a run still 'running' after 30 is dead
  UPDATE pipeline_runs SET status = 'failed', finished_at = now(),
         error = 'abandoned: still running after 30 min (n8n restart or timeout)'
  WHERE status = 'running' AND started_at < now() - interval '30 minutes'
  RETURNING 1
), failures AS (
  SELECT job_id, count(*) AS n, max(coalesce(finished_at, started_at)) AS last_at
  FROM pipeline_runs WHERE status = 'failed' AND job_id IS NOT NULL GROUP BY job_id
)
SELECT 'upload' AS mode, j.job_id::text AS job_id, '' AS product_ids
FROM upload_jobs j LEFT JOIN failures f USING (job_id)
WHERE j.status = 'COMPLETED'
  AND (j.match_status IS NULL
       OR (j.match_status = 'RUNNING' AND j.match_started_at < now() - interval '15 minutes')
       OR (j.match_status = 'FAILED' AND coalesce(f.n, 0) < 3 AND f.last_at < now() - interval '10 minutes'))
ORDER BY j.completed_at
LIMIT 5;
