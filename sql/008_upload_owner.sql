-- 008_upload_owner.sql: bulk uploads belong to a signed-in (merchant) account.
--
-- Several people (merchants, reviewers) share one database. Each sees and deletes only the
-- uploads made from their own account; admins see all. Older uploads have no owner (NULL):
-- only an admin can delete those. Instant checks are never owned here (they are consumer data).
ALTER TABLE upload_jobs
    ADD COLUMN account_id text REFERENCES accounts (account_id) ON DELETE SET NULL;
CREATE INDEX upload_jobs_account_idx ON upload_jobs (account_id, created_at DESC);
