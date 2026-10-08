-- 001_schema.sql: engine data model for database `app` (PLAN.md §8).
-- Applied once by the migrate Lambda inside a transaction and recorded in schema_migrations.
--
-- Conventions:
--   * Enum-like columns are TEXT + CHECK rather than Postgres ENUM types: adding a value
--     later is a one-line constraint change, not an ALTER TYPE dance.
--   * CHECK constraints mirror the Python validator (defense in depth: even a buggy
--     writer cannot store an out-of-range user).
--   * Counters that are "not measured yet" stay NULL rather than 0, so the Treasure Hunt
--     numbers never show a fake zero.

-- ---------------------------------------------------------------------------
-- Ingestion
-- ---------------------------------------------------------------------------

CREATE TABLE upload_jobs (
    job_id            uuid PRIMARY KEY,
    s3_key            text NOT NULL UNIQUE,
    original_filename text,
    status            text NOT NULL DEFAULT 'AWAITING_UPLOAD'
                      CHECK (status IN ('AWAITING_UPLOAD', 'PROCESSING', 'COMPLETED', 'FAILED')),
    -- Incremented by each ingest attempt; lets the API tell "never arrived" from "retrying".
    attempts          int NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    total_rows        int,
    inserted          int,
    updated           int,
    unchanged         int,
    rejected          int,
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    -- Workflow B's lock + progress (PLAN.md §11.2). NULL = not picked up yet.
    match_status      text CHECK (match_status IN ('RUNNING', 'DONE', 'FAILED')),
    match_started_at  timestamptz,
    matched_at        timestamptz
);
CREATE INDEX upload_jobs_status_idx ON upload_jobs (status);
CREATE INDEX upload_jobs_match_status_idx ON upload_jobs (match_status);

CREATE TABLE users (
    user_id           uuid PRIMARY KEY,
    name              text,
    -- Deliberately NOT unique: the sample reuses one email across several user_ids.
    email             text NOT NULL CHECK (email = lower(email) AND email LIKE '%@%'),
    monthly_income    int NOT NULL CHECK (monthly_income > 0),
    credit_score      int NOT NULL CHECK (credit_score BETWEEN 300 AND 900),
    employment_status text NOT NULL
                      CHECK (employment_status IN ('salaried', 'self_employed', 'business')),
    age               int NOT NULL CHECK (age BETWEEN 18 AND 100),
    -- The job that last inserted or CHANGED this user; Workflow B matches exactly these.
    upload_job_id     uuid REFERENCES upload_jobs (job_id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX users_upload_job_id_idx ON users (upload_job_id);
CREATE INDEX users_email_idx ON users (email);

CREATE TABLE upload_rejects (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id     uuid NOT NULL REFERENCES upload_jobs (job_id) ON DELETE CASCADE,
    row_number int NOT NULL,
    raw_line   text NOT NULL,
    reason     text NOT NULL
);
CREATE INDEX upload_rejects_job_id_idx ON upload_rejects (job_id, row_number);

-- ---------------------------------------------------------------------------
-- Loan products (Workflow A)
-- ---------------------------------------------------------------------------

CREATE TABLE loan_products (
    product_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lender              text NOT NULL,
    source_url          text NOT NULL,
    product_name        text NOT NULL,
    product_url         text,
    interest_rate_min   numeric(5, 2) CHECK (interest_rate_min >= 0),  -- % p.a.
    interest_rate_max   numeric(5, 2) CHECK (interest_rate_max >= 0),
    rate_type           text NOT NULL DEFAULT 'unknown'
                        CHECK (rate_type IN ('reducing', 'flat', 'unknown')),
    -- NULL criterion = "lender states no limit" = passes (PLAN.md §10 step 6).
    min_monthly_income  int CHECK (min_monthly_income > 0),
    min_credit_score    int CHECK (min_credit_score BETWEEN 300 AND 900),
    max_credit_score    int CHECK (max_credit_score BETWEEN 300 AND 900),
    min_age             int CHECK (min_age BETWEEN 18 AND 100),
    max_age             int CHECK (max_age BETWEEN 18 AND 100),
    -- NULL = all employment types accepted.
    employment_types    text[] CHECK (
                            employment_types <@ ARRAY['salaried', 'self_employed', 'business']
                        ),
    loan_amount_min     bigint CHECK (loan_amount_min >= 0),
    loan_amount_max     bigint CHECK (loan_amount_max >= 0),
    tenure_months_max   int CHECK (tenure_months_max > 0),
    -- Criteria we can't check from the 5 CSV fields; feeds the "conditional" tier / LLM stage.
    other_criteria_text text,
    raw_extracted       jsonb,           -- the LLM's raw strings, kept for audit
    criteria_json       jsonb,           -- normalized criteria
    -- Hash of the normalized criteria text; unchanged hash = zero LLM calls on re-crawl.
    criteria_hash       text NOT NULL,
    is_active           boolean NOT NULL DEFAULT true,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    last_changed_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_url, product_name),
    CHECK (interest_rate_min IS NULL OR interest_rate_max IS NULL
           OR interest_rate_min <= interest_rate_max),
    CHECK (min_credit_score IS NULL OR max_credit_score IS NULL
           OR min_credit_score <= max_credit_score),
    CHECK (min_age IS NULL OR max_age IS NULL OR min_age <= max_age)
);
CREATE INDEX loan_products_active_idx ON loan_products (is_active);

CREATE TABLE crawl_runs (
    run_id         uuid NOT NULL,
    source_url     text NOT NULL,
    status         text NOT NULL CHECK (status IN ('ok', 'failed', 'fixture')),
    products_found int,
    error          text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    PRIMARY KEY (run_id, source_url)
);

-- ---------------------------------------------------------------------------
-- Matching (Workflow B) + Treasure Hunt evidence
-- ---------------------------------------------------------------------------

-- One row per Workflow B run: the measured funnel quoted in the README.
CREATE TABLE pipeline_runs (
    run_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mode                text NOT NULL CHECK (mode IN ('upload', 'products')),
    job_id              uuid REFERENCES upload_jobs (job_id),
    status              text NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'done', 'failed')),
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    users_in            int,
    products_in         int,
    naive_pairs         bigint,          -- users x products: what a brute-force LLM would see
    pairs_after_sql     bigint,
    classes             int,
    class_product_pairs int,
    rule_decided        int,
    llm_candidates      int,
    llm_cache_hits      int,
    llm_calls           int,
    llm_input_tokens    int,
    llm_output_tokens   int,
    llm_cost_usd_est    numeric(12, 6),
    matches_new         int,
    matches_superseded  int,
    matches_unchanged   int,
    emails_sent         int,
    emails_skipped_demo int,
    emails_failed       int
);
CREATE INDEX pipeline_runs_job_id_idx ON pipeline_runs (job_id);

