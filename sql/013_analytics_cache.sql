-- 013_analytics_cache.sql: an upload's analytics are computed once, not once per Lambda container.
--
-- The charts of a 10,000-user upload aggregate ~250,000 matches: seconds on a db.t4g.micro, and
-- more while a matching run is busy. Every new api container used to recompute them, and under
-- load a request could pass the API timeout ("internal error"). The api now stores the result
-- here, keyed by what the charts depend on (when the upload was matched or cleared).
CREATE TABLE analytics_cache (
    job_id      uuid PRIMARY KEY REFERENCES upload_jobs (job_id) ON DELETE CASCADE,
    version     text NOT NULL,          -- matched_at|purged_at when the payload was computed
    payload     jsonb NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now()
);
