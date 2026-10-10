-- 005_accounts.sql: real user accounts (Amazon Cognito) linked to saved eligibility profiles.
--
-- Cognito owns identity: passwords never reach this database. An account row is created
-- the first time a signed-in user calls the API, keyed by Cognito's immutable `sub`.
-- Additive only: no existing table changes, so Workflows A/B/C are untouched.

CREATE TABLE accounts (
    account_id   text PRIMARY KEY,                 -- Cognito `sub` (stable, never reused)
    email        text NOT NULL,
    daily_picks  boolean NOT NULL DEFAULT true,    -- "send me my top picks every morning"
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX accounts_email_idx ON accounts (lower(email));

-- The eligibility checks an account saved. One profile can belong to one account only:
-- whoever first saves a check owns it (the dashboard link proves they ran it).
CREATE TABLE account_profiles (
    account_id text NOT NULL REFERENCES accounts (account_id) ON DELETE CASCADE,
    user_id    uuid NOT NULL UNIQUE REFERENCES users (user_id) ON DELETE CASCADE,
    saved_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, user_id)
);
