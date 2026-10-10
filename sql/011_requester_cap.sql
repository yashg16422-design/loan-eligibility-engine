-- 011_requester_cap.sql: a per-requester daily cap on instant checks.
--
-- The api Lambda stores an HMAC of the caller's source IP (keyed with its token secret), never
-- the IP itself, so one visitor cannot use up the shared daily budget of instant checks.
-- Additive: NULL on older rows and on CSV uploads (those are capped per account instead).
ALTER TABLE upload_jobs ADD COLUMN requester_hash text;
CREATE INDEX upload_jobs_requester_idx ON upload_jobs (requester_hash, created_at)
    WHERE requester_hash IS NOT NULL;
