-- Workflow C · Finish: after the send loop. Params: $1 run_id.
-- Sent and failed rows were already written one by one (notify_record_send.sql). Every OTHER
-- user with new matches is recorded as skipped_demo (production would email them) and marked
-- notified, so nobody is emailed twice; then the run's counters are set from the table, which
-- makes a re-run idempotent.
WITH run AS (
    SELECT job_id FROM pipeline_runs WHERE run_id = $1::uuid
), rest AS (
    SELECT DISTINCT m.user_id FROM matches m
    WHERE m.match_run_id = $1::uuid AND m.status = 'active' AND m.notified_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM notifications n WHERE n.run_id = $1::uuid AND n.user_id = m.user_id)
), ins_skip AS (
    INSERT INTO notifications (user_id, alias_email, job_id, run_id, status, error)
    SELECT user_id, '(demo cap: not sent)', (SELECT job_id FROM run), $1::uuid, 'skipped_demo',
           'demo cap reached: production would email this user'
    FROM rest
    RETURNING 1
), mark AS (
    UPDATE matches SET notified_at = now()
    WHERE match_run_id = $1::uuid AND status = 'active' AND notified_at IS NULL
      AND user_id IN (SELECT user_id FROM rest)
    RETURNING 1
)
-- Counts read the table as it was before this statement (sends recorded earlier) plus what
-- this statement inserts.
UPDATE pipeline_runs SET
    emails_sent = (SELECT count(*) FROM notifications WHERE run_id = $1::uuid AND status = 'sent'),
    emails_failed = (SELECT count(*) FROM notifications WHERE run_id = $1::uuid AND status = 'failed'),
    emails_skipped_demo = (SELECT count(*) FROM notifications WHERE run_id = $1::uuid AND status = 'skipped_demo')
                          + (SELECT count(*) FROM ins_skip)
WHERE run_id = $1::uuid
RETURNING run_id::text, emails_sent, emails_failed, emails_skipped_demo,
          (SELECT count(*) FROM mark) AS matches_marked_notified,
          (SELECT count(*) FROM ins_skip) AS notification_rows;
