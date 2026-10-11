-- Workflow B · Sweeper, second task: runs that wrote their matches but never recorded their
-- emails, because n8n lost its database or restarted between Stage 3 and Workflow C (found live:
-- the job showed "matched" and the screen waited for emails forever). No params.
--
-- Picked: a run with new matches, no email counters, whose proofs did not fail, that either
-- finished more than 15 minutes ago (C normally ends within a few minutes of B1) or was closed as
-- abandoned by the sweeper. Workflow B re-runs the post-write proof first and only then calls C,
-- which is idempotent: users already emailed are skipped, nobody gets two emails.
SELECT r.run_id::text AS run_id
FROM pipeline_runs r
WHERE r.matches_new > 0
  AND r.emails_sent IS NULL
  AND coalesce(r.prewrite_ok, true) AND coalesce(r.correctness_ok, true)
  AND r.started_at > now() - interval '1 day'
  AND (   (r.status = 'done'   AND r.finished_at < now() - interval '15 minutes')
       OR (r.status = 'failed' AND r.error LIKE 'abandoned%'))
ORDER BY r.started_at
LIMIT 2;
