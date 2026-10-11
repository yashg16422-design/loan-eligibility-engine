-- Workflow B · A recovered run passed its proof again: record it as done before C emails it.
-- Params: $1 run_id.
UPDATE pipeline_runs
SET status = 'done', finished_at = coalesce(finished_at, now()),
    error = CASE WHEN status = 'failed' THEN 'recovered by the sweeper: proof re-run, emails sent'
                 ELSE error END
WHERE run_id = $1::uuid
RETURNING run_id::text, status, correctness_ok;
