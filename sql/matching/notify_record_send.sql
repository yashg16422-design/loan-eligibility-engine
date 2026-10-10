-- Workflow C · Record ONE send, right after SES answers (inside the send loop).
-- Params: $1 run_id, $2 user_id, $3 alias_email, $4 status ('sent'|'failed'),
--         $5 ses_message_id ('' if none), $6 error ('' if none).
-- Recording each send immediately means a crash mid-loop never emails anyone twice: the
-- re-run's "Users to email" skips users whose matches are already notified, and its demo cap
-- counts the sends already recorded. A failed send stays un-notified for a later retry.
WITH s AS (
    SELECT $1::uuid AS run_id, $2::uuid AS user_id, $3::text AS alias_email, $4::text AS status,
           nullif($5::text, '') AS ses_message_id, nullif($6::text, '') AS error
), ins AS (
    INSERT INTO notifications (user_id, alias_email, job_id, run_id, status, ses_message_id, error)
    SELECT s.user_id, s.alias_email, r.job_id, s.run_id, s.status, s.ses_message_id, s.error
    FROM s JOIN pipeline_runs r ON r.run_id = s.run_id
    RETURNING 1
), mark AS (
    UPDATE matches m SET notified_at = now()
    FROM s
    WHERE s.status = 'sent' AND m.match_run_id = s.run_id AND m.user_id = s.user_id
      AND m.status = 'active' AND m.notified_at IS NULL
    RETURNING 1
)
SELECT s.user_id::text, s.alias_email, s.status, s.ses_message_id, s.error,
       (SELECT count(*) FROM ins) AS recorded, (SELECT count(*) FROM mark) AS matches_marked
FROM s;
