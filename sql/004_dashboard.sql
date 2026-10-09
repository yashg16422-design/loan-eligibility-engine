-- 004_dashboard.sql: the borrower dashboard and the instant eligibility check.
--
-- Additive only: no existing table loses a column, so the matching pipeline (Workflows
-- A/B/C) is untouched.

-- One row per borrower who saved anything in the dashboard. Arrays of product ids keep
-- reads to a single row; the caps stop a client from growing a row without bound.
CREATE TABLE user_preferences (
    user_id     uuid PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    shortlist   uuid[] NOT NULL DEFAULT '{}' CHECK (cardinality(shortlist) <= 50),
    top3        uuid[] NOT NULL DEFAULT '{}' CHECK (cardinality(top3) <= 3),
    hidden      uuid[] NOT NULL DEFAULT '{}' CHECK (cardinality(hidden) <= 200),
    alerts      boolean NOT NULL DEFAULT false,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Where a job came from: a CSV upload, or one person's instant check through the same
-- pipeline. Lets the API cap instant checks per day (SES sandbox quota) and lets the ops
-- view tell them apart.
ALTER TABLE upload_jobs
    ADD COLUMN source text NOT NULL DEFAULT 'csv' CHECK (source IN ('csv', 'instant_check'));
CREATE INDEX upload_jobs_source_created_idx ON upload_jobs (source, created_at);
