-- R__grants.sql: least-privilege grants (PLAN.md §7).
-- "R__" = repeatable: the migrate Lambda re-applies this file on EVERY run, after the
-- numbered migrations, so new tables are never left without grants. GRANT/REVOKE are
-- idempotent, so running it twice changes nothing.
-- The roles themselves are created by the migrate Lambda (passwords come from
-- Secrets Manager and must never appear in a .sql file).

-- Nobody connects to `app` unless granted below (PG >= 15 already revokes CREATE on public).
REVOKE ALL ON DATABASE app FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE app TO app_ingest, n8n_workflows;
GRANT USAGE ON SCHEMA public TO app_ingest, n8n_workflows;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_ingest, n8n_workflows;

-- app_ingest: the api and ingest Lambdas.
-- Writes the ingestion tables; reads match/notify progress for the UI tracker.
GRANT SELECT, INSERT, UPDATE ON upload_jobs, users, upload_rejects TO app_ingest;
GRANT SELECT ON pipeline_runs, notifications TO app_ingest;
-- Stop on a stalled matching run closes its run row (only these three columns).
GRANT UPDATE (status, finished_at, error) ON pipeline_runs TO app_ingest;
-- Borrower dashboard + ops view (api Lambda): read the results, own only the preferences.
GRANT SELECT ON matches, loan_products, criteria_rules, crawl_runs, workflow_errors TO app_ingest;
GRANT SELECT, INSERT, UPDATE ON user_preferences TO app_ingest;
-- Accounts (Cognito-backed): the api Lambda creates and links accounts, never deletes one.
GRANT SELECT, INSERT, UPDATE ON accounts, account_profiles TO app_ingest;
-- Data reset (006): an admin deletes an upload's users, a person deletes their own check, an
-- account unlinks its saved checks. Child rows (matches, notifications, preferences, links)
-- go by ON DELETE CASCADE, which runs as the table owner, so no DELETE grant is needed there.
GRANT DELETE ON users, account_profiles TO app_ingest;
-- Analytics computed once per upload version (013), shared by every api container.
GRANT SELECT, INSERT, UPDATE ON analytics_cache TO app_ingest;

-- n8n_workflows: the n8n Postgres credential (Workflows A, B, C).
-- Reads users; may only touch the match-progress columns of upload_jobs.
GRANT SELECT ON users, upload_jobs TO n8n_workflows;
GRANT UPDATE (match_status, match_started_at, matched_at) ON upload_jobs TO n8n_workflows;
GRANT SELECT, INSERT, UPDATE
    ON loan_products, crawl_runs, matches, criteria_rules, match_classes, match_pairs,
       pipeline_runs, notifications, workflow_errors
    TO n8n_workflows;
-- The crawler's config is read-only for n8n: sources are changed by a migration or a DBA.
GRANT SELECT ON crawl_sources TO n8n_workflows;

-- PostgreSQL 17 MAINTAIN: lets Workflow B ANALYZE the tables it bulk-writes (fresh planner
-- statistics between Stage 1 and Stage 3), without owning them or being an admin.
GRANT MAINTAIN ON match_classes, match_pairs, matches TO n8n_workflows;

-- Guards (sessions opened after this runs): no Workflow statement outlives its execution.
-- n8n stops an execution after 10 minutes but cannot stop the SQL it started, which would keep
-- running and holding locks; the same limit on the database side ends it. An open transaction
-- left idle (a crashed client) is closed too.
ALTER ROLE n8n_workflows SET statement_timeout = '10min';
ALTER ROLE n8n_workflows SET idle_in_transaction_session_timeout = '10min';
ALTER ROLE app_ingest SET idle_in_transaction_session_timeout = '10min';
