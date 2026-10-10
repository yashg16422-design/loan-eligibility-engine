-- Workflow C1 · Store a batch of composed emails. Params: $1 run_id, $2 JSON array of
-- {user_id, subject, body_text}. Returns how many were stored and how many remain, which is
-- what C's loop decides on.
WITH composed AS (
    SELECT * FROM jsonb_to_recordset($2::jsonb) AS c(user_id text, subject text, body_text text)
), saved AS (
    UPDATE notifications n SET subject = c.subject, body_text = c.body_text
    FROM composed c
    WHERE n.run_id = $1::uuid AND n.status = 'skipped_demo' AND n.subject IS NULL
      AND n.user_id = c.user_id::uuid
    RETURNING 1
)
SELECT $1::text AS run_id,
       (SELECT count(*) FROM saved)::int AS composed,
       ((SELECT count(*) FROM notifications
         WHERE run_id = $1::uuid AND status = 'skipped_demo' AND subject IS NULL)
        - (SELECT count(*) FROM saved))::int AS remaining;
