-- 006_data_reset.sql: delete demo data on purpose (one upload's users, every uploaded user, or
-- one person's checks) while lender products, run history and accounts stay.

-- Set when an operator deleted this upload's users. The job row stays because pipeline_runs,
-- matches and notifications history point at it (the Treasure Hunt evidence is never deleted).
ALTER TABLE upload_jobs ADD COLUMN purged_at timestamptz;

-- ON DELETE CASCADE from users finds child rows by user_id. matches only had a PARTIAL index on
-- user_id (active rows) and notifications none, so deleting 10,000 users would scan both tables
-- once per user. With these the delete is an index lookup per user.
CREATE INDEX matches_user_id_idx ON matches (user_id);
CREATE INDEX notifications_user_id_idx ON notifications (user_id);
