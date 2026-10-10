-- 012_composed_emails.sql: every matched user's email is composed and kept, not only the sent ones.
--
-- The SES sandbox (200 emails a day, verified recipients only) limits REAL sends to a demo cap
-- of 5 per run. Workflow C still builds each user's personalized email (C1, in batches) and
-- stores its subject and text here, so the notification step is complete for every user and
-- auditable; only delivery is capped. Additive: NULL on older rows.
ALTER TABLE notifications ADD COLUMN subject text, ADD COLUMN body_text text;
