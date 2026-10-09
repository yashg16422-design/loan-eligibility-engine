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

-- app_ingest: api, ingest and dlq-handler Lambdas.
-- Writes the ingestion tables; reads match/notify progress for the UI tracker.
GRANT SELECT, INSERT, UPDATE ON upload_jobs, users, upload_rejects TO app_ingest;
GRANT SELECT ON pipeline_runs, notifications TO app_ingest;

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
