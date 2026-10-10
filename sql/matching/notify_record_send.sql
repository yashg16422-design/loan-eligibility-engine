-- Workflow C · Record ONE send, right after SES answers (inside the send loop).
-- Param: $1 = one JSON object {run_id, user_id, alias_email, status ('sent'|'failed'),
--         ses_message_id, error, subject, body_text}.
-- One JSON parameter, not eight: n8n's query parameters break on free text with newlines
-- (the email body), while a JSON string is passed through intact (found live).
-- Recording each send immediately means a crash mid-loop never emails anyone twice: the
-- re-run's "Users to email" skips users whose matches are already notified, and its demo cap
-- counts the sends already recorded. A failed send stays un-notified for a later retry.
WITH s AS (
    SELECT run_id, user_id, alias_email, status, nullif(ses_message_id, '') AS ses_message_id,
           nullif(error, '') AS error, nullif(subject, '') AS subject,
           nullif(body_text, '') AS body_text
    FROM jsonb_to_record($1::jsonb) AS r(run_id uuid, user_id uuid, alias_email text, status text,
                                         ses_message_id text, error text, subject text,
                                         body_text text)
), ins AS (
    INSERT INTO notifications (user_id, alias_email, job_id, run_id, status, ses_message_id, error,
                               subject, body_text)
    SELECT s.user_id, s.alias_email, r.job_id, s.run_id, s.status, s.ses_message_id, s.error,
           s.subject, s.body_text
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