CREATE TABLE matches (
    match_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    product_id    uuid NOT NULL REFERENCES loan_products (product_id),
    job_id        uuid REFERENCES upload_jobs (job_id),
    match_run_id  uuid NOT NULL REFERENCES pipeline_runs (run_id),
    tier          text NOT NULL CHECK (tier IN ('eligible', 'conditional')),
    requirements  text,          -- e.g. "2 years work experience" (conditional tier)
    stage_decided text NOT NULL CHECK (stage_decided IN ('sql', 'rules', 'llm')),
    llm_reason    text,
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    superseded_at timestamptz,
    notified_at   timestamptz,
    CHECK ((status = 'superseded') = (superseded_at IS NOT NULL))
);
-- At most ONE active match per (user, product): makes re-runs idempotent (ON CONFLICT DO NOTHING).
CREATE UNIQUE INDEX matches_one_active_pair_uidx
    ON matches (user_id, product_id) WHERE status = 'active';
-- Workflow C's "who still needs an email" lookup stays small and fast.
CREATE INDEX matches_pending_notification_idx
    ON matches (user_id) WHERE status = 'active' AND notified_at IS NULL;
CREATE INDEX matches_run_id_idx ON matches (match_run_id);
CREATE INDEX matches_product_id_idx ON matches (product_id);

-- LLM decision cache: a (criteria, user-class) pair is judged once per prompt version.
CREATE TABLE llm_decisions (
    criteria_hash   text NOT NULL,
    class_signature text NOT NULL,
    prompt_version  text NOT NULL,
    tier            text NOT NULL CHECK (tier IN ('eligible', 'conditional', 'not_eligible')),
    requirements    text,
    reason          text,
    model_id        text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (criteria_hash, class_signature, prompt_version)
);

-- ---------------------------------------------------------------------------
-- Notification (Workflow C) + errors
-- ---------------------------------------------------------------------------

CREATE TABLE notifications (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        uuid NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    alias_email    text NOT NULL,  -- always a verified +alias, never the CSV address
    job_id         uuid REFERENCES upload_jobs (job_id),
    run_id         uuid REFERENCES pipeline_runs (run_id),
    status         text NOT NULL CHECK (status IN ('sent', 'skipped_demo', 'failed')),
    ses_message_id text,
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_run_id_idx ON notifications (run_id);
CREATE INDEX notifications_job_id_idx ON notifications (job_id);

CREATE TABLE workflow_errors (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow     text NOT NULL,
    node         text,
    message      text NOT NULL,
    execution_id text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
